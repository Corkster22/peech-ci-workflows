"""deny_in_scope_spawn.py - the PreToolUse spawn-control hook (PPA-1566).

Each case drives main() end to end: a PreToolUse payload on stdin, a
transcript on disk carrying the dispatch line, and fetch_ticket() stubbed so
no case reaches Jira. The decision is read off stdout the way Claude Code
reads it, and every assertion names the decision it expected.
"""

import importlib.util
import io
import json
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "deny_in_scope_spawn.py"


def _load():
    spec = importlib.util.spec_from_file_location("deny_in_scope_spawn", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()

BOUNDARY = """Change the thing.

<!-- pt-files:start -->
edit: libs/shared/peech_shared/drive_folders.py (new)
edit: config/app.yml
cite: docs/spikes/PPA-996-findings.md
<!-- pt-files:end -->
"""

#: The line PPA-1599 requires, naming a consequence, so the fix-here cases
#: below reach the question they test.
BREAKS = "What breaks if not fixed: the weekly report double-counts one row."

#: The key the stubbed Jira read returns for a session's first create.
FIRST_KEY = "PPA-2001"

TICKET = {"description": BOUNDARY,
          "customfield_10767": "* [machine] config/app.yml carries one "
                               "template id per category."}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Drive main() and return (decision, stdout payload, log records)."""
    log = tmp_path / "hook.log"
    monkeypatch.setattr(hook, "LOG", log)
    monkeypatch.setattr(hook, "fetch_ticket", lambda key: TICKET)
    monkeypatch.setattr(hook, "created_key", lambda summary, since: FIRST_KEY)
    transcript = tmp_path / "t.jsonl"

    def go(summary, *, dispatch="PPA-997", project="PPA", description="",
           tool=hook.TOOL, fetch=None, breaks=BREAKS, session="test-no-cache"):
        if breaks is not None:
            description = f"{description}\n\n{breaks}"
        prompts = [dispatch] if isinstance(dispatch, str) else dispatch
        entries = [{"type": "user", "message": {"role": "user", "content": (
            f'<pasted_content id="x">\n{text}\n</pasted_content>')}}
            for text in prompts]
        transcript.write_text("\n".join(json.dumps(e) for e in entries))
        if fetch:
            monkeypatch.setattr(hook, "fetch_ticket", fetch)
        payload = {"session_id": session, "transcript_path":
                   str(transcript), "hook_event_name": "PreToolUse",
                   "tool_name": tool, "tool_input": {
                       "projectKey": project, "summary": summary,
                       "description": description}}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        out = io.StringIO()
        monkeypatch.setattr("sys.stdout", out)
        assert hook.main() == 0
        printed = json.loads(out.getvalue()) if out.getvalue() else None
        records = [json.loads(line) for line in log.read_text().splitlines()]
        return decision_of(printed), printed, records

    return go


def decision_of(printed):
    if printed is None:
        return "allow"
    if printed.get("continue") is False:
        return "halt"
    return printed["hookSpecificOutput"]["permissionDecision"]


def test_a_create_inside_the_boundary_is_denied(run):
    decision, printed, records = run(
        "drive_folders.py prints a path twice",
        description="libs/shared/peech_shared/drive_folders.py line 40")

    assert decision == "deny", f"expected deny, got {decision}"
    reason = printed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "libs/shared/peech_shared/drive_folders.py" in reason
    assert "outcome 1, fix it here" in reason
    assert records[-1]["reason"] == "denied"


def test_a_create_outside_the_boundary_is_allowed(run):
    decision, _, records = run(
        "slack.py drops a mention",
        description="libs/shared/peech_shared/slack.py line 90")

    assert decision == "allow", f"expected allow, got {decision}"
    assert records[-1]["reason"] == "allowed"


def test_a_create_naming_no_file_is_allowed(run):
    decision, _, _ = run("The board header reads oddly")

    assert decision == "allow", f"expected allow, got {decision}"


def test_a_ticket_with_no_pt_files_block_denies_nothing(run):
    decision, _, _ = run(
        "config/app.yml carries a stale comment",
        fetch=lambda key: {"description": "No block here.",
                           "customfield_10767": "config/app.yml"})

    assert decision == "allow", f"expected allow, got {decision}"


def test_a_file_the_conditions_measure_halts(run):
    decision, printed, records = run("config/app.yml has a second id block")

    assert decision == "deny", f"expected deny, got {decision}"
    assert "continue" not in printed, "continue: false stops the agent " \
        "without cancelling the create"
    reason = printed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "config/app.yml" in reason
    assert "PPA-997" in reason
    assert "halt rung" in reason
    assert "stop and ask the conductor to rule" in reason
    assert records[-1]["reason"] == "halted"


def test_no_dispatched_ticket_passes_through(run):
    decision, _, records = run("config/app.yml has a second id block",
                               dispatch="just a question, no key")

    assert decision == "allow", f"expected allow, got {decision}"
    assert records[-1]["reason"] == "no-dispatch"


def test_a_later_dispatch_supersedes_the_first_one(run):
    """PPA-1720. The first well-formed dispatch used to win, so a set corrected
    later in the session was still the boundary a create was judged against."""
    seen = []

    def fetch(key):
        seen.append(key)
        return TICKET

    decision, _, _ = run(
        "drive_folders.py prints a path twice",
        description="libs/shared/peech_shared/drive_folders.py line 40",
        dispatch=["PPA-997", "Run batch 02 \u2014 set: PPA-998", "PPA-999"],
        fetch=fetch)

    assert decision == "deny", f"expected deny, got {decision}"
    assert seen == ["PPA-999"], f"scoped to {seen}, not the latest dispatch"


def test_a_malformed_prompt_after_a_dispatch_leaves_that_dispatch_in_force(run):
    seen = []

    def fetch(key):
        seen.append(key)
        return TICKET

    run("config/app.yml has a second id block", fetch=fetch,
        dispatch=["PPA-997", "PPA-997 looks done, push it"])

    assert seen == ["PPA-997"]


def test_a_create_outside_ppa_passes_through(run):
    decision, _, records = run("config/app.yml", project="AISD2026")

    assert decision == "allow", f"expected allow, got {decision}"
    assert records[-1]["reason"] == "not-ppa"


def test_an_unreachable_jira_allows_and_logs(run):
    def unreachable(key):
        raise OSError("Jira unreachable")

    decision, _, records = run("config/app.yml has a second id block",
                               fetch=unreachable)

    assert decision == "allow", f"expected allow, got {decision}"
    assert records[-1]["reason"] == "hook-failed"
    assert "Jira unreachable" in records[-1]["error"]


def test_a_malformed_payload_allows_and_logs(tmp_path, monkeypatch):
    log = tmp_path / "hook.log"
    monkeypatch.setattr(hook, "LOG", log)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)

    assert hook.main() == 0
    assert out.getvalue() == "", "expected allow, got output"
    assert json.loads(log.read_text())["reason"] == "unreadable-payload"


def test_the_hooks_json_matcher_is_the_tool_the_hook_checks():
    """A matcher naming a tool that does not exist never fires and reports
    nothing, so the registration and TOOL have to be the same string.

    PPA-1586. The plugin registers it in hooks/hooks.json."""
    settings = json.loads((HOOK.parent / "hooks.json").read_text())
    matchers = [entry["matcher"] for entry in settings["hooks"]["PreToolUse"]
                if any("deny_in_scope_spawn.py" in h["command"]
                       for h in entry["hooks"])]
    assert matchers == [hook.TOOL]


def test_editable_paths_reads_only_edit_lines():
    assert hook.editable_paths(BOUNDARY) == [
        "libs/shared/peech_shared/drive_folders.py", "config/app.yml"]


# ------------------------------------------------------------ PPA-1599 rungs

def test_a_create_naming_no_breakage_is_denied(run):
    decision, printed, records = run("The board header reads oddly",
                                     breaks=None)

    assert decision == "deny", f"expected deny, got {decision}"
    reason = printed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "carries no line beginning 'What breaks if not fixed:'" in reason
    assert "drop it with a comment in the code" in reason
    assert records[-1]["reason"] == "no-breakage"


@pytest.mark.parametrize("line", [
    "What breaks if not fixed: nothing",
    "What breaks if not fixed: Nothing observable.",
    "What breaks if not fixed: none",
    "What breaks if not fixed: n/a",
    "What breaks if not fixed:",
])
def test_a_create_saying_nothing_breaks_is_denied(run, line):
    decision, printed, _ = run("The board header reads oddly", breaks=line)

    assert decision == "deny", f"expected deny for {line!r}, got {decision}"
    assert "says nothing breaks" in \
        printed["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("line", [
    BREAKS,
    "- **What breaks if not fixed:** the Stop gate passes a close-out it cannot read.",
])
def test_a_create_naming_a_consequence_is_allowed(run, line):
    decision, printed, records = run("The board header reads oddly", breaks=line)

    assert decision == "allow", f"expected allow for {line!r}, got {decision}"
    assert printed is None
    assert records[-1]["reason"] == "allowed"


def test_the_fix_here_deny_still_wins_over_the_breakage_line(run):
    decision, printed, _ = run(
        "drive_folders.py prints a path twice", breaks=None,
        description="libs/shared/peech_shared/drive_folders.py line 40")

    assert decision == "deny"
    assert "outcome 1, fix it here" in \
        printed["hookSpecificOutput"]["permissionDecisionReason"]


def test_the_second_create_in_a_session_is_denied_naming_the_first(run):
    first, _, _ = run("The board header reads oddly")
    decision, printed, records = run("The footer reads oddly too")

    assert first == "allow", f"expected the first create allowed, got {first}"
    assert decision == "deny", f"expected deny, got {decision}"
    assert "continue" not in printed, "continue: false stops the agent " \
        "without cancelling the create"
    reason = printed["hookSpecificOutput"]["permissionDecisionReason"]
    assert FIRST_KEY in reason
    assert "The board header reads oddly" in reason
    assert "ask the conductor to rule" in reason
    for choice in ("fold this finding into", "fix it here", "open the second"):
        assert choice in reason
    assert records[-1]["reason"] == "second-create"


def test_a_create_after_the_halt_is_the_conductors_ruling_and_passes(run):
    run("The board header reads oddly")
    run("The footer reads oddly too")
    decision, _, records = run("The footer reads oddly too")

    assert decision == "allow", f"expected allow, got {decision}"
    assert records[-1]["reason"] == "allowed"


def test_creates_in_another_session_do_not_count(run):
    run("The board header reads oddly", session="another-session")
    decision, _, _ = run("The footer reads oddly too")

    assert decision == "allow", f"expected allow, got {decision}"


def test_a_denied_create_does_not_count_as_the_first(run):
    run("The board header reads oddly", breaks=None)
    decision, _, _ = run("The footer reads oddly too")

    assert decision == "allow", f"expected allow, got {decision}"


def test_an_unreadable_log_allows_the_create_and_logs(run, monkeypatch):
    run("The board header reads oddly")

    def unreadable(session_id):
        raise OSError("log unreadable")

    monkeypatch.setattr(hook, "session_records", unreadable)
    decision, _, records = run("The footer reads oddly too")

    assert decision == "allow", f"expected allow, got {decision}"
    assert records[-1]["reason"] == "hook-failed"
    assert "log unreadable" in records[-1]["error"]


def test_an_unreachable_jira_on_the_count_allows_and_logs(run, monkeypatch):
    run("The board header reads oddly")

    def unreachable(summary, since):
        raise OSError("Jira search unreachable")

    monkeypatch.setattr(hook, "created_key", unreachable)
    decision, _, records = run("The footer reads oddly too")

    assert decision == "allow", f"expected allow, got {decision}"
    assert records[-1]["reason"] == "hook-failed"
    assert "Jira search unreachable" in records[-1]["error"]


def test_created_key_matches_the_summary_exactly(monkeypatch):
    seen = []

    def get(path):
        seen.append(path)
        return {"issues": [
            {"key": "PPA-1", "fields": {"summary": "The board header reads oddly, again"}},
            {"key": "PPA-2", "fields": {"summary": "The board header reads oddly"}}]}

    monkeypatch.setattr(hook, "_jira_get", get)

    assert hook.created_key("The board header reads oddly",
                            "2026-09-23T10:00:00-04:00") == "PPA-2"
    assert "2026-09-22" in seen[0] and seen[0].startswith("/search/jql?jql=")


def test_a_peechpmo_create_inside_the_boundary_is_denied(run):
    """PPA-1825. A create in PEECHPMO was logged not-ppa and allowed."""
    decision, _, records = run(
        "drive_folders.py prints a path twice", project="PEECHPMO",
        dispatch="PEECHPMO-997",
        description="libs/shared/peech_shared/drive_folders.py line 40")

    assert decision == "deny", f"expected deny, got {decision}"
    assert records[-1]["reason"] == "denied"
