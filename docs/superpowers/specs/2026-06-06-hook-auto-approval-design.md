# Hook-Based Auto-Approval System for Claude Code Permissions

**Status:** Draft  
**Date:** 2026-06-06  
**Author:** user (via brainstorming)

## 1. Overview

### 1.1 Problem

Claude Code prompts for user permission before executing Bash commands, writing files, and making web requests. During heavy development sessions, these prompts accumulate and interrupt flow. The user wants to skip routine approvals while retaining guardrails for truly dangerous operations.

### 1.2 Solution

A hook-based system that intercepts all Claude Code tool permission requests, routes them through a local daemon, and auto-approves or denies based on configurable rules. Dangerous commands trigger a GUI popup (zenity) for explicit click confirmation. All decisions are logged for auditability.

### 1.3 Scope

- **In scope:** Bash, Write/Edit, and WebFetch/WebSearch tool permissions; idle-session popup notification
- **Out of scope:** Other tool types, remote approval, shared/collaborative approval
- **Non-goal:** Bypassing any Claude Code safety classifier; this sits at the hook level only

## 2. Architecture

```
Claude Code (hooks)
  │
  ├─ PreToolUse hook ──────────────────┐
  │       exit 0 = allow, non-0 = deny │
  │       ▼                            ▼
  │  auto-approve-cli (thin client)   auto-approve-daemon.py
  │       │  JSON Unix socket  ──────▶  ├─ Rule engine
  │       │                             ├─ Audit log
  │       │                             └─ zenity prompt
  │
  └─ Stop hook (session idle)
         fire-and-forget
         ▼
    idle-notify → zenity --info popup
```

### 2.1 Decision Flow

1. Claude Code fires PreToolUse hook before executing a tool
2. Hook runs `auto-approve-cli`, passes tool metadata via environment variables
3. Client connects to Unix socket (`/tmp/claude-auto-approve.sock`), sends JSON request
4. Daemon receives request, matches against rule set in priority order
5. Match found and action is `allow` → returns `{"decision": "allow"}`
6. Match found and action is `prompt` → spawns `zenity --question`, user clicks Yes/No
7. Match found and action is `deny` → returns `{"decision": "deny"}`
8. No match → uses `default_action` from config
9. Client exits with code 0 (allow) or 1 (deny)
10. Claude Code proceeds or cancels based on exit code

## 3. Components

### 3.1 Client (`auto-approve-cli`)

Thin Python script called by the hook. No long-lived state. Separated from daemon for two reasons: it avoids importing all daemon dependencies into the hook's startup path (keeping hook latency low), and it handles the client-side timeout independently of the daemon's accept loop.

**Input (from hook environment):**
- `CLAUDE_TOOL_NAME` — tool being invoked (Bash, Write, Edit, WebFetch, WebSearch)
- `CLAUDE_TOOL_INPUT` — tool arguments (command text, file path, URL)
- `CLAUDE_PERMISSION_RATIONALE` — why Claude requested this permission

**Input (from stdin, optional):**
- Full hook JSON object if provided by newer CC versions

**Behavior:**
1. Read environment variables and/or stdin
2. Build JSON request: `{"tool": "...", "tool_input": {...}, "rationale": "...", "timestamp": "..."}`
3. Connect to Unix socket at `/tmp/claude-auto-approve.sock`
4. Send JSON request (one line, newline-terminated)
5. Read one line JSON response (timeout: 15 seconds)
6. Parse `decision` field
7. `"allow"` → exit 0; `"deny"` → exit 1; timeout/error → exit 1

### 3.2 Daemon (`auto-approve-daemon.py`)

Long-running Python process. User manages lifecycle manually.

**CLI interface:**
```
./auto-approve-daemon.py start      # Fork to background, create pidfile
./auto-approve-daemon.py stop       # Send SIGTERM, remove pidfile
./auto-approve-daemon.py status     # Print daemon status + recent log tail
```

**Startup sequence:**
1. Parse CLI arguments
2. If `start`: fork, write PID to `/tmp/claude-auto-approve.pid`
3. Load `config.yaml` from same directory as daemon
4. Remove stale socket file if exists
5. Create Unix socket, bind, listen (mode 0600)
6. Enter accept loop

**Accept loop:**
1. `accept()` connection
2. Read one line (max 64KB)
3. Parse JSON
4. Run rule matching (see §4)
5. Write JSON response: `{"decision": "allow"|"deny", "reason": "rule:<name>"|"default"|"prompt:user-denied", "timestamp": "..."}`
6. Close connection
7. Goto 1

**Shutdown:**
- SIGTERM → close socket, unlink socket file, remove pidfile, exit 0
- SIGINT → same as SIGTERM

### 3.3 Configuration (`config.yaml`)

YAML file in the same directory as the daemon. User-editable.

