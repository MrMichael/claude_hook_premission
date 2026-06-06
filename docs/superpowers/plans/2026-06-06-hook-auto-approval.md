# Hook Auto-Approval System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a hook-based auto-approval daemon that intercepts Claude Code permission prompts, auto-approves routine operations, pops up GUI confirmation for destructive commands, and notifies user when session goes idle.

**Architecture:** Two independent hook paths. Path 1: PreToolUse → auto-approve-cli → Unix socket → daemon (rule engine + zenity prompt). Path 2: Stop hook → idle-notify → zenity info popup. Config in YAML, audit log in JSON-lines.

**Tech Stack:** Python 3 (stdlib only: socket, json, subprocess, signal, os), YAML (PyYAML), zenity (system package), pytest

---

## File Structure

```
hook_premission/
├── auto-approve-cli              # PreToolUse hook client (Python, no deps)
├── idle-notify                   # Stop hook idle notification (shell script)
├── auto-approve-daemon.py        # Background daemon: rule engine + socket server
├── config.yaml                   # Default rule configuration
├── tests/
│   ├── test_rules.py             # Rule matching unit tests
│   ├── test_protocol.py          # JSON protocol + client tests
│   └── test_daemon.py            # Daemon lifecycle integration tests
└── README.md                     # Install, usage, logrotate
```

**Boundaries:**
- `auto-approve-cli`: Reads env vars → sends JSON → reads response → exits. No imports from daemon. ~50 lines.
- `idle-notify`: Fire-and-forget. Calls zenity. 15 lines shell.
- `auto-approve-daemon.py`: Socket server + rule engine + zenity subprocess + logging. ~200 lines.
- `config.yaml`: User-editable rules. Ships with safe defaults.

---

### Task 1: Project Scaffold + Dependencies

**Files:**
- Create: `tests/__init__.py`

- [ ] **Step 1: Verify Python + dependencies**

Run: `python3 --version`
Expected: Python 3.8+

Run: `python3 -c "import yaml; print(yaml.__version__)"`
If fails: `pip install pyyaml`

Run: `which zenity`
Expected: `/usr/bin/zenity` or similar. If missing: `sudo apt install zenity`

- [ ] **Step 2: Create project structure**

```bash
mkdir -p /home/michael/Documents/repository/agent_harness/hook_premission/tests
touch /home/michael/Documents/repository/agent_harness/hook_premission/tests/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add tests/__init__.py
git commit -m "chore: scaffold project structure"
```

---

### Task 2: Rule Engine — TDD

**Files:**
- Create: `tests/test_rules.py`
- Create: `auto-approve-daemon.py` (rule engine portion)

- [ ] **Step 1: Write failing test — exact tool match, allow**

```python
# tests/test_rules.py
import sys
sys.path.insert(0, '/home/michael/Documents/repository/agent_harness/hook_premission')

from auto_approve_daemon import match_rule

def test_exact_tool_match_allow():
    config = {
        "default_action": "deny",
        "rules": [
            {
                "priority": 10,
                "name": "web-allow",
                "pattern": {"tool": "WebFetch"},
                "action": "allow"
            }
        ]
    }
    request = {"tool": "WebFetch", "command": "https://example.com", "rationale": "test"}
    result = match_rule(request, config)
    assert result["action"] == "allow"
    assert result["reason"] == "rule:web-allow"
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_rules.py::test_exact_tool_match_allow -v`
Expected: FAIL (no module `auto_approve_daemon`)

- [ ] **Step 3: Write minimal implementation**

```python
# auto-approve-daemon.py
import os
import json
import socket
import signal
import subprocess
import sys
import argparse
import shutil
from datetime import datetime, timezone

import yaml


def match_rule(request, config):
    """Match request against rules in priority order. Return dict with action and reason."""
    rules = sorted(config.get("rules", []), key=lambda r: r["priority"])
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_rules.py::test_exact_tool_match_allow -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_rules.py auto-approve-daemon.py
git commit -m "feat: rule engine — exact tool match"
```

---

