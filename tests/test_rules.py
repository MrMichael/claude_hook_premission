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
