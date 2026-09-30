"""grade_definition_of_done.py — the Stop-event Definition of Done gate (PPA-1519).

The hook is under the plugin's hooks/, not on sys.path, so it is loaded by path, the
same way test_transition_on_prompt.py loads its own subject.

Every test drives ``main()`` end to end: a payload on stdin, a transcript on
disk, and a stubbed Jira read. That is deliberate — the contract the ticket
asks for is what reaches stdout and what the exit code is, and neither is
observable from the helpers alone. No test here reaches Jira, and the one that
asserts the gate does not read Jira asserts it by counting calls to a stub that
would raise.
"""

import importlib.util
import io
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

#: The plugin root. The single-definition tests below search it, and
#: pr_merge_close_out.py no longer ships in it (PPA-1605).
REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "grade_definition_of_done.py"


def _load():
    spec = importlib.util.spec_from_file_location("grade_definition_of_done", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()


# ------------------------------------------------------------- the fixtures

def dod(*texts):
    """``customfield_10767``'s ADF, as the field returns it."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": text}]}]}
                for text in texts
            ],
        }],
    }


TWO = ("[machine] The grader refuses a stop when any condition has no verdict.",
       "[machine] The full pytest pass count is quoted from a run.")


def transcript(tmp_path, prompt, close_out=None, name="t.jsonl"):
    """A transcript holding one dispatch and, optionally, one reply."""
    records = [
        {"type": "user", "message": {"content": prompt}},
    ]
    if close_out is not None:
        records.append({"type": "assistant", "message": {
            "content": [{"type": "text", "text": close_out}]}})
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return str(path)


def transcript_of(tmp_path, prompts, close_out=None, name="multi.jsonl"):
    """A transcript holding several user prompts in order (PPA-1720) and,
    optionally, one reply after the last."""
    records = [{"type": "user", "message": {"content": prompt}}
               for prompt in prompts]
    if close_out is not None:
        records.append({"type": "assistant", "message": {
            "content": [{"type": "text", "text": close_out}]}})
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _log_elsewhere(tmp_path, monkeypatch):
    """Every test writes its log inside its own tmp_path.

    Autouse and unconditional: ``LOG`` is a real path in the operator's home,
    and a suite that appends to it on every run pollutes the one record the
    first live firing is supposed to leave. The one test that reads the log
    sets its own path over the top of this.
    """
    monkeypatch.setattr(hook, "LOG", tmp_path / "autouse-gate.log")


def run(monkeypatch, capsys, payload, conditions=TWO, get=None):
    """Drive ``main()`` once. Returns (exit code, the parsed stdout or None)."""
    calls = []

    def stub(path, timeout=hook.JIRA_TIMEOUT):
        calls.append(path)
        if get is not None:
            return get(path)
        return {"fields": {"customfield_10767": dod(*conditions)}}

    monkeypatch.setattr(hook, "jira_get", stub)
    monkeypatch.setattr(hook, "conditions_of",
                        lambda key, get=stub: hook.conditions_in(
                            (get(f"/issue/{key}").get("fields") or {})
                            .get("customfield_10767")))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = hook.main()
    out = capsys.readouterr().out.strip()
    return code, (json.loads(out) if out else None), calls


DISPATCH = "PPA-1519\n\nBuild it as written."


# ------------------------------------------------------------- named tests

def test_every_condition_stated_permits_the_stop(tmp_path, monkeypatch, capsys):
    """A turn stating a verdict for every condition permits the stop."""
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
        "| 2 | The full pytest pass count is quoted from a run | MET |\n")
    code, out, _ = run(monkeypatch, capsys, {
        "stop_hook_active": False,
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert out is None


def test_an_unstated_condition_refuses_and_names_it(tmp_path, monkeypatch, capsys):
    """A turn leaving one condition unstated refuses the stop and names it."""
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert out["decision"] == "block"
    assert "PPA-1519 condition 2: no verdict in this turn." in out["reason"]


def test_a_condition_not_met_refuses_and_names_it(tmp_path, monkeypatch, capsys):
    """A turn reporting a condition not met refuses the stop and names it."""
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
        "| 2 | The full pytest pass count is quoted from a run | NOT MET |\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert "PPA-1519 condition 2: NOT MET." in out["reason"]


def test_a_finding_with_no_allowed_outcome_refuses(tmp_path, monkeypatch, capsys):
    """A finding whose outcome word is none of the three refuses and is named."""
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
        "| 2 | The full pytest pass count is quoted from a run | MET |\n"
        "\n"
        "Finding 1 - the register's prose on check_claudemd.py is stale.\n"
        "Reported, not fixed.\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert "states no allowed outcome" in out["reason"]
    assert "the register's prose on check_claudemd.py is stale" in out["reason"]


#: Both conditions stated met, so a refusal below is the finding's alone.
MET_BOTH = (
    "| # | Condition | Verdict |\n"
    "| --- | --- | --- |\n"
    "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
    "| 2 | The full pytest pass count is quoted from a run | MET |\n"
    "\n"
    "Finding 1 - the register's prose on check_claudemd.py is stale.\n")


@pytest.mark.parametrize("outcome", [
    "Outcome: fixed here, commit abc1234, reproduced with pytest tests/.",
    "Outcome: ticketed as PPA-1601.",
    # PPA-1600: a drop names what breaks, or it refuses - see below.
    "Outcome: dropped. Nothing reads that prose.\n"
    "What breaks if not fixed: nothing observable; no code path reads it.",
])
def test_a_finding_naming_one_of_the_three_passes(
        tmp_path, monkeypatch, capsys, outcome):
    """The same finding, worded to the condition, does not refuse."""
    close_out = MET_BOTH + outcome + "\n"
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert out is None


def test_stop_hook_active_exits_zero_and_reads_no_jira(tmp_path, monkeypatch, capsys):
    """stop_hook_active true exits 0 without reading Jira."""
    def explode(path):
        raise AssertionError("the gate read Jira with stop_hook_active true")

    code, out, calls = run(monkeypatch, capsys, {
        "stop_hook_active": True,
        "transcript_path": transcript(tmp_path, DISPATCH, "nothing stated"),
    }, get=explode)
    assert code == 0
    assert out is None
    assert calls == []


def test_unresolvable_keys_refuse_the_stop(tmp_path, monkeypatch, capsys):
    """An unreadable transcript resolves no keys, and refuses."""
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": str(tmp_path / "absent.jsonl"),
    })
    assert code == 0
    assert "the gate did not run" in out["reason"]
    assert "could not be resolved" in out["reason"]
    assert calls == []


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root reads a mode-000 file, so there is nothing to deny")
def test_an_unreadable_transcript_refuses_the_stop(tmp_path, monkeypatch, capsys):
    """A transcript that exists but cannot be opened refuses, and says so.

    The case condition 6 names that the absent-file case does not reach. This
    transcript carries a real dispatch, so every earlier reading of it - is it
    there, does it name a ticket - answers yes; only the read itself fails.
    A gate that tested existence rather than readability graded this as a
    session that dispatched nothing and permitted the stop.
    """
    path = Path(transcript(tmp_path, DISPATCH, "| 1 | x | MET |"))
    path.chmod(0o000)
    try:
        code, out, calls = run(monkeypatch, capsys, {
            "transcript_path": str(path),
        })
    finally:
        path.chmod(0o644)
    assert code == 0
    assert "the gate did not run" in out["reason"]
    assert "could not be resolved" in out["reason"]
    assert "PermissionError" in out["reason"]
    assert calls == []


def test_a_malformed_dispatch_line_refuses_the_stop(tmp_path, monkeypatch, capsys):
    """A first line carrying keys that is not a dispatch resolves nothing."""
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": transcript(
            tmp_path, "Please build PPA-1519 today.", "| 1 | x | MET |"),
    })
    assert code == 0
    assert "the gate did not run" in out["reason"]
    assert calls == []


# ------------------------------------------- PPA-1720: the latest valid dispatch

ALL_MET = (
    "| # | Condition | Verdict |\n"
    "| --- | --- | --- |\n"
    "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
    "| 2 | The full pytest pass count is quoted from a run | MET |\n")


def test_a_malformed_first_prompt_grades_against_the_later_keys_only_dispatch(
        tmp_path, monkeypatch, capsys):
    """PPA-1714, 29-SEP-2026. The first prompt opened "Run batch 01 - set:
    PPA-1714" and the conductor re-dispatched with the key alone. The gate
    refused twice as unresolvable and the work shipped ungraded."""
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": transcript_of(
            tmp_path, ["Run batch 01 \u2014 set: PPA-1714", "PPA-1519"], ALL_MET),
    })
    assert code == 0
    assert out is None, "the later dispatch was graded and met"
    assert calls == ["/issue/PPA-1519"], "graded against the later keys alone"


def test_a_malformed_prompt_with_no_later_dispatch_still_refuses_as_malformed(
        tmp_path, monkeypatch, capsys):
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": transcript_of(
            tmp_path, ["Run batch 01 \u2014 set: PPA-1714", "thanks, go on"],
            ALL_MET),
    })
    assert code == 0
    assert "the dispatch could not be resolved" in out["reason"]
    assert "PPA-1714" in out["reason"]
    assert calls == []


def test_a_later_dispatch_supersedes_an_earlier_well_formed_one(
        tmp_path, monkeypatch, capsys):
    """The other half of the incident class (PPA-1698 comment 30438): a gate
    fixed to the session's first dispatch graded the set it started with."""
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": transcript_of(
            tmp_path, ["PPA-1518", "PPA-1519, PPA-1520"], ALL_MET),
    })
    assert calls == ["/issue/PPA-1519", "/issue/PPA-1520"]


