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
