# Claude Code 自动审批系统

通过 Hook 自动批准 Claude Code 权限提示。危险命令弹窗确认，会话空闲弹窗提醒。

## 安装

```bash
pip install pyyaml              # 配置解析
sudo apt install zenity         # GUI弹窗 (Ubuntu/Debian)
sudo apt install libnotify-bin  # 桌面通知 (可选)

chmod +x auto-approve-cli idle-notify auto_approve_daemon.py
```

## Hook 配置

添加到 `~/.claude/settings.json`（省略 matcher = 匹配所有工具）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /home/michael/Documents/repository/agent_harness/hook_premission/auto-approve-cli"
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "rtk hook claude"
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

## 使用

```bash
./auto_approve_daemon.py start       # 后台启动（持久运行）
./auto_approve_daemon.py status      # 查看状态 + 最近审批记录
./auto_approve_daemon.py stop        # 停止
./auto_approve_daemon.py foreground  # 前台运行（调试用）
```

## 规则配置

编辑 `config.yaml`。规则按 priority 升序匹配（数字越小越优先），首次命中即返回。

```yaml
default_action: "allow"       # 无规则匹配时的默认操作 (allow/deny)
notify_mode: "silent"         # 通知模式: silent/verbose/never

rules:
  - priority: 1               # 硬拒绝 —— 最高优先级
    name: "destroy-system"
    pattern:
      tool: "Bash"
      command_contains:
        - "mkfs."
        - "dd if="
        - "> /dev/sda"
    action: "deny"

  - priority: 50              # 弹窗确认 —— 中等优先级
    name: "destructive-ops"
    pattern:
      tool: "Bash"
      command_contains:
        - "rm "
        - "rmdir"
        - "delete"
        - "purge"
    action: "prompt"
    prompt_message: |
      ⚠️  危险操作

      命令: {command}
      原因: {rationale}

      允许执行？

  - priority: 80              # 自动放行 —— 低优先级
    name: "web-allow"
    pattern:
      tool: "WebFetch"
    action: "allow"
```

### action 类型

| action | 效果 |
|--------|------|
| `allow` | 自动放行 |
| `deny` | 直接拒绝 |
| `prompt` | 弹 zenity 窗口，点击确认 |

### pattern 字段

| 字段 | 匹配方式 |
|------|---------|
| `tool` | 工具名精确匹配（Bash/Write/Edit/WebFetch/WebSearch） |
| `command_contains` | 命令包含任一子串（大小写不敏感） |

多个 pattern 字段之间为 AND 关系。同一字段内的列表为 OR（任一命中即匹配）。

**注意：** `default_action: allow` 意味着未知工具一律放行。改为 `deny` 启用严格模式。

## 通知模式

| 模式 | 自动放行 | 弹窗确认 | 硬拒绝 | 错误 |
|------|---------|---------|--------|------|
| `silent`（推荐） | 静默 | notify-send | notify-send | notify-send |
| `verbose` | notify-send | notify-send | notify-send | notify-send |
| `never` | 静默 | 静默 | 静默 | 静默 |

通知超时 1 秒。

## 日志

`~/.claude/auto-approve.log` —— 每行 JSON，格式：

```json
{"timestamp": "2026-06-06T14:09:38+08:00", "tool": "Bash", "decision": "ALLOW", "reason": "rule:bash-allow", "command_summary": "echo test", "rationale": "测试自动放行"}
```

### 实时监控

```bash
tail -f ~/.claude/auto-approve.log
```

### 日志轮转

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

## 空闲提醒

Claude Code 响应完毕后自动弹窗 "任务完成，等待输入"，10 秒后消失。

不需要时从 `settings.json` 删除 `Stop` hook 块即可。

## 测试

```bash
pytest tests/ -v    # 11 tests
```

## 文件

| 文件 | 作用 |
|------|------|
| `auto-approve-cli` | PreToolUse hook 客户端 |
| `auto_approve_daemon.py` | 后台守护进程（socket 服务器 + 规则引擎） |
| `idle-notify` | Stop hook 空闲提醒 |
| `config.yaml` | 用户规则配置 |
| `tests/` | pytest 测试套件 |