def test_a_well_formed_first_dispatch_grades_as_it_did(
        tmp_path, monkeypatch, capsys):
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": transcript_of(
            tmp_path, [DISPATCH, "and check the tests too"], ALL_MET),
    })
    assert code == 0
    assert out is None
    assert calls == ["/issue/PPA-1519"]


def test_a_follow_up_opening_on_a_key_does_not_undo_the_dispatch(
        tmp_path, monkeypatch, capsys):
    """A malformed prompt after a well-formed dispatch is a follow-up, not a
    re-dispatch. Refusing on it would stop every session whose user typed
    "PPA-1519 looks done, push it" after the dispatch."""
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": transcript_of(
            tmp_path, [DISPATCH, "PPA-1519 looks done, push it"], ALL_MET),
    })
    assert code == 0
    assert out is None
    assert calls == ["/issue/PPA-1519"]


def test_a_session_dispatching_nothing_permits_the_stop(tmp_path, monkeypatch, capsys):
    """A readable transcript naming no ticket has nothing to grade."""
    code, out, calls = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, "What does this repo do?", "It reports."),
    })
    assert code == 0
    assert out is None
    assert calls == []


def test_a_jira_timeout_refuses_and_says_the_gate_did_not_run(
        tmp_path, monkeypatch, capsys):
    """A Jira timeout refuses the stop and says the gate did not run."""
    def timeout(path):
        raise TimeoutError("timed out")

    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, "| 1 | x | MET |"),
    }, get=timeout)
    assert code == 0
    assert "the gate did not run" in out["reason"]
    assert "TimeoutError" in out["reason"]


