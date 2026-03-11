#!/usr/bin/env python3
"""Auto-generate compliance hooks from promoted correction groups.

Takes a correction theme string, classifies hookability, and optionally
generates a warn-only bash hook script registered in settings.json.

Usage:
    hook_generator.py <theme> [--project-root <path>]
    hook_generator.py --test
"""
import json, os, re, sys, tempfile

COMPLIANCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "compliance")
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "settings.json")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

TOOL_KEYWORDS = {
    "bash", "edit", "write", "read", "agent", "skill", "task",
    "grep", "glob", "notebook",
}

TOOL_GATE_PATTERNS = [
    (re.compile(r"never\s+use\s+(\S+)", re.IGNORECASE), "ban"),
    (re.compile(r"don'?t\s+use\s+(\S+)", re.IGNORECASE), "ban"),
    (re.compile(r"do\s+not\s+use\s+(\S+)", re.IGNORECASE), "ban"),
    (re.compile(r"always\s+use\s+(\S+)", re.IGNORECASE), "require"),
    (re.compile(r"use\s+/(\S+)\s+for", re.IGNORECASE), "require_skill"),
    (re.compile(r"don'?t\s+(\S+)\s+without\s+(\S+)", re.IGNORECASE), "conditional"),
    (re.compile(r"never\s+(\S+)\s+without\s+(\S+)", re.IGNORECASE), "conditional"),
]

CLI_DANGER_PATTERNS = [
    re.compile(r"rm\s+-rf", re.IGNORECASE),
    re.compile(r"git\s+push\s+--force", re.IGNORECASE),
    re.compile(r"git\s+reset\s+--hard", re.IGNORECASE),
    re.compile(r"git\s+add\s+-[aA]", re.IGNORECASE),
    re.compile(r"git\s+clean\s+-f", re.IGNORECASE),
    re.compile(r"drop\s+table", re.IGNORECASE),
    re.compile(r"truncate\s+table", re.IGNORECASE),
]

RESPONSE_PATTERNS = [
    re.compile(r"don'?t\s+narrate", re.IGNORECASE),
    re.compile(r"stop\s+talk", re.IGNORECASE),
    re.compile(r"post.?completion\s+narrat", re.IGNORECASE),
    re.compile(r"don'?t\s+(explain|describe|summarize)\s+(what|before|after)", re.IGNORECASE),
]


def sanitize_name(theme):
    name = theme.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = name.strip("-")
    return name[:60]


def classify_hookability(theme):
    theme_lower = theme.lower()

    for pattern in RESPONSE_PATTERNS:
        if pattern.search(theme):
            return {"hookable": True, "hook_type": "Stop", "reason": "response-structure pattern"}

    for pattern in CLI_DANGER_PATTERNS:
        if pattern.search(theme):
            cli_match = pattern.pattern
            return {
                "hookable": True,
                "hook_type": "PreToolUse",
                "matcher": "Bash",
                "detect_pattern": pattern.pattern,
                "reason": f"CLI danger pattern: {cli_match}",
            }

    for regex, gate_type in TOOL_GATE_PATTERNS:
        m = regex.search(theme)
        if m:
            mentioned_tool = m.group(1).lower().rstrip(".,;:!")
            if mentioned_tool in TOOL_KEYWORDS:
                return {
                    "hookable": True,
                    "hook_type": "PreToolUse",
                    "matcher": mentioned_tool.capitalize(),
                    "gate_type": gate_type,
                    "reason": f"tool-gating: {gate_type} {mentioned_tool}",
                }
            if gate_type == "require_skill":
                skill_name = m.group(1)
                return {
                    "hookable": True,
                    "hook_type": "PreToolUse",
                    "matcher": "Skill",
                    "gate_type": "require_skill",
                    "skill_name": skill_name,
                    "reason": f"skill routing: use /{skill_name}",
                }

    words = set(re.findall(r"\w+", theme_lower))
    tool_mentions = words & TOOL_KEYWORDS
    if tool_mentions:
        tool = sorted(tool_mentions)[0]
        return {
            "hookable": True,
            "hook_type": "PreToolUse",
            "matcher": tool.capitalize(),
            "reason": f"tool mention: {tool}",
        }

    return {"hookable": False, "reason": "not structurally enforceable (style/tone/judgment)"}


