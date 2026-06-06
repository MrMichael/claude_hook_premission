import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone

DEFAULT_SOCKET_PATH = "/tmp/claude-auto-approve.sock"
DEFAULT_PID_PATH = "/tmp/claude-auto-approve.pid"
DEFAULT_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def match_rule(request, config):
    """Match request against rules in priority order. Return dict with action and reason."""
    rules = sorted(config.get("rules", []), key=lambda r: r.get("priority", 999))
    for rule in rules:
        pattern = rule.get("pattern", {})
        # Check tool match (exact)
        if "tool" in pattern:
            if pattern["tool"] != request.get("tool"):
                continue
        # Check command_contains match (any substring, case-insensitive)
        if "command_contains" in pattern:
            cmd = request.get("command", "").lower()
            if not any(sub.lower() in cmd for sub in pattern["command_contains"]):
                continue
        return {"action": rule["action"], "reason": f"rule:{rule['name']}"}
    # No rule matched — use default
    return {"action": config.get("default_action", "deny"), "reason": "default"}


def load_config(config_path):
    with open(config_path) as f:
        import yaml
        return yaml.safe_load(f)


def run_foreground(config_path):
    """Run the daemon in the foreground (for testing/manual use)."""
    config = load_config(config_path)
    socket_path = config.get("socket_path", DEFAULT_SOCKET_PATH)
    log_path = os.path.expanduser(config.get("log_path", "~/.claude/auto-approve.log"))

    # Remove stale socket
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass

    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    os.chmod(socket_path, 0o600)
    server.listen(5)

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    server.settimeout(1.0)  # Check signals every second

    while running:
        try:
            conn, _ = server.accept()
        except socket.timeout:
            continue

        try:
            f = conn.makefile("r", buffering=1)
            line = f.readline(65536)
            if not line:
                conn.close()
                continue

            request = json.loads(line)
            result = match_rule(request, config)

            action = result["action"]
            decision = action if action in ("allow", "deny") else "deny"

            # Handle prompt action
            if action == "prompt":
                if shutil.which("zenity") and os.environ.get("DISPLAY"):
                    # Find the matched rule's prompt_message
                    rules = sorted(config.get("rules", []), key=lambda r: r["priority"])
                    matched_rule = next(
                        (r for r in rules if r["name"] == result["reason"].replace("rule:", "")),
                        None
                    )
                    msg_template = "Allow: {command}?\n\n{rationale}"
                    if matched_rule:
                        msg_template = matched_rule.get("prompt_message", msg_template)

                    msg = msg_template.format(
                        command=request.get("command", ""),
                        rationale=request.get("rationale", ""),
                    )
                    try:
                        rc = subprocess.run(
                            ["zenity", "--question", "--text", msg, "--title", "Claude Code Permission"],
                            timeout=30,
                        )
                        decision = "allow" if rc.returncode == 0 else "deny"
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        decision = "deny"
                else:
                    decision = "deny"

            reason = result["reason"]
            if action == "prompt":
                reason = "prompt:user-allowed" if decision == "allow" else "prompt:user-denied"

            # Log
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool": request.get("tool", ""),
                "decision": decision.upper(),
                "reason": reason,
                "command_summary": str(request.get("command", ""))[:200],
                "rationale": request.get("rationale", ""),
            }
            with open(log_path, "a") as logf:
                logf.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            response = {
                "decision": decision,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except (json.JSONDecodeError, Exception):
            try:
                err_resp = json.dumps({"decision": "deny", "reason": "error"}) + "\n"
                conn.sendall(err_resp.encode("utf-8"))
            except Exception:
                pass
        finally:
            conn.close()

    server.close()
    os.unlink(socket_path)


def do_start(config_path):
    """Fork to background and start daemon."""
    pid = os.fork()
    if pid > 0:
        # Parent: write PID and exit
        with open(DEFAULT_PID_PATH, "w") as f:
            f.write(str(pid))
        print(f"Daemon started (PID: {pid})")
        return

    # Child: become daemon
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)

    run_foreground(config_path)
    sys.exit(0)


def do_stop():
    """Stop running daemon by PID file."""
    try:
        with open(DEFAULT_PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Daemon stopped (PID: {pid})")
    except (FileNotFoundError, ProcessLookupError, ValueError):
        print("Daemon not running")
        try:
            os.unlink(DEFAULT_PID_PATH)
        except FileNotFoundError:
            pass
    try:
        os.unlink(DEFAULT_SOCKET_PATH)
    except FileNotFoundError:
        pass


def do_status():
    """Print daemon status."""
    running = False
    pid = None
    try:
        with open(DEFAULT_PID_PATH) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        running = True
    except (FileNotFoundError, ProcessLookupError, ValueError):
        pass

    if running:
        print(f"Daemon: RUNNING (PID: {pid})")
    else:
        print("Daemon: NOT RUNNING")

    log_path = os.path.expanduser("~/.claude/auto-approve.log")
    try:
        with open(log_path) as f:
            lines = f.readlines()
            if lines:
                print(f"\nRecent decisions ({len(lines)} total):")
                for line in lines[-5:]:
                    entry = json.loads(line)
                    print(f"  {entry['timestamp']} | {entry['tool']:12s} | {entry['decision']:5s} | {entry['reason']}")
    except FileNotFoundError:
        print("  (no log yet)")


def main():
    parser = argparse.ArgumentParser(description="Claude Code Auto-Approval Daemon")
    parser.add_argument("command", choices=["start", "stop", "status", "foreground"])
    parser.add_argument("--config", default=os.path.join(DEFAULT_CONFIG_DIR, "config.yaml"),
                        help="Path to config.yaml")
    args = parser.parse_args()

    if args.command == "start":
        do_start(args.config)
    elif args.command == "stop":
        do_stop()
    elif args.command == "status":
        do_status()
    elif args.command == "foreground":
        run_foreground(args.config)


if __name__ == "__main__":
    main()