def test_twenty_conditions_stay_under_the_ten_thousand_character_cap(
        tmp_path, monkeypatch, capsys):
    """Output over the 10,000-character cap is not produced for 20 conditions."""
    conditions = tuple(
        f"[machine] Condition {n} requires distinctive evidence alpha{n} "
        f"quoted from a run in peech-pmo-automation, and nothing else."
        for n in range(1, 21))
    # One row of twenty, not none: a close-out yielding no row at all is now
    # one shape message (PPA-1546), and the cap is about the per-condition
    # enumeration, which needs a close-out the extractor can read.
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | Condition 1 requires distinctive evidence alpha1 quoted "
        "from a run | MET |\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    }, conditions=conditions)
    assert code == 0
    payload = json.dumps({"decision": "block", "reason": out["reason"]})
    assert len(out["reason"]) < 10000, len(out["reason"])
    assert len(payload) < 10000, len(payload)
    # Every one of the nineteen is still named, so the clip is headroom rather
    # than a truncation the session would have to guess around.
    for n in range(2, 21):
        assert f"condition {n}: no verdict" in out["reason"]


# --------------------------------------------------- the ticket's own shape

def test_the_jira_timeout_is_shorter_than_the_hook_timeout():
    """The Jira read's timeout is shorter than the declared hook timeout."""
    settings = json.loads((HOOK.parent / "hooks.json").read_text())
    declared = [h["timeout"] for group in settings["hooks"]["Stop"]
                for h in group["hooks"]
                if "grade_definition_of_done.py" in h["command"]]
    assert declared == [60]
    assert declared[0] > hook.JIRA_TIMEOUT