def _generate_bash_pretooluse(theme, classification):
    matcher = classification.get("matcher", "Bash")
    detect_pattern = classification.get("detect_pattern")

    if detect_pattern:
        condition_check = _bash_regex_check(detect_pattern)
    elif matcher == "Bash":
        key_words = re.findall(r"\b[a-z][\w-]+\b", theme.lower())
        dangerous = [w for w in key_words if len(w) > 2 and w not in ("use", "never", "don", "without", "always", "the", "for", "and", "with")]
        if dangerous:
            pattern_str = "|".join(dangerous[:3])
            condition_check = f'  if echo "$COMMAND" | grep -qEi "{pattern_str}"; then'
        else:
            return None
    else:
        return None

    return f"""#!/bin/bash
# Auto-generated compliance hook. Source: correction_groups theme "{theme[:200]}". Mode: warn-only.
# Hook type: PreToolUse, matcher: {matcher}

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ti = d.get('tool_input', {{}})
print(ti.get('command', ti.get('content', ti.get('file_path', ''))))
" 2>/dev/null)

{condition_check}
    echo "COMPLIANCE WARNING: This action may violate preference: {theme[:200]}" >&2
    echo "Source: auto-generated from correction_groups. Mode: warn-only." >&2
  fi

exit 0
"""


def _bash_regex_check(pattern):
    safe_pattern = pattern.replace("\\s+", "[[:space:]]+").replace("\\s", "[[:space:]]")
    return f'  if echo "$COMMAND" | grep -qEi "{safe_pattern}"; then'


def _generate_bash_stop(theme):
    return f"""#!/bin/bash
# Auto-generated compliance hook. Source: correction_groups theme "{theme[:200]}". Mode: warn-only.
# Hook type: Stop (response-structure)
# NOTE: Stop hooks cannot prevent output already sent. This logs a warning for future awareness.

INPUT=$(cat)

echo "COMPLIANCE WARNING: Response may violate preference: {theme[:200]}" >&2
echo "Source: auto-generated from correction_groups. Mode: warn-only." >&2

exit 0
"""


def generate_hook(theme, project_root=None):
    if project_root:
        compliance_dir = os.path.join(project_root, "hooks", "compliance")
        settings_path = os.path.join(project_root, "settings.json")
    else:
        compliance_dir = COMPLIANCE_DIR
        settings_path = SETTINGS_PATH

    classification = classify_hookability(theme)
    if not classification["hookable"]:
        _log_hookability(theme, classification, project_root)
        return None

    hook_name = f"compliance-{sanitize_name(theme)}.sh"
    hook_path = os.path.join(compliance_dir, hook_name)

    if os.path.exists(hook_path):
        return {"path": hook_path, "skipped": True, "reason": "hook already exists"}

    os.makedirs(compliance_dir, exist_ok=True)

    hook_type = classification["hook_type"]
    if hook_type == "PreToolUse":
        script = _generate_bash_pretooluse(theme, classification)
    elif hook_type == "Stop":
        script = _generate_bash_stop(theme)
    else:
        script = _generate_bash_pretooluse(theme, classification)

    if script is None:
        matcher = classification.get("matcher", "unknown")
        not_hookable = {"hookable": False, "reason": f"cannot derive non-vacuous condition for matcher: {matcher}"}
        _log_hookability(theme, not_hookable, project_root)
        return None

    with open(hook_path, "w") as f:
        f.write(script)
    os.chmod(hook_path, 0o755)

    _update_settings(settings_path, hook_path, hook_type, classification)

    _log_generation(theme, hook_path, hook_type, classification, project_root)

    return {
        "path": hook_path,
        "hook_type": hook_type,
        "classification": classification,
        "skipped": False,
    }


def _resolve_hook_path(command):
    """Expand ~ and resolve a hook command path to an absolute filesystem path."""
    return os.path.expanduser(command)


def _update_settings(settings_path, hook_path, hook_type, classification):
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    hook_rel = hook_path.replace(os.path.expanduser("~"), "~")
    hook_command = hook_rel

    # Task 3: Verify hook file exists before registering
    resolved_path = _resolve_hook_path(hook_command)
    if not os.path.exists(resolved_path):
        return

    perm_entry = f"Bash({hook_rel}*)"
    permissions = settings.setdefault("permissions", {})
    allow_list = permissions.setdefault("allow", [])
    if perm_entry not in allow_list:
        allow_list.append(perm_entry)

    hooks = settings.setdefault("hooks", {})
    event_matchers = hooks.setdefault(hook_type, [])

    matcher_name = classification.get("matcher", "")
    hook_entry = {"type": "command", "command": hook_command, "timeout": 5}

    if hook_type == "Stop":
        new_matcher = {"hooks": [hook_entry]}
        already = any(
            any(h.get("command") == hook_command for h in m.get("hooks", []))
            for m in event_matchers
        )
        if not already:
            event_matchers.append(new_matcher)
    else:
        found_matcher = None
        for m in event_matchers:
            if m.get("matcher") == matcher_name:
                found_matcher = m
                break

        if found_matcher:
            existing_commands = [h.get("command") for h in found_matcher.get("hooks", [])]
            if hook_command not in existing_commands:
                found_matcher["hooks"].append(hook_entry)
        else:
            new_matcher = {"matcher": matcher_name, "hooks": [hook_entry]}
            event_matchers.append(new_matcher)

    # Task 4: Reconcile — prune dead hook paths for this matcher
    for m in event_matchers:
        if m.get("matcher", "") == matcher_name or (hook_type == "Stop" and "matcher" not in m):
            live_hooks = [h for h in m.get("hooks", []) if os.path.exists(_resolve_hook_path(h.get("command", "")))]
            m["hooks"] = live_hooks
    # Remove matcher entries with no remaining hooks
    hooks[hook_type] = [m for m in event_matchers if m.get("hooks")]

    tmp_path = settings_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.rename(tmp_path, settings_path)