### Task 3: Rule Engine — More Cases

**Files:**
- Modify: `tests/test_rules.py`

- [ ] **Step 1: Add tests for remaining match types**

```python
def test_priority_order_first_match_wins():
    config = {
        "default_action": "deny",
        "rules": [
            {"priority": 1, "name": "high-deny", "pattern": {"tool": "Bash"}, "action": "deny"},
            {"priority": 10, "name": "low-allow", "pattern": {"tool": "Bash"}, "action": "allow"},
        ]
    }
    result = match_rule({"tool": "Bash", "command": "ls"}, config)
    assert result["action"] == "deny"
    assert result["reason"] == "rule:high-deny"


def test_default_action_when_no_match():
    config = {
        "default_action": "allow",
        "rules": [
            {"priority": 1, "name": "only-bash", "pattern": {"tool": "Bash"}, "action": "deny"}
        ]
    }
    result = match_rule({"tool": "WebFetch", "command": "https://x.com"}, config)
    assert result["action"] == "allow"
    assert result["reason"] == "default"


def test_command_contains_substring_case_insensitive():
    config = {
        "default_action": "deny",
        "rules": [
            {
                "priority": 50,
                "name": "destructive",
                "pattern": {"tool": "Bash", "command_contains": ["rm ", "rmdir"]},
                "action": "prompt"
            }
        ]
    }
    result = match_rule({"tool": "Bash", "command": "RM -rf /tmp/cache"}, config)
    assert result["action"] == "prompt"
    assert result["reason"] == "rule:destructive"


def test_no_rules_uses_default():
    config = {"default_action": "allow", "rules": []}
    result = match_rule({"tool": "Bash", "command": "ls"}, config)
    assert result["action"] == "allow"
    assert result["reason"] == "default"


def test_missing_command_field_still_matches_tool():
    config = {
        "default_action": "deny",
        "rules": [
            {"priority": 10, "name": "write-allow", "pattern": {"tool": "Write"}, "action": "allow"}
        ]
    }
    result = match_rule({"tool": "Write"}, config)
    assert result["action"] == "allow"
```

- [ ] **Step 2: Run tests, confirm pass**

Run: `pytest tests/test_rules.py -v`
Expected: All PASS (implementation already handles these from Task 2)

- [ ] **Step 3: Commit**

```bash
git add tests/test_rules.py
git commit -m "test: rule engine — priority, default, substring, edge cases"
```

---

### Task 4: JSON Protocol + Client

**Files:**
- Create: `tests/test_protocol.py`
- Create: `auto-approve-cli`

- [ ] **Step 1: Write failing test — client builds correct JSON**

```python
# tests/test_protocol.py
import json
import subprocess
import os
import sys

CLI_PATH = "/home/michael/Documents/repository/agent_harness/hook_premission/auto-approve-cli"


def test_client_builds_json_from_env():
    """Client reads env vars and produces correct JSON on stdout (dry-run mode)."""
    env = {
        **os.environ,
        "CLAUDE_TOOL_NAME": "Bash",
        "CLAUDE_TOOL_INPUT": '{"command": "ls -la"}',
        "CLAUDE_PERMISSION_RATIONALE": "list files",
        "AUTO_APPROVE_DRY_RUN": "1",
    }
    result = subprocess.run(
        [sys.executable, CLI_PATH],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    data = json.loads(result.stdout.strip())
    assert data["tool"] == "Bash"
    assert data["command"] == "ls -la"
    assert data["rationale"] == "list files"
    assert "timestamp" in data


def test_client_dry_run_exit_code():
    """Dry-run mode exits 0."""
    env = {
        **os.environ,
        "CLAUDE_TOOL_NAME": "Bash",
        "CLAUDE_TOOL_INPUT": "{}",
        "CLAUDE_PERMISSION_RATIONALE": "",
        "AUTO_APPROVE_DRY_RUN": "1",
    }
    result = subprocess.run(
        [sys.executable, CLI_PATH],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_protocol.py -v`
