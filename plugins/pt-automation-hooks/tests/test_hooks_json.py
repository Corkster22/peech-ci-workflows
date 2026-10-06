"""hooks/hooks.json - every hook the plugin serves, on the event it fires on.

PPA-1586. The set is every hook wired in two or more repositories'
.claude/settings.json at origin/main on 23-SEP-2026, plus deny_in_scope_spawn.py
by name. A hook file in hooks/ that nothing registers never runs, and a
registration naming a file that is not there fails on every firing, so both
directions are asserted. PPA-1597 added label_spawned_ticket.py, and PPA-1626
deny_push_without_checklist.py, and PPA-1662 refresh_ci_workflows.py. PPA-1757
added log_turn_worklog.py, the one Stop hook that fails open. PPA-1774 added
post_pending_turns.py, the SessionStart hook that posts earlier sessions' turns.
PPA-1872 added delete_merged_branches.py, the SessionStart hook that deletes merged branches.
"""

import json
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
CONFIG = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())

EXPECTED = {
    "SessionStart": [(None, "refresh_ci_workflows.py"),
                     (None, "post_pending_turns.py"),
                     (None, "delete_merged_branches.py")],
    "UserPromptSubmit": [(None, "transition_on_prompt.py")],
    "PreToolUse": [("mcp__atlassian__createJiraIssue", "deny_in_scope_spawn.py"),
                   ("Bash", "deny_push_without_checklist.py")],
    "PostToolUse": [("mcp__atlassian__createJiraIssue", "label_spawned_ticket.py")],
    "Stop": [(None, "check_claudemd.py"), (None, "grade_definition_of_done.py"),
             (None, "log_turn_worklog.py")],
    "SessionEnd": [(None, "arm_auto_merge.py")],
}


def registered():
    return {event: [(block.get("matcher"), name)
                    for block in blocks for hook in block["hooks"]
                    for name in re.findall(r"hooks/(\w+\.py)", hook["command"])]
            for event, blocks in CONFIG["hooks"].items()}


def test_every_shared_hook_is_registered_on_its_event():
    assert registered() == EXPECTED


def test_every_registered_file_ships_and_every_shipped_hook_is_registered():
    named = {name for pairs in registered().values() for _, name in pairs}
    shipped = {p.name for p in (PLUGIN / "hooks").glob("*.py")}
    assert named == shipped


def test_every_command_resolves_the_plugin_root_the_same_way():
    """One resolution idiom, so a fix to it is one fix."""
    for blocks in CONFIG["hooks"].values():
        for block in blocks:
            for hook in block["hooks"]:
                assert hook["command"].startswith('r="${CLAUDE_PLUGIN_ROOT:-}"; ')


def _stop_hooks():
    return {name: hook for block in CONFIG["hooks"]["Stop"] for hook in block["hooks"]
            for name in re.findall(r"hooks/(\w+\.py)", hook["command"])}


def test_the_worklog_hook_fails_open_with_a_timeout():
    """PPA-1757. Exit 2 blocks the stop, so a missing file must exit 0."""
    hook = _stop_hooks()["log_turn_worklog.py"]
    assert '[ ! -f "$h" ] && exit 0' in hook["command"]
    assert "exit 2" not in hook["command"]
    assert hook["timeout"] > 0


def test_the_existing_stop_hooks_still_fail_closed():
    hooks = _stop_hooks()
    for name in ("check_claudemd.py", "grade_definition_of_done.py"):
        assert "exit 2" in hooks[name]["command"]


def _session_start_hooks():
    return {name: hook for block in CONFIG["hooks"]["SessionStart"]
            for hook in block["hooks"]
            for name in re.findall(r"hooks/(\w+\.py)", hook["command"])}


def test_the_session_start_worklog_hook_fails_open_with_a_timeout():
    """PPA-1774. A missing file must not stop a session starting, and the
    timeout must exceed log_turn_worklog.DEADLINE (25 s), which ends the HTTP."""
    hook = _session_start_hooks()["post_pending_turns.py"]
    assert '[ ! -f "$h" ] && exit 0' in hook["command"]
    assert "exit 2" not in hook["command"]
    assert 25 < hook["timeout"]


def test_the_branch_cleanup_hook_fails_open_with_a_timeout_above_its_deadline():
    """PPA-1872. A missing file must not stop a session starting, and the
    timeout must exceed delete_merged_branches.DEADLINE, which ends its GitHub calls."""
    import sys
    sys.path.insert(0, str(PLUGIN / "hooks"))
    import delete_merged_branches
    hook = _session_start_hooks()["delete_merged_branches.py"]
    assert '[ ! -f "$h" ] && exit 0' in hook["command"]
    assert "exit 2" not in hook["command"]
    assert delete_merged_branches.DEADLINE < hook["timeout"]