def test_the_grader_defines_no_second_pairing_function():
    """The pairing function is imported, and there is one definition of it."""
    source = HOOK.read_text()
    assert "from pr_merge_close_out import" in source
    assert "pair_rows" in source
    assert "def pair_rows" not in source
    defined = [p for p in REPO.rglob("*.py")
               if "__pycache__" not in p.parts
               and re.search(r"^def pair_rows\(", p.read_text(), re.M)]
    assert defined == []
    assert Path(hook.pair_rows.__code__.co_filename) == hook.CLOSE_OUT


def test_the_grader_defines_no_second_readable_close_out():
    """PPA-1546. What counts as a readable close-out has one definition.

    The shape refusal is decided by ``stated_rows`` - the same extractor
    scripts/pr_merge_close_out.py reads its own rows with - rather than by a
    second rule about lines. A second definition would drift from the first
    and the merge would start disagreeing with the gate about what it can read.
    """
    source = HOOK.read_text()
    assert "stated_rows" in source
    assert "def stated_rows" not in source
    defined = [p for p in REPO.rglob("*.py")
               if "__pycache__" not in p.parts
               and re.search(r"^def stated_rows\(", p.read_text(), re.M)]
    assert defined == []
    assert Path(hook.stated_rows.__code__.co_filename) == hook.CLOSE_OUT


def test_the_stop_is_refused_through_stdout_not_an_exit_code(
        tmp_path, monkeypatch, capsys):
    """The unmet list travels as JSON on stdout; the exit code carries none."""
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert set(out) == {"decision", "reason"}
    assert out["decision"] == "block"
    assert "condition 2: no verdict" in out["reason"]


def test_the_log_records_what_the_live_payload_carried(
        tmp_path, monkeypatch, capsys):
    """Each firing records the payload's field set, which is unreadable from
    inside the turn that writes the close-out - see LOG's own note."""
    monkeypatch.setattr(hook, "LOG", tmp_path / "gate.log")
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
        "| 2 | The full pytest pass count is quoted from a run | MET |\n")
    code, _out, _calls = run(monkeypatch, capsys, {
        "session_id": "abc",
        "stop_hook_active": False,
        "last_assistant_message": close_out,
        "transcript_path": transcript(tmp_path, DISPATCH, "something else"),
    })
    assert code == 0
    record = json.loads((tmp_path / "gate.log").read_text().splitlines()[-1])
    assert record["keys"] == [
        "last_assistant_message", "session_id", "stop_hook_active",
        "transcript_path"]
    assert record["has_last_assistant_message"] is True
    assert record["outcome"] == "permitted:last_assistant_message"


