# Claude Code Auto-Approval System

Auto-approves Claude Code permission prompts via hooks. Dangerous commands trigger GUI confirmation. Session-idle popup reminder.

## Install

```bash
pip install pyyaml          # config parsing
sudo apt install zenity     # GUI popups (Ubuntu/Debian)

chmod +x auto-approve-cli idle-notify auto_approve_daemon.py
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
python3 auto_approve_daemon.py start     # Start daemon (persistent)
python3 auto_approve_daemon.py status    # Check status + recent log
python3 auto_approve_daemon.py stop      # Stop daemon
python3 auto_approve_daemon.py foreground  # Run in foreground (for testing)
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
