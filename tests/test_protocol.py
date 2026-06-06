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