def test_the_payload_beats_the_transcript_for_the_close_out(
        tmp_path, monkeypatch, capsys):
    """last_assistant_message is the carrier; the transcript is the fallback."""
    stated = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
        "| 2 | The full pytest pass count is quoted from a run | MET |\n")
    payload = {"transcript_path": transcript(tmp_path, DISPATCH, "no verdicts")}
    code, out, _ = run(monkeypatch, capsys,
                       {**payload, "last_assistant_message": stated})
    assert (code, out) == (0, None)
    # Drop it and the same session is graded off the transcript, which states
    # nothing, so the stop is refused.
    code, out, _ = run(monkeypatch, capsys, payload)
    assert out["decision"] == "block"


def test_the_hook_runs_as_the_hooks_json_command_declares_it(tmp_path):
    """The declared command finds the hook, runs it, and returns its stdout.

    PPA-1586. The command finds the hook through CLAUDE_PLUGIN_ROOT, and the
    hook finds pt_transition.py in the peech-ci-workflows clone (PPA-1662)."""
    settings = json.loads((HOOK.parent / "hooks.json").read_text())
    command = next(h["command"] for group in settings["hooks"]["Stop"]
                   for h in group["hooks"]
                   if "grade_definition_of_done.py" in h["command"])
    # HOME moves so the log this firing writes lands in tmp_path rather than
    # the operator's home. Safe only because stop_hook_active short-circuits
    # ahead of pt_transition's credential path, which resolves off HOME too.
    home = {"CLAUDE_PLUGIN_ROOT": str(REPO), "CLAUDE_PROJECT_DIR": str(REPO.parents[1]),
            "HOME": str(tmp_path)}
    # The close-out clone resolves off HOME as well, so the moved HOME carries it.
    clone = tmp_path / hook.CLOSE_OUT.parents[1].relative_to(Path.home())
    clone.parent.mkdir(parents=True)
    clone.symlink_to(hook.CLOSE_OUT.parents[1])
    result = subprocess.run(
        ["bash", "-c", command],
        input=json.dumps({"stop_hook_active": True}),
        env={**os.environ, **home},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""

    missing = subprocess.run(
        ["bash", "-c", command],
        input="{}", env={**os.environ, **home, "CLAUDE_PLUGIN_ROOT": str(tmp_path)},
        capture_output=True, text=True, timeout=60)
    assert missing.returncode == 2
    assert "is missing" in missing.stderr


def test_a_missing_close_out_clone_warns_and_passes(tmp_path):
    """PPA-1605. pr_merge_close_out.py is read from the peech-ci-workflows clone.

    Where that clone is absent the hook names the missing path in a
    systemMessage and exits 0 - even on a stop it would otherwise grade, since
    nothing the session does inside the turn can put the clone there."""
    env = {**os.environ, "HOME": str(tmp_path),
           "CLAUDE_PROJECT_DIR": str(REPO.parents[1])}
    result = subprocess.run(
        ["python3", str(HOOK)], input="{}", env=env,
        capture_output=True, text=True, timeout=60)
    missing = (tmp_path / "Documents" / "Claude-Projects" / "peech-ci-workflows"
               / "scripts" / "pr_merge_close_out.py")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"systemMessage": (
        f"pt-automation-hooks: {missing} is missing, so the Definition of "
        "Done gate did not run. Clone peech-ci-workflows to that path.")}


@pytest.mark.parametrize("wording,refused", [
    ("Outcome: fixed here, commit abc1234.", False),
    ("Outcome: dropped - nothing observable breaks.", False),
    ("Outcome: ticketed as PPA-1600.", False),
    ("Outcome 1, fixed in a separate commit.", False),
    ("Reported, not fixed.", True),
    ("Reported, not acted on.", True),
    ("Not fixed here.", True),
])
def test_each_outcome_wording(wording, refused):
    """The three allowed spellings pass; the 17-SEP-2026 wordings do not."""
    text = f"Finding 1 - something.\n{wording}\n"
    assert bool(hook.findings_without_outcome(text)) is refused


# ------------------------------- PPA-1546: an unreadable close-out's shape