def _log_hookability(theme, classification, project_root=None):
    root = project_root or PROJECT_ROOT
    try:
        sys.path.insert(0, root)
        from hooks.lib.om_write import om_write
        om_write(
            content=f"Hookability eval: NOT hookable. Theme: {theme[:200]}. Reason: {classification['reason']}",
            tags=["behavioral-pref"],
            user_id="proj:dotclaude",
        )
    except Exception:
        pass


def _log_generation(theme, hook_path, hook_type, classification, project_root=None):
    root = project_root or PROJECT_ROOT
    try:
        sys.path.insert(0, root)
        from hooks.lib.om_write import om_write
        om_write(
            content=f"Compliance hook generated. Theme: {theme[:200]}. Path: {hook_path}. Type: {hook_type}. Mode: warn-only.",
            tags=["behavioral-pref"],
            user_id="proj:dotclaude",
        )
    except Exception:
        pass


def _run_tests():
    import tempfile, shutil

    test_dir = tempfile.mkdtemp(prefix="hook_gen_test_")
    compliance_test = os.path.join(test_dir, "hooks", "compliance")
    os.makedirs(compliance_test)
    settings_test = os.path.join(test_dir, "settings.json")
    with open(settings_test, "w") as f:
        json.dump({"permissions": {"allow": []}, "hooks": {"PreToolUse": [], "Stop": []}}, f)

    passed = 0
    failed = 0

    # Test 1: hookable CLI danger pattern
    result = classify_hookability("never use rm -rf without confirmation")
    assert result["hookable"], f"Test 1 failed: {result}"
    assert result["hook_type"] == "PreToolUse", f"Test 1 hook_type: {result}"
    passed += 1
    print("PASS: Test 1 - CLI danger pattern classified as hookable PreToolUse")

    # Test 2: non-hookable tone/judgment
    result = classify_hookability("own positions, retract later if wrong")
    assert not result["hookable"], f"Test 2 failed: {result}"
    passed += 1
    print("PASS: Test 2 - Tone/judgment classified as not hookable")

    # Test 3: response-structure pattern
    result = classify_hookability("don't narrate what you're about to do")
    assert result["hookable"], f"Test 3 failed: {result}"
    assert result["hook_type"] == "Stop", f"Test 3 hook_type: {result}"
    passed += 1
    print("PASS: Test 3 - Response-structure classified as Stop hook")

    # Test 4: tool-gating pattern
    result = classify_hookability("never use Agent tool for simple tasks")
    assert result["hookable"], f"Test 4 failed: {result}"
    assert result["hook_type"] == "PreToolUse", f"Test 4 hook_type: {result}"
    assert result["matcher"] == "Agent", f"Test 4 matcher: {result}"
    passed += 1
    print("PASS: Test 4 - Tool-gating classified correctly")

    # Test 5: skill routing
    result = classify_hookability("use /ship for all new work")
    assert result["hookable"], f"Test 5 failed: {result}"
    assert result["gate_type"] == "require_skill", f"Test 5 gate_type: {result}"
    passed += 1
    print("PASS: Test 5 - Skill routing classified correctly")

    # Test 6: generate hook file for rm -rf
    result = generate_hook("never use rm -rf without confirmation", project_root=test_dir)
    assert result is not None, "Test 6 failed: result is None"
    assert not result["skipped"], f"Test 6 skipped: {result}"
    assert os.path.isfile(result["path"]), f"Test 6 file missing: {result['path']}"
    with open(result["path"]) as f:
        content = f.read()
    assert "exit 0" in content, "Test 6: hook must exit 0"
    assert "exit 2" not in content, "Test 6: hook must NOT exit 2"
    assert "warn-only" in content, "Test 6: hook must be warn-only"
    passed += 1
    print(f"PASS: Test 6 - Hook file generated at {result['path']}")

    # Test 7: settings.json updated
    with open(settings_test) as f:
        settings = json.load(f)
    allow = settings["permissions"]["allow"]
    assert any("compliance" in e for e in allow), f"Test 7 failed: {allow}"
    pre_tool = settings["hooks"]["PreToolUse"]
    assert len(pre_tool) > 0, f"Test 7 no PreToolUse entries"
    passed += 1
    print("PASS: Test 7 - settings.json updated with hook entry")

    # Test 8: idempotency
    result2 = generate_hook("never use rm -rf without confirmation", project_root=test_dir)
    assert result2 is not None and result2["skipped"], f"Test 8 failed: {result2}"
    passed += 1
    print("PASS: Test 8 - Idempotent: second generation skipped")

    # Test 9: settings.json is valid JSON
    with open(settings_test) as f:
        json.load(f)
    passed += 1
    print("PASS: Test 9 - settings.json remains valid JSON")

    # Test 10: no generated hook exits 2
    for fname in os.listdir(compliance_test):
        fpath = os.path.join(compliance_test, fname)
        if fname.endswith(".sh"):
            with open(fpath) as f:
                content = f.read()
            assert "exit 2" not in content, f"Test 10: {fname} contains exit 2"
    passed += 1
    print("PASS: Test 10 - No generated hooks exit 2 (all warn-only)")

    # Test 11: sanitize_name
    assert sanitize_name("Never use rm -rf!! OMG") == "never-use-rm-rf-omg"
    passed += 1
    print("PASS: Test 11 - Name sanitization")

    # Test 12: Stop hook generation
    result = generate_hook("stop talking after completing tasks", project_root=test_dir)
    assert result is not None and not result["skipped"], f"Test 12 failed: {result}"
    assert result["hook_type"] == "Stop", f"Test 12 type: {result}"
    with open(result["path"]) as f:
        content = f.read()
    assert "exit 0" in content and "exit 2" not in content
    passed += 1
    print("PASS: Test 12 - Stop hook generated correctly")

    # Test 13: Skill matcher with no detect_pattern returns None (not vacuous)
    result = generate_hook("use /ship for all new work", project_root=test_dir)
    assert result is None, f"Test 13 failed: expected None for skill matcher without detect_pattern, got {result}"
    passed += 1
    print("PASS: Test 13 - Skill matcher with no detect_pattern returns None")

    # Test 14: Non-hookable result shape is consistent (dict with hookable: False from classify)
    result = classify_hookability("own positions, retract later if wrong")
    assert isinstance(result, dict), f"Test 14 failed: not a dict"
    assert result.get("hookable") is False, f"Test 14 failed: hookable not False"
    assert "reason" in result, f"Test 14 failed: missing reason"
    passed += 1
    print("PASS: Test 14 - Non-hookable result has consistent shape")

    # Test 15: _update_settings() does not register hooks for non-existent files
    settings_test2 = os.path.join(test_dir, "settings2.json")
    with open(settings_test2, "w") as f:
        json.dump({"permissions": {"allow": []}, "hooks": {"PreToolUse": []}}, f)
    fake_hook_path = os.path.join(test_dir, "hooks", "compliance", "does-not-exist.sh")
    _update_settings(settings_test2, fake_hook_path, "PreToolUse", {"matcher": "Bash"})
    with open(settings_test2) as f:
        s = json.load(f)
    # Should not have registered the non-existent hook
    pre_tool_entries = s["hooks"]["PreToolUse"]
    for m in pre_tool_entries:
        for h in m.get("hooks", []):
            assert h.get("command") != fake_hook_path.replace(os.path.expanduser("~"), "~"), \
                f"Test 15 failed: registered non-existent hook"
    passed += 1
    print("PASS: Test 15 - _update_settings() skips non-existent hook files")

    # Test 16: No generated hook contains 'if true; then'
    compliance_files = [f for f in os.listdir(compliance_test) if f.endswith(".sh")] if os.path.exists(compliance_test) else []
    for fname in compliance_files:
        fpath = os.path.join(compliance_test, fname)
        with open(fpath) as f:
            content = f.read()
        assert "if true; then" not in content, f"Test 16 failed: {fname} contains 'if true; then'"
    passed += 1
    print("PASS: Test 16 - No generated hooks contain vacuous 'if true; then'")

    shutil.rmtree(test_dir)
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        success = _run_tests()
        sys.exit(0 if success else 1)

    if len(sys.argv) < 2:
        print("Usage: hook_generator.py <theme> [--project-root <path>]", file=sys.stderr)
        sys.exit(1)

    theme = sys.argv[1]
    project_root = None
    if "--project-root" in sys.argv:
        idx = sys.argv.index("--project-root")
        if idx + 1 < len(sys.argv):
            project_root = sys.argv[idx + 1]

    result = generate_hook(theme, project_root=project_root)
    if result is None:
        print(json.dumps({"hookable": False}))
    else:
        print(json.dumps(result, default=str))
