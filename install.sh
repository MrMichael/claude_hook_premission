#!/usr/bin/env bash
set -euo pipefail

# Claude Code 自动审批系统 —— 一键安装（Ubuntu）
# 用法: ./install.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo -e "${GREEN}┌─────────────────────────────────────┐${NC}"
echo -e "${GREEN}│  Claude Code Auto-Approval 安装程序  │${NC}"
echo -e "${GREEN}└─────────────────────────────────────┘${NC}"
echo ""

# ─── 1. 系统依赖 ───
echo -e "${YELLOW}[1/5] 安装系统依赖...${NC}"
sudo apt-get update -qq
sudo apt-get install -y -qq zenity libnotify-bin python3 python3-pip
echo -e "${GREEN}  ✓ zenity, libnotify-bin, python3${NC}"

# ─── 2. Python 依赖 ───
echo -e "${YELLOW}[2/5] 安装 Python 依赖...${NC}"
pip3 install --quiet pyyaml
echo -e "${GREEN}  ✓ pyyaml${NC}"

# ─── 3. 可执行权限 ───
echo -e "${YELLOW}[3/5] 设置可执行权限...${NC}"
chmod +x "$SCRIPT_DIR/auto-approve-cli" \
         "$SCRIPT_DIR/idle-notify" \
         "$SCRIPT_DIR/auto_approve_daemon.py" \
         "$SCRIPT_DIR/install.sh"
echo -e "${GREEN}  ✓ 脚本已添加执行权限${NC}"

# ─── 4. 安装 Hook 配置 ───
echo -e "${YELLOW}[4/5] 配置 Hook...${NC}"

if [ ! -f "$SETTINGS_FILE" ]; then
    echo -e "${RED}  ✗ 未找到 $SETTINGS_FILE${NC}"
    echo "  请手动将以下内容添加到 settings.json:"
    echo ""
    echo '  "hooks": {'
    echo '    "PreToolUse": ['
    echo '      {'
    echo '        "hooks": [{'
    echo '          "type": "command",'
    echo "          \"command\": \"python3 $SCRIPT_DIR/auto-approve-cli\""
    echo '        }]'
    echo '      }'
    echo '    ],'
    echo '    "Stop": ['
    echo '      {'
    echo '        "hooks": [{'
    echo '          "type": "command",'
    echo "          \"command\": \"$SCRIPT_DIR/idle-notify\""
    echo '        }]'
    echo '      }'
    echo '    ]'
    echo '  }'
    echo ""
else
    if grep -q "auto-approve-cli" "$SETTINGS_FILE" 2>/dev/null; then
        echo -e "${GREEN}  ✓ Hook 已配置 (settings.json 中已有 auto-approve-cli)${NC}"
    else
        echo -e "${YELLOW}  ⚠ Hook 未配置。${NC}"
        echo "  请手动编辑 $SETTINGS_FILE，在 hooks 中添加:"
        echo ""
        echo '  "PreToolUse": ['
        echo '    {'
        echo '      "hooks": [{'
        echo '        "type": "command",'
        echo "        \"command\": \"python3 $SCRIPT_DIR/auto-approve-cli\""
        echo '      }]'
        echo '    }'
        echo '  ],'
        echo '  "Stop": ['
        echo '    {'
        echo '      "hooks": [{'
        echo '        "type": "command",'
        echo "        \"command\": \"$SCRIPT_DIR/idle-notify\""
        echo '      }]'
        echo '    }'
        echo '  ]'
        echo ""
    fi
fi

# ─── 5. 启动守护进程 ───
echo -e "${YELLOW}[5/5] 启动守护进程...${NC}"

"$SCRIPT_DIR/auto_approve_daemon.py" stop 2>/dev/null || true
sleep 0.3
"$SCRIPT_DIR/auto_approve_daemon.py" start
sleep 0.3

if "$SCRIPT_DIR/auto_approve_daemon.py" status 2>/dev/null | grep -q "RUNNING"; then
    echo -e "${GREEN}  ✓ 守护进程已启动${NC}"
else
    echo -e "${RED}  ✗ 守护进程启动失败，请检查日志${NC}"
fi

# ─── 完成 ───
echo ""
echo -e "${GREEN}┌─────────────────────────────────────┐${NC}"
echo -e "${GREEN}│            安装完成！                │${NC}"
echo -e "${GREEN}└─────────────────────────────────────┘${NC}"
echo ""
echo "  守护进程: $SCRIPT_DIR/auto_approve_daemon.py status"
echo "  实时日志: tail -f ~/.claude/auto-approve.log"
echo "  配置文件: $SCRIPT_DIR/config.yaml"
echo ""
