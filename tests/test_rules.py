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
