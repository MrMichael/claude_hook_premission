import json
import os
import signal
import socket
import subprocess
import sys
import time
import pytest


DAEMON_PATH = "/home/michael/Documents/repository/agent_harness/hook_premission/auto_approve_daemon.py"
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

    # config.yaml default_action is "allow" — so unknown tools get allowed
    assert response["decision"] == "allow"
    assert response["reason"] == "default"
