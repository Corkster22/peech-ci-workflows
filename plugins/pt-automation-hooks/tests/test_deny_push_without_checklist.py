"""deny_push_without_checklist.py - the ticket-branch push guard (PPA-1626).

Each test drives ``decide()`` against a real git repository in tmp_path and a
transcript on disk, with Jira stubbed: the branch name and the head commit are
read from git as a session's push would read them, and no test reaches Jira.
"""

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1]
HOOK = PLUGIN / "hooks" / "deny_push_without_checklist.py"


def _load():
    spec = importlib.util.spec_from_file_location("deny_push_without_checklist", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()


def comment(text):
    """One Jira comment as the v3 API returns it, its body in ADF."""
    return {"body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}}


CHECKLIST = comment("1. The hook denies a push with no checklist - MET")
PROSE = comment("Pushed the branch; every condition is met.")


def read_key(path):
    """The key a stubbed Jira read was for."""
    return re.match(r"/issue/([A-Z]+-\d+)\?fields=comment,customfield_10767",
                    path).group(1)


def jira(comments_by_key, dod_by_key=None):
    """A Jira stub answering the one read the hook makes per key. A key with no
    entry in ``dod_by_key`` has an empty Definition of Done, which keeps the
    PPA-1626 test: one comment stating a row."""
    calls = []

    def get(path, timeout):
        calls.append((path, timeout))
        key = read_key(path)
        return {"fields": {
            "comment": {"comments": comments_by_key.get(key, [])},
            "customfield_10767": (dod_by_key or {}).get(key)}}

    get.calls = calls
    return get


def git(repo, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: the work (PPA-1)")
    git(tmp_path, "checkout", "-q", "-b", "ppa-1-guard")
    return tmp_path


def payload(repo, command="git push -u origin HEAD", dispatch="PPA-1, PPA-2"):
    transcript = repo / "transcript.jsonl"
    transcript.write_text(json.dumps(
        {"type": "user", "message": {"content": dispatch}}) + "\n")
    return {"tool_name": "Bash", "cwd": str(repo),
            "transcript_path": str(transcript),
            "tool_input": {"command": command}}


def denial(output):
    """The PreToolUse decision, or {} - so a missing deny fails an assertion
    on its value rather than raising on None."""
    return (output or {}).get("hookSpecificOutput") or {}


def test_denies_a_ppa_push_with_no_checklist(repo):
    get = jira({"PPA-1": [CHECKLIST], "PPA-2": [PROSE]})
    decision = denial(hook.decide(payload(repo), get))
    assert decision.get("permissionDecision") == "deny"
    reason = decision["permissionDecisionReason"]
    assert "PPA-2 carries no close-out checklist" in reason
    assert "PPA-1," not in reason
    assert "| 1 | <the condition text, quoted> | MET |" in reason
    assert "1. <the condition text, quoted> - MET" in reason


def test_allows_a_ppa_push_once_every_key_has_a_checklist(repo):
    get = jira({"PPA-1": [PROSE, CHECKLIST], "PPA-2": [CHECKLIST]})
    assert hook.decide(payload(repo), get) is None
    assert len(get.calls) == 2


def test_a_malformed_first_prompt_is_checked_against_the_later_dispatch(repo):
    """PPA-1720. session_keys stopped at a malformed first prompt, so this
    guard saw no keys and let the push through unchecked."""
    call = payload(repo)
    Path(call["transcript_path"]).write_text("\n".join(json.dumps(
        {"type": "user", "message": {"content": text}})
        for text in ("Run batch 01 \u2014 set: PPA-1", "PPA-2")) + "\n")
    get = jira({"PPA-1": [CHECKLIST], "PPA-2": [PROSE]})

    decision = denial(hook.decide(call, get))

    assert decision.get("permissionDecision") == "deny"
    assert "PPA-2 carries no close-out checklist" in decision[
        "permissionDecisionReason"]
    assert [read_key(path) for path, _ in get.calls] == ["PPA-2"]


def test_a_superseded_dispatch_is_not_the_set_checked(repo):
    call = payload(repo)
    Path(call["transcript_path"]).write_text("\n".join(json.dumps(
        {"type": "user", "message": {"content": text}})
        for text in ("PPA-1", "PPA-2")) + "\n")
    get = jira({"PPA-1": [PROSE], "PPA-2": [CHECKLIST]})

    assert hook.decide(call, get) is None
    assert [read_key(path) for path, _ in get.calls] == ["PPA-2"]


def test_allows_a_non_ppa_branch_without_reading_jira(repo):
    git(repo, "checkout", "-q", "main")
    get = jira({})
    assert hook.decide(payload(repo, "git push origin main"), get) is None
    assert get.calls == []


def test_allows_a_work_in_progress_push_without_reading_jira(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "wip: halfway - pausing session")
    get = jira({})
    assert hook.decide(payload(repo), get) is None
    assert get.calls == []


def test_denies_and_names_the_error_and_key_when_jira_fails(repo):
    """PPA-1765 test (f), Decision 1A. The PPA-1626 behaviour was an allow with
    a warning; a gate that lets a push through on an error is not a gate."""
    def get(path, timeout):
        raise TimeoutError("timed out")

    decision = denial(hook.decide(payload(repo), get))

    assert decision.get("permissionDecision") == "deny"
    reason = decision["permissionDecisionReason"]
    assert "PPA-1" in reason
    assert "TimeoutError('timed out')" in reason


def test_a_read_that_fails_part_way_names_the_key_it_was_reading(repo):
    def get(path, timeout):
        if read_key(path) == "PPA-2":
            raise OSError("no route to host")
        return jira({"PPA-1": [CHECKLIST]})(path, timeout)

    reason = denial(hook.decide(payload(repo), get))["permissionDecisionReason"]

    assert "Jira read for PPA-2 failed" in reason
    assert "no route to host" in reason


def test_an_exhausted_budget_denies_and_names_the_key_not_yet_read(repo):
    ticks = iter([0, 0, hook.BUDGET + 1])
    get = jira({"PPA-1": [CHECKLIST], "PPA-2": [CHECKLIST]})

    with pytest.raises(hook.ReadFailed) as caught:
        hook.keys_with_gaps(["PPA-1", "PPA-2"], get, clock=lambda: next(ticks))

    assert caught.value.key == "PPA-2"
    assert isinstance(caught.value.error, TimeoutError)


def test_an_explicit_ppa_refspec_is_checked_from_another_branch(repo):
    git(repo, "checkout", "-q", "main")
    output = hook.decide(payload(repo, "git push origin main:ppa-1-guard"), jira({}))
    assert denial(output).get("permissionDecision") == "deny"


@pytest.mark.parametrize("command", [
    "git status", "git commit -m 'push the fix'", "echo git push"])
def test_a_command_running_no_push_is_not_checked(repo, command):
    get = jira({})
    assert hook.decide(payload(repo, command), get) is None
    assert get.calls == []


def test_the_jira_reads_stop_inside_the_hook_timeout():
    config = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    timeout = next(h["timeout"] for block in config["hooks"]["PreToolUse"]
                   for h in block["hooks"] if HOOK.name in h["command"])
    assert hook.JIRA_TIMEOUT <= hook.BUDGET < timeout


# ---------------------------------------------------------------------------
# PPA-1765: every Definition of Done condition pairs with a stated verdict.
#
# The fixtures are the stored text of two close-outs, read once from Jira on
# 01-OCT-2026 and embedded; no test makes a live call. PPA-1760 comment 30800
# keeps its condition text and verdict cells verbatim and abbreviates the
# evidence cells, which the parser does not read. PPA-1748 comment 30671 keeps
# its three rows verbatim and drops the paragraphs around them.
# ---------------------------------------------------------------------------

VERDICT_RULE = ("If a condition is fully met, write MET. If it carries a "
                "qualification or awaits a ruling, write NOT MET and put the "
                "reason in the evidence.")


def text_node(text):
    return {"type": "text", "text": text}


def paragraph(text):
    return {"type": "paragraph", "content": [text_node(text)]}


def doc(*blocks):
    return {"type": "doc", "version": 1, "content": list(blocks)}


def dod(*conditions):
    """The Definition of Done field as Jira returns it: a bullet list in ADF."""
    return doc({"type": "bulletList", "content": [
        {"type": "listItem", "content": [paragraph(text)]}
        for text in conditions]})


def table_row(kind, *cells):
    return {"type": "tableRow", "content": [
        {"type": kind, "attrs": {}, "content": [paragraph(cell)]}
        for cell in cells]}


def table_comment(intro, rows):
    """A close-out as a Jira ADF table: (number, quoted condition, verdict,
    evidence) per row, under the header the real comments carry."""
    return {"body": doc(paragraph(intro), {
        "type": "table", "attrs": {"layout": "default"}, "content": [
            table_row("tableHeader", "#", "Condition (quoted from the "
                      "Definition of Done)", "Verdict", "Evidence"),
            *(table_row("tableCell", str(n), quoted, verdict, evidence)
              for n, quoted, verdict, evidence in rows)]})}


def list_comment(*items):
    return {"body": doc({"type": "orderedList", "attrs": {"order": 1},
                         "content": [{"type": "listItem",
                                      "content": [paragraph(item)]}
                                     for item in items]})}


PPA_1760_DOD = dod(
    r"[machine] git grep -nE 'the four-ticket cap\.|Cap four tickets|up to the "
    r"cap|Split only under Batch size' <commit> -- skills/ returns no line at "
    r"the ticket's commit, run in peech-skills, with the command and output "
    r"quoted. The new Batch size line names the retired cap by design and does "
    r"not match this pattern.",
    "[machine] The four edits match the ticket's quoted text exactly, and the "
    "new Batch size line in the batch-formation reference reads the ticket's "
    "block text exactly, shown by a quoted diff of the ticket's own commit.",
    "[machine] Both skills' versions are incremented, and git show --name-only "
    "on the ticket's own commit lists only files under skills/pt-conduct-gates/ "
    "and skills/pt-priority-board/, plus any skill registry entry the version "
    "change requires.",
    "[machine] The skill conformance check passes in peech-skills, with its "
    "output quoted.",
    "[machine] Every finding names one of the three outcomes - fixed here, "
    "dropped, or ticketed. A fix here names its commit and its reproduction "
    "command. A drop quotes the comment recorded in the code and names what "
    "would break if it is never fixed. A finding reported with no outcome is an "
    "incomplete report.")

#: Condition 1's verdict cell reads "MET as written", which is not a verdict
#: alone, so the row states no verdict and the merge held PPA-1760 on it.
PPA_1760_ROWS = [
    (1, '"' + PPA_1760_DOD["content"][0]["content"][0]["content"][0]["content"][0]
     ["text"].removeprefix("[machine] ") + '"', "MET as written",
     "Before, at the parent commit 5d00a4d, the same command returned three lines."),
    (2, '"The four edits match the ticket\'s quoted text exactly, and the new '
        "Batch size line in the batch-formation reference reads the ticket's "
        "block text exactly, shown by a quoted diff of the ticket's own "
        'commit."', "MET", "git show -U0 e747d02: four edits."),
    (3, '"Both skills\' versions are incremented, and git show --name-only on '
        "the ticket's own commit lists only files under skills/pt-conduct-gates/ "
        "and skills/pt-priority-board/, plus any skill registry entry the "
        'version change requires."', "MET", "4-26-0 to 4-27-0; 1-3-1 to 1-3-2."),
    (4, '"The skill conformance check passes in peech-skills, with its output '
        'quoted."', "MET", "BLOCKING findings: 0, exit 0."),
    (5, '"Every finding names one of the three outcomes - fixed here, dropped, '
        "or ticketed. A fix here names its commit and its reproduction command. "
        "A drop quotes the comment recorded in the code and names what would "
        "break if it is never fixed. A finding reported with no outcome is an "
        'incomplete report."', "MET", "One finding, awaiting a ruling."),
]
PPA_1760_INTRO = "Close-out checklist, PPA-1760. Local commit e747d02."

PPA_1748_DOD = dod(
    "[machine] pt-coding-setup and pt-session-lifecycle name the same place "
    "for the Jira MCP server configuration.",
    "[machine] pt-coding-setup and pt-session-lifecycle state the same global "
    "ENABLE_CLAUDEAI_MCP_SERVERS value, or neither states one.",
    "[machine] python3 scripts/validate_skills.py passes in peech-skills.")

#: Three rows that each state MET and quote no condition text, so none pairs.
PPA_1748_CLOSE_OUT = list_comment(
    "[machine] MET. Both skills name one place for the Jira MCP server: one "
    "user-scope server per Mac. pt-session-lifecycle § Claude Code "
    "Configuration carries the route and the command.",
    "[machine] MET, by the \"neither states one\" branch. pt-session-lifecycle "
    "no longer tells the reader to set ENABLE_CLAUDEAI_MCP_SERVERS in global "
    "settings. pt-coding-setup states no value.",
    "[machine] MET. python3 scripts/validate_skills.py in peech-skills: All 22 "
    "skills and marketplace.json passed validation.")


def reason_of(output):
    return denial(output)["permissionDecisionReason"]


def test_a_close_out_leaving_condition_1_unpaired_is_denied(repo):
    """(a) PPA-1760 comment 30800. The merge held this ticket on condition 1,
    and the PPA-1626 guard let the push through because four rows parsed."""
    get = jira({"PPA-1": [table_comment(PPA_1760_INTRO, PPA_1760_ROWS)]},
               {"PPA-1": PPA_1760_DOD})

    output = hook.decide(payload(repo, dispatch="PPA-1"), get)

    assert denial(output).get("permissionDecision") == "deny"
    reason = reason_of(output)
    assert "PPA-1 leaves a Definition of Done condition with no stated verdict" in reason
    assert "  1. [machine] git grep -nE" in reason
    assert not re.search(r"^  [2-5]\. ", reason, re.MULTILINE), (
        "only the unpaired condition is named")


def test_the_refusal_names_the_shapes_the_fix_and_the_verdict_rule(repo):
    """PPA-1765 conditions 3 and 4: the two shapes, the Jira close-out comment
    as the thing to fix, and the verdict line verbatim."""
    get = jira({"PPA-1": [table_comment(PPA_1760_INTRO, PPA_1760_ROWS)]},
               {"PPA-1": PPA_1760_DOD})

    reason = reason_of(hook.decide(payload(repo, dispatch="PPA-1"), get))

    assert "1. <the condition text, quoted> - MET" in reason
    assert "| 1 | <the condition text, quoted> | MET |" in reason
    assert "The Jira close-out comment is the thing to fix" in reason
    assert VERDICT_RULE in reason


def test_the_same_close_out_with_condition_1_stated_met_is_allowed(repo):
    """(b) The one cell changed: MET as written becomes MET."""
    fixed = [(1, PPA_1760_ROWS[0][1], "MET", PPA_1760_ROWS[0][3]),
             *PPA_1760_ROWS[1:]]
    get = jira({"PPA-1": [table_comment(PPA_1760_INTRO, fixed)]},
               {"PPA-1": PPA_1760_DOD})

    assert hook.decide(payload(repo, dispatch="PPA-1"), get) is None


def test_a_close_out_quoting_no_condition_is_denied_naming_all_three(repo):
    """(c) PPA-1748 comment 30671. Three rows state MET, quote nothing, and
    the merge held the ticket on all three."""
    get = jira({"PPA-1": [PPA_1748_CLOSE_OUT]}, {"PPA-1": PPA_1748_DOD})

    reason = reason_of(hook.decide(payload(repo, dispatch="PPA-1"), get))

    assert "  1. [machine] pt-coding-setup and pt-session-lifecycle name the same" in reason
    assert "  2. [machine] pt-coding-setup and pt-session-lifecycle state the same" in reason
    assert "  3. [machine] python3 scripts/validate_skills.py passes" in reason


def test_a_close_out_pairing_every_condition_is_allowed(repo):
    """(d)"""
    conditions = ["The hook denies an unpaired close-out.",
                  "The hook allows a paired close-out."]
    close_out = list_comment(*(f"{text} - MET" for text in conditions))
    get = jira({"PPA-1": [close_out]}, {"PPA-1": dod(*conditions)})

    assert hook.decide(payload(repo, dispatch="PPA-1"), get) is None


def test_a_condition_stated_not_met_is_paired_and_the_merge_decides(repo):
    """Paired is not passed. NOT MET is a stated verdict, and holding the
    ticket on it is the merge close-out's call: 14 of the 65 holds measured on
    PPA-1764 were that, and the hold working correctly."""
    conditions = ["The hook denies an unpaired close-out."]
    close_out = list_comment(f"{conditions[0]} - NOT MET")
    get = jira({"PPA-1": [close_out]}, {"PPA-1": dod(*conditions)})

    assert hook.decide(payload(repo, dispatch="PPA-1"), get) is None


def test_two_close_outs_are_graded_on_the_comment_the_merge_selects(repo):
    """(e) The merge close-out's rule is ``merged_verdicts``: the base is the
    most complete checklist, and a later comment overrides only the rows it
    pairs. Here the EARLIER comment pairs all three conditions and the LATER
    one pairs one and carries a row quoting no condition, so the earlier is the
    base and the later overrides condition 1 alone. The push is allowed, as the
    merge would grade it. Recency would deny it."""
    import pr_merge_close_out as merge

    conditions = ["The hook denies an unpaired close-out.",
                  "The hook allows a paired close-out.",
                  "The hook denies when Jira cannot be read."]
    earlier = list_comment(*(f"{text} - MET" for text in conditions))
    later = list_comment(f"{conditions[0]} - MET",
                         "A restated row quoting nothing the field says - MET")
    comments = [earlier, later]

    _, used, _ = merge.merged_verdicts(
        comments, merge.conditions_in(dod(*conditions)), "PPA-1")
    assert used[0] is earlier, "the merge selects the earlier, fuller comment"
    assert used[1:] == [later], "the later comment only overrides what it pairs"

    get = jira({"PPA-1": comments}, {"PPA-1": dod(*conditions)})
    assert hook.decide(payload(repo, dispatch="PPA-1"), get) is None


def test_an_absent_checklist_names_every_condition(repo):
    conditions = ["The hook denies an unpaired close-out.",
                  "The hook allows a paired close-out."]
    get = jira({"PPA-1": [PROSE]}, {"PPA-1": dod(*conditions)})

    reason = reason_of(hook.decide(payload(repo, dispatch="PPA-1"), get))

    assert "PPA-1 carries no close-out checklist in Jira." in reason
    assert "  1. The hook denies an unpaired close-out." in reason
    assert "  2. The hook allows a paired close-out." in reason


def test_an_empty_definition_of_done_keeps_the_one_row_test(repo):
    """Today's behaviour for a key with nothing to pair against."""
    allowed = jira({"PPA-1": [CHECKLIST]})
    denied = jira({"PPA-1": [PROSE]})

    assert hook.decide(payload(repo, dispatch="PPA-1"), allowed) is None
    assert "PPA-1 carries no close-out checklist" in reason_of(
        hook.decide(payload(repo, dispatch="PPA-1"), denied))