```yaml
# --- Socket & Logging ---
socket_path: "/tmp/claude-auto-approve.sock"
log_path: "~/.claude/auto-approve.log"

# --- Default action when no rule matches ---
default_action: "allow"   # "allow" | "deny"

# --- Rules: matched in priority order (lowest number = highest priority) ---
# First match wins. No match → default_action.

rules:
  # --- Explicit deny list (highest priority) ---
  - priority: 1
    name: "destroy-system"
    pattern:
      tool: "Bash"
      command_contains:
        - "rm -rf /"
        - "mkfs."
        - "dd if="
        - "> /dev/sda"
        - ":(){ :|:& };:"   # fork bomb
    action: "deny"

  # --- Destructive commands: prompt (mid priority) ---
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

  # --- Per-tool blanket rules (lower priority) ---
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

### 3.4 Idle Notification (`idle-notify`)

Separate from the permission system. Triggered by the `Stop` hook — Claude fires it when it finishes generating and waits for user input.

Thin shell/Python script. No socket connection needed — fire-and-forget.

**Behavior:**
1. Invoked by `Stop` hook
2. Calls `zenity --info --text="Claude Code — 任务完成，等待输入" --timeout=10`
3. Timeout 10 seconds: auto-dismisses if user isn't looking
4. Always succeeds (hook exit 0) — failure to notify must not block Claude Code

**Why separate from daemon:**
- Idle notify is fire-and-forget, not request-response
- Does not need rule engine or socket
- Simpler failure mode: if zenity fails, just log and move on

### 3.5 Hook Configuration

In `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/hook_premission/auto-approve-cli"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/hook_premission/idle-notify"
          }
        ]
      }
    ]
  }
}
```

PreToolUse hook: exit 0 = allow, non-zero exit = deny. Empty matcher catches all tools.

Stop hook: fires when Claude finishes responding and waits for user. Fire-and-forget idle popup.

## 4. Rule Matching Algorithm

```
function match(request, rules):
    for rule in rules sorted by priority ASC:
        if all patterns in rule.pattern match request:
            return rule.action
    return config.default_action
```

**Pattern matching (AND semantics):**
- `tool`: exact string match on `CLAUDE_TOOL_NAME`
- `command_contains`: true if ANY substring in list is found in the command text (case-insensitive)
- `path_patterns`: (not in V1) reserved for glob matching on file paths
- `url_patterns`: (not in V1) reserved for glob matching on URLs

If a rule defines multiple pattern fields, ALL must match. If a rule defines one pattern field with a list, ANY list element matching counts.

## 5. Error Handling

| Scenario | Behavior | Rationale |
|----------|----------|-----------|
| Daemon not running | Client connection refused, exit 1 | Deny-default: safe |
| Socket connect timeout (15s) | Exit 1 | Deny-default: safe |
| zenity dialog timeout (30s) | Deny (zenity exits 1 on timeout) | Unattended = no consent |
| Stale socket file on startup | Daemon unlinks old socket before bind | Handle unclean shutdown |
| Daemon crash mid-connection | Client gets EOF, exit 1 | Deny-default: safe |
| Malformed request JSON | Log error, return `{"decision": "deny"}` | Never allow on parse failure |
| No rules match | Use `default_action` | Configurable fallback |
| zenity not installed | Log warning, deny `prompt` actions | Can't prompt without GUI |
| No X display (headless/SSH) | Log warning, deny `prompt` actions | zenity requires `$DISPLAY` |

## 6. Logging & Audit

**Log format** (one JSON line per decision):

```json
{"timestamp": "2026-06-06T15:30:00+08:00", "tool": "Bash", "decision": "ALLOW", "reason": "rule:bash-allow", "command_summary": "ls -la /tmp", "rationale": "check build artifacts"}
```

**Log rotation:** append-only. User responsible for rotation (logrotate snippet provided in README).

## 7. Testing Strategy

### Unit Tests (pytest)
- Rule matching: each rule type, priority ordering, first-match-wins
- JSON request/response serialization
- Default action behavior

### Integration Tests
- Start daemon, send request, verify response
- zenity mocked via environment variable (`ZENITY_MOCK=yes|no`)
- Socket cleanup on shutdown
- Client timeout behavior

### Manual Smoke Tests
- Start daemon in foreground mode (`./auto-approve-daemon.py foreground`)
- Send test request via `socat` or `nc -U`
- Verify GUI popup for prompt rules

## 8. Open Questions / Future

- **V2:** glob-based `path_patterns` and `url_patterns`
- **V2:** per-directory trust (auto-allow in project dirs, prompt outside)
- **V2:** TTL-based trust (allow for 5 minutes after first confirm)
- **Risks:** User must understand that `default_action: allow` combined with broad rules = effectively no permission checks. This is intentional but should be called out in README.

## 9. Security Considerations

- Unix socket is mode 0600 — only the owning user can connect
- Incoming connections inherit the connecting process's UID via `SO_PEERCRED` (Linux) — daemon can verify same-user
- Default deny on any error or timeout ensures fail-safe behavior
- Audit log provides post-hoc visibility into all approved actions
- GUI prompt for destructive commands preserves a human-in-the-loop step for the most dangerous operations