#: A close-out claiming every condition met, in prose. The extractor reads no
#: row from it, and until PPA-1546 it was refused with one "no verdict in this
#: turn" line per condition - which reads as missing verdicts to a session
#: whose verdicts are all present and all unreadable.
PROSE = (
    "I built PPA-1519 as written. Every Definition of Done condition is met: "
    "the grader refuses a stop when any condition has no verdict, and the "
    "full pytest pass count is quoted from the run above. Findings: none.")


def test_a_prose_close_out_is_refused_on_its_shape_and_said_once(
        tmp_path, monkeypatch, capsys):
    """Zero rows is named once as a shape, not enumerated per condition."""
    assert hook.stated_rows(PROSE.splitlines()) == [], (
        "the fixture has to yield no row for this to be the case under test")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, PROSE),
    })
    assert code == 0
    assert out["decision"] == "block"
    assert "No checklist row was found" in out["reason"]
    # Both shapes are named, so the session is told what to write rather than
    # only that what it wrote was wrong.
    assert "a line opening with a condition number" in out["reason"]
    assert "a pipe table row whose first non-empty cell" in out["reason"]
    # And the enumeration this replaces is gone. One line per condition is
    # what sent the session back to restate the same prose.
    assert "no verdict in this turn" not in out["reason"]


def test_some_rows_but_not_all_still_reports_per_condition(
        tmp_path, monkeypatch, capsys):
    """A close-out that did write a checklist keeps today's reporting.

    The rows here are genuinely missing rather than unreadable, so naming the
    shape would be wrong: the session already wrote the shape correctly.
    """
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert "PPA-1519 condition 2: no verdict in this turn." in out["reason"]
    assert "No checklist row was found" not in out["reason"]


def test_a_numbered_close_out_stating_every_verdict_passes(
        tmp_path, monkeypatch, capsys):
    """The first shape the refusal names is one the gate actually accepts."""
    close_out = (
        "1. The grader refuses a stop when any condition has no verdict "
        "— MET\n"
        "2. The full pytest pass count is quoted from a run — MET\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert (code, out) == (0, None)


def test_a_table_close_out_stating_every_verdict_passes(
        tmp_path, monkeypatch, capsys):
    """And so is the second. Named beside the numbered case on purpose: the
    refusal offers two shapes, so both are held at accepted here."""
    close_out = (
        "| # | Condition | Verdict |\n"
        "| --- | --- | --- |\n"
        "| 1 | The grader refuses a stop when any condition has no verdict | MET |\n"
        "| 2 | The full pytest pass count is quoted from a run | MET |\n")
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert (code, out) == (0, None)


@pytest.mark.parametrize("text,refused", [
    ("Finding 1 - x.\nReported, nothing done.\n", True),
    ("Finding 1 - the gate prints nothing on a pass.\nReported, not fixed.\n", True),
    ("Findings: none.\n", False),
    ("**Findings:** none beyond the ticket's own work.\n", False),
    ("- Findings - nothing to report.\n", False),
    ("No findings.\n", False),
])
def test_only_a_findings_line_saying_none_is_a_clean_close_out(text, refused):
    """PPA-1600, adjacent. "nothing" inside a real finding is not "none"."""
    assert bool(hook.findings_without_outcome(text)) is refused


# ---------------------------- PPA-1600: a drop names what breaks, or refuses

def test_a_drop_naming_no_breakage_refuses_the_stop(tmp_path, monkeypatch, capsys):
    """The refusal names the finding and tells the session the line to add."""
    close_out = MET_BOTH + "Outcome: dropped. Nothing reads that prose.\n"
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert code == 0
    assert out["decision"] == "block"
    assert ("finding is dropped but does not name what breaks if it is never "
            'fixed - add a line "What breaks if not fixed: <the consequence>" '
            "to it: Finding 1 - the register's prose on check_claudemd.py is "
            "stale.") in out["reason"]
    assert "states no allowed outcome" not in out["reason"]


@pytest.mark.parametrize("line", [
    "What breaks if not fixed: the merge close-out reads a stale register.",
    "What would break if it is never fixed - nothing observable; only the "
    "--verify-rules CLI reads that path.",
    "**What breaks if not fixed:** a second Stop hook fires on every session.",
])
def test_a_drop_naming_what_breaks_passes(tmp_path, monkeypatch, capsys, line):
    close_out = MET_BOTH + f"Outcome: dropped.\n{line}\n"
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(tmp_path, DISPATCH, close_out),
    })
    assert (code, out) == (0, None)