Expected: FAIL (client script doesn't exist)

- [ ] **Step 3: Write client**

```python
#!/usr/bin/env python3
"""auto-approve-cli — PreToolUse hook client. Sends request to daemon, returns decision."""
import json
import os
import socket
import sys
from datetime import datetime, timezone


SOCKET_PATH = "/tmp/claude-auto-approve.sock"
TIMEOUT = 15


def build_request():
    tool_name = os.environ.get("CLAUDE_TOOL_NAME", "Unknown")
    tool_input_str = os.environ.get("CLAUDE_TOOL_INPUT", "{}")
    rationale = os.environ.get("CLAUDE_PERMISSION_RATIONALE", "")

    try:
        tool_input = json.loads(tool_input_str)
    except json.JSONDecodeError:
        tool_input = {"raw": tool_input_str}

    command = tool_input.get("command",
                tool_input.get("file_path",
                    tool_input.get("url", "")))

    return {
        "tool": tool_name,
        "command": str(command),
        "tool_input": tool_input,
        "rationale": rationale,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main():
    request = build_request()

    # Dry-run mode: print JSON and exit 0 (for testing without daemon)
    if os.environ.get("AUTO_APPROVE_DRY_RUN"):
        print(json.dumps(request))
        sys.exit(0)

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect(SOCKET_PATH)
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))

        f = sock.makefile("r", buffering=1)
        response_line = f.readline()
        if not response_line:
            sys.exit(1)

        response = json.loads(response_line)
        decision = response.get("decision", "deny")
        sys.exit(0 if decision == "allow" else 1)

    except (socket.timeout, ConnectionRefusedError, FileNotFoundError, json.JSONDecodeError):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

```bash
chmod +x /home/michael/Documents/repository/agent_harness/hook_premission/auto-approve-cli
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_protocol.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_protocol.py auto-approve-cli
git commit -m "feat: client — JSON protocol, env var reading, dry-run mode"
```

---

### Task 5: Idle Notification

**Files:**
- Create: `idle-notify`

- [ ] **Step 1: Write idle-notify script**

```bash
#!/bin/bash
# idle-notify — Stop hook: show popup when Claude finishes responding
# Fire-and-forget. Always exits 0.

if command -v zenity &>/dev/null && [ -n "$DISPLAY" ]; then
    zenity --info \
        --text="Claude Code — 任务完成，等待输入" \
        --title="Claude Code" \
        --timeout=10 \
        --width=300 \
        2>/dev/null &
fi
exit 0
```

```bash
chmod +x /home/michael/Documents/repository/agent_harness/hook_premission/idle-notify
```

- [ ] **Step 2: Manual smoke test**

```bash
# Run in a terminal with X display:
./idle-notify
# Expected: popup appears for 10 seconds, auto-dismisses. Script exits 0 immediately.
echo $?  # should be 0
```

- [ ] **Step 3: Commit**

```bash
git add idle-notify
git commit -m "feat: idle-notify — Stop hook popup notification"
```

---

### Task 6: Daemon — Socket Server + Lifecycle

**Files:**
- Modify: `auto-approve-daemon.py` (add socket server, CLI)
- Create: `tests/test_daemon.py`

- [ ] **Step 1: Write failing integration test — daemon start/stop**

```python
# tests/test_daemon.py
import json
import os
import signal
import socket
import subprocess
import sys
import time
import pytest


DAEMON_PATH = "/home/michael/Documents/repository/agent_harness/hook_premission/auto-approve-daemon.py"
CONFIG_PATH = "/home/michael/Documents/repository/agent_harness/hook_premission/config.yaml"
SOCKET_PATH = "/tmp/claude-auto-approve.sock"
PID_PATH = "/tmp/claude-auto-approve.pid"


def cleanup():
    """Remove stale socket/pid from previous failed tests."""
    for p in [SOCKET_PATH, PID_PATH]:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


@pytest.fixture(autouse=True)
def clean_before_after():
    cleanup()
    yield
    cleanup()


def send_request(request_dict, timeout=5):
    """Send a JSON request to the daemon and return the response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(SOCKET_PATH)
    sock.sendall((json.dumps(request_dict) + "\n").encode("utf-8"))
    f = sock.makefile("r")
    line = f.readline()
    sock.close()
    return json.loads(line)


def test_daemon_start_responds_and_stops():
    """Daemon starts, accepts a request, returns response, stops cleanly."""
    proc = subprocess.Popen(
        [sys.executable, DAEMON_PATH, "foreground", "--config", CONFIG_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for socket to appear
    for _ in range(50):
        if os.path.exists(SOCKET_PATH):
            break
        time.sleep(0.1)
    assert os.path.exists(SOCKET_PATH), "Daemon did not create socket"

    # Send a request
    response = send_request({
        "tool": "Bash",
        "command": "ls -la",
        "rationale": "test",
        "timestamp": "2026-01-01T00:00:00Z",
    })

    assert response["decision"] in ("allow", "deny")
    assert "timestamp" in response

    # Stop daemon
    proc.terminate()
    proc.wait(timeout=5)
    assert not os.path.exists(SOCKET_PATH), "Socket not cleaned up"


def test_daemon_uses_default_action():
    """When no rules match, daemon uses default_action from config ('allow')."""
    proc = subprocess.Popen(
        [sys.executable, DAEMON_PATH, "foreground", "--config", CONFIG_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(50):
        if os.path.exists(SOCKET_PATH):
            break
        time.sleep(0.1)

    response = send_request({
        "tool": "UnknownTool",
        "command": "something",
        "rationale": "",
        "timestamp": "",
    })
    proc.terminate()
    proc.wait(timeout=5)

    # config.yaml default_action is "allow"
    assert response["decision"] == "allow"
    assert response["reason"] == "default"
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_daemon.py -v`
Expected: FAIL (no `foreground` command or `match_rule` not exposed)

- [ ] **Step 3: Implement daemon socket server + CLI (appends to auto-approve-daemon.py)**

```python
# Append to auto-approve-daemon.py (after match_rule definition, before __main__ block)

DEFAULT_SOCKET_PATH = "/tmp/claude-auto-approve.sock"
DEFAULT_PID_PATH = "/tmp/claude-auto-approve.pid"
DEFAULT_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config(config_path):
    with open(config_path) as f:
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
```

- [ ] **Step 4: Run integration tests**

Run: `pytest tests/test_daemon.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add auto-approve-daemon.py tests/test_daemon.py
git commit -m "feat: daemon — socket server, foreground mode, start/stop/status CLI"
```

---

### Task 7: Config File + Full Integration

**Files:**
- Create: `config.yaml`

- [ ] **Step 1: Write config.yaml (from spec)**

```yaml
# --- Socket & Logging ---
socket_path: "/tmp/claude-auto-approve.sock"
log_path: "~/.claude/auto-approve.log"

# --- Default action when no rule matches ---
default_action: "allow"

# --- Rules: matched in priority order (lowest number = highest priority) ---
rules:
  - priority: 1
    name: "destroy-system"
    pattern:
      tool: "Bash"
      command_contains:
        - "rm -rf /"
        - "mkfs."
        - "dd if="
        - "> /dev/sda"
        - ":(){ :|:& };:"
    action: "deny"

  - priority: 50
    name: "destructive-ops"
    pattern:
      tool: "Bash"
      command_contains:
        - "rm "
        - "rmdir"
        - "delete"
        - "drop "
        - "purge"
        - "truncate"
        - "shred"
    action: "prompt"
    prompt_message: |
      ⚠️  Destructive command detected

      Command: {command}
      Reason:  {rationale}

      Allow this operation?

  - priority: 80
    name: "web-allow"
    pattern:
      tool: "WebFetch"
    action: "allow"

  - priority: 81
    name: "web-search-allow"
    pattern:
      tool: "WebSearch"
    action: "allow"

  - priority: 82
    name: "file-write-allow"
    pattern:
      tool: "Write"
    action: "allow"

  - priority: 83
    name: "file-edit-allow"
    pattern:
      tool: "Edit"
    action: "allow"

  - priority: 84
    name: "bash-allow"
    pattern:
      tool: "Bash"
    action: "allow"
```

- [ ] **Step 2: Full integration test — daemon with real config**

```python
# Append to tests/test_daemon.py
def test_full_flow_with_config():
    """Start daemon, send requests, check rule-matched responses."""
    proc = subprocess.Popen(
        [sys.executable, DAEMON_PATH, "foreground", "--config", CONFIG_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(50):
        if os.path.exists(SOCKET_PATH):
            break
        time.sleep(0.1)

    # WebFetch should be auto-allowed by rule web-allow (priority 80)
    response = send_request({
        "tool": "WebFetch",
        "command": "https://example.com",
        "rationale": "fetch docs",
    })
    assert response["decision"] == "allow"
    assert response["reason"] == "rule:web-allow"

    # "rm -rf /etc" should be denied by destroy-system rule (priority 1)
    response = send_request({
        "tool": "Bash",
        "command": "rm -rf /etc/passwd",
        "rationale": "dangerous",
    })
    assert response["decision"] == "deny"
    assert response["reason"] == "rule:destroy-system"

    proc.terminate()
    proc.wait(timeout=5)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_daemon.py -v`
Expected: 3 PASS

- [ ] **Step 4: Commit**

```bash
git add config.yaml tests/test_daemon.py
git commit -m "feat: config.yaml + full integration test"
```

---

### Task 8: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

````markdown
# Claude Code Auto-Approval System

Auto-approves Claude Code permission prompts via hooks. Dangerous commands trigger GUI confirmation. Session-idle popup reminder.

## Install

```bash
pip install pyyaml          # config parsing
sudo apt install zenity     # GUI popups (Ubuntu/Debian)

chmod +x auto-approve-cli idle-notify auto-approve-daemon.py
```

## Hook Configuration

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /home/michael/Documents/repository/agent_harness/hook_premission/auto-approve-cli"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/home/michael/Documents/repository/agent_harness/hook_premission/idle-notify"
          }
        ]
      }
    ]
  }
}
```

## Usage

```bash
./auto-approve-daemon.py start     # Start daemon (persistent)
./auto-approve-daemon.py status    # Check status + recent log
./auto-approve-daemon.py stop      # Stop daemon
./auto-approve-daemon.py foreground  # Run in foreground (for testing)
```

## Config

Edit `config.yaml` to customize rules.

**Warning:** `default_action: allow` means unknown tools are auto-approved. Set to `deny` for strict mode.

## Logs

`~/.claude/auto-approve.log` — JSON lines, one per decision.

### Log Rotation

```
# /etc/logrotate.d/claude-auto-approve
~/.claude/auto-approve.log {
    weekly
    rotate 4
    missingok
    notifempty
    compress
}
```

## Testing

```bash
pytest tests/ -v
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README — install, usage, logrotate"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests pass (5 rule + 2 protocol + 3 daemon = 10 PASS)

- [ ] **Step 2: Manual daemon foreground test**

```bash
# Terminal 1: Start daemon
./auto-approve-daemon.py foreground

# Terminal 2: Send test requests
echo '{"tool":"Bash","command":"ls","rationale":"test"}' | socat - UNIX-CONNECT:/tmp/claude-auto-approve.sock
# Expected: {"decision": "allow", "reason": "rule:bash-allow", ...}

echo '{"tool":"Bash","command":"rm -rf /tmp","rationale":"test"}' | socat - UNIX-CONNECT:/tmp/claude-auto-approve.sock
# Expected: zenity popup appears
```

- [ ] **Step 3: Manual idle-notify test**

```bash
./idle-notify
# Expected: zenity info popup, auto-dismisses in 10s
```

- [ ] **Step 4: Install hooks to settings.json**

Add the PreToolUse and Stop hook configs from README to `~/.claude/settings.json`.

- [ ] **Step 5: Commit final state**

```bash
git add -A
git commit -m "chore: final verification complete"
```