@pytest.mark.parametrize("text,unbroken", [
    ("Finding 1 - x.\nOutcome: fixed here, commit abc1234.\n", []),
    ("Finding 1 - x.\nOutcome: ticketed as PPA-1601.\n", []),
    ("Finding 1 - x.\nNot dropped; fixed here.\n", []),
    ("Finding 1 - x.\nOutcome: dropped.\nWhat breaks if not fixed:\n", ["Finding 1 - x."]),
    ("Findings: none.\n", []),
])
def test_only_a_drop_is_asked_what_breaks(text, unbroken):
    """Fixed here and ticketed grade as before; an empty answer is no answer."""
    assert hook.drops_without_breakage(text) == unbroken


# ------------------------------------------------- per-ticket sections (PPA-1619)

#: Two tickets of seven conditions each, the shape of the PPA-1612 and PPA-1613
#: close-out on PR #129. Each ticket's words are its own, so a row can only
#: pair to the ticket it quotes.
SEVEN = {
    "PPA-1612": tuple(
        f"[machine] The ledger writer {w} every weekly row." for w in (
            "stamps", "dedupes", "sorts", "validates", "archives", "hashes",
            "exports")),
    "PPA-1613": tuple(
        f"[machine] The roster reader {w} each staff record." for w in (
            "loads", "merges", "filters", "normalises", "caches", "audits",
            "publishes")),
}


def sectioned(verdicts=None):
    """A close-out with each ticket's rows under a heading naming its key."""
    verdicts = verdicts or {}
    out = []
    for key, conditions in SEVEN.items():
        out.append(f"### {key}")
        for n, text in enumerate(conditions, 1):
            quoted = text.removeprefix("[machine] ").rstrip(".")
            out.append(f"{n}. {quoted} - {verdicts.get((key, n), 'MET')}")
        out.append("")
    return "\n".join(out)


def by_key(path):
    key = re.search(r"PPA-\d+", path).group(0)
    return {"fields": {"customfield_10767": dod(*SEVEN[key])}}


def test_the_pr_129_close_out_is_graded_seven_rows_per_ticket(
        tmp_path, monkeypatch, capsys):
    """Condition 2: two tickets, seven conditions each, a heading per key. Each
    ticket is graded against its own seven rows, with no row-count mismatch."""
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(
            tmp_path, "PPA-1612, PPA-1613\n\nBuild both.", sectioned()),
    }, get=by_key)
    assert code == 0
    assert out is None, out and out["reason"]
    lines = sectioned().splitlines()
    for key in SEVEN:
        rows = hook.section_rows(lines, key)
        pairing = hook.pair_rows(hook.conditions_in(dod(*SEVEN[key])), rows)
        assert len(pairing.verdicts) == 7
        assert pairing.defects == []


def test_no_row_is_filed_against_a_ticket_it_does_not_name(
        tmp_path, monkeypatch, capsys):
    """Condition 1: a verdict under one key's heading refuses that key alone."""
    close_out = sectioned({("PPA-1613", 4): "NOT MET"})
    code, out, _ = run(monkeypatch, capsys, {
        "transcript_path": transcript(
            tmp_path, "PPA-1612, PPA-1613\n\nBuild both.", close_out),
    }, get=by_key)
    assert code == 0
    reason = out["reason"]
    assert "PPA-1613 condition 4: NOT MET." in reason
    assert "PPA-1612" not in reason, reason
    assert "row(s)" not in reason, reason
