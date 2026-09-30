"""transition_on_prompt.py — the UserPromptSubmit transition hook (PPA-1126).

The hook is under the plugin's hooks/, not on sys.path, so it is loaded by path.
Every test drives it end to end through stdin and a stub ``pt_transition.py``:
the contract the ticket asks for is about the hook's exit code and what it
fires, and neither is observable from the helpers alone.

The stub is what makes this suite fixture-driven rather than live. No test here
reaches Jira, and none reads the real credential file.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "transition_on_prompt.py"


def _load():
    spec = importlib.util.spec_from_file_location("transition_on_prompt", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load()

#: A second, never-patched instance. The sandbox fixture replaces three reader
#: functions on ``hook``, which is what keeps this suite off the network - but
#: PPA-1465 has to count the Jira calls a real dispatch makes, and that needs
#: the real readers. They are taken from here and patched back in for the one
#: case that wants them, with ``_jira_get`` stubbed underneath.
REAL = _load()


# ``pt_transition.py``'s real output shape, one line per key, no network.
STUB = '''#!/usr/bin/env python3
import sys
from pathlib import Path

VERDICT = "{verdict}"
keys = sys.argv[sys.argv.index("--keys") + 1].split(",")
Path(__file__).with_name("fired.txt").write_text("\\n".join(keys))
for key in keys:
    print(f"{{key:<10}} 'To Do' -> 'In Progress' hops=1 {{VERDICT}}")
sys.exit({code})
'''


@pytest.fixture(autouse=True)
def never_the_operators_own_log(tmp_path, monkeypatch):
    """PPA-1557. No test in this file appends to ~/.claude/pt-transition-hook.log.

    The `sandbox` fixture has redirected LOG since PPA-1262, but only for the
    tests that take it. `test_an_absent_plugins_tree_is_a_note_and_never_a_finding`
    takes `tmp_path` alone and calls skill_drift() on a path that does not
    exist, and the hook's own failure path wrote the resulting record - pytest
    temp path and all - straight to the operator's live log. Measured
    22-SEP-2026: 98 of that file's 177 lines carried a pytest-of- path,
    interleaved with the real dispatch failures the log exists to preserve.

    Autouse, because the defect is a test that forgot rather than a test that
    chose: a redirect each test opts into is one the next test can omit, and
    nothing in the output says so. `sandbox` still sets LOG for the cases that
    read their own writes; this only guarantees the floor.
    """
    monkeypatch.setattr(hook, "LOG",
                        tmp_path / "hook-log" / "pt-transition-hook.log")


def test_no_test_in_this_file_can_write_to_the_operators_own_log():
    """The fixture above, asserted rather than trusted. A test that reaches the
    operator's home directory is the failure; the path is the evidence."""
    assert str(Path.home() / ".claude") not in str(hook.LOG), (
        f"a test in this file would write to {hook.LOG}, which is under the "
        f"operator's own ~/.claude directory")


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """A fake peech-ci-workflows clone whose scripts/ holds a stub pt_transition.py.

    LOG is redirected as well (PPA-1262). The real one is under ~/.claude/, and
    a suite that appends to the operator's own failure log would both pollute it
    and read its own writes.
    """
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(hook, "REPO", tmp_path)
    monkeypatch.setattr(hook, "SCRIPT", scripts / "pt_transition.py")
    monkeypatch.setattr(hook, "LOG", tmp_path / "log" / "pt-transition-hook.log")
    monkeypatch.setattr(hook.tempfile, "gettempdir", lambda: str(tmp_path / "cache"))
    (tmp_path / "cache").mkdir()
    # PPA-1418 put a live Jira read in front of the transition, and PPA-1419
    # added a second one that resolves the repository from the dispatched
    # tickets. Every case below predates both and is about the transition half,
    # so each key resolves to one repository and the backlog is empty, which
    # blocks nothing. The completeness check has its own section, where both
    # are overridden per test.
    monkeypatch.setattr(hook, "repo_components_of",
                        lambda keys, **kw: dict.fromkeys(keys, "REPO: peech-skills"))
    monkeypatch.setattr(hook, "dispatchable_set", lambda component, **kw: [])
    # PPA-1716 made the completeness check read each key's work type. The
    # fixture keys below are invented, so none has one and the set stays whole.
    monkeypatch.setattr(hook, "work_types_of", lambda keys, **kw: {})
    # PPA-1465's shared read was the one live read left unstubbed, so 72 of this
    # file's cases searched the real Jira on every run. Handed None, each check
    # reads for itself, and each of those reads is stubbed above and below.
    monkeypatch.setattr(hook, "read_dispatched", lambda keys, **kw: (None, None))
    # PPA-1427 put a third live read in front of the transition. Same reasoning
    # as the two above: every case that predates it is about some other half of
    # the hook, so each key resolves to a ticket that passes the Bar and sits
    # at a status the cache may speak for. The Bar section overrides this.
    monkeypatch.setattr(hook, "bar_fields_of",
                        lambda keys, **kw: {k: bar_fields() for k in keys})
    # PPA-1465 put a fourth live read in front of the transition, and a refusal
    # with it. Every case below predates it, so the session is rooted in the
    # repository its fixture tickets name and the refusal never fires - which
    # is the condition under which the ticket promises this suite is unchanged.
    # The mismatch section overrides this to root the session elsewhere.
    root = tmp_path / "peech-skills"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    # PPA-1470 put the drift report in front of the transition. It reads
    # ~/.claude/plugins, which is the operator's real machine -
    # stubbed out here so no case below depends on what is installed on it.
    # The drift section builds its own trees and calls skill_drift() directly.
    monkeypatch.setattr(hook, "report_skill_drift", lambda *a, **kw: None)
    return tmp_path


def bar_fields(status="In Progress", **overrides):
    """Issue fields passing every mechanical Bar item, before ``overrides``.

    Written as a passing ticket that each case then breaks in exactly one way,
    so a refusal in a test is attributable to the item that test names and to
    nothing else.
    """
    fields = {
        "status": status,
        "components": ["EXA: Delegated", "REPO: peech-skills"],
        "repo_components": ["REPO: peech-skills"],
        "description": "## Scope boundary\nEdits one file and nothing else.",
        "dod": "One condition that can be evidenced.",
    }
    fields.update(overrides)
    return fields


def log_records():
    """Every record the hook appended, parsed. Empty when it wrote nothing."""
    if not hook.LOG.exists():
        return []
    return [json.loads(line) for line in hook.LOG.read_text().splitlines() if line]


def install_stub(sandbox, verdict="PASS", code=0):
    hook.SCRIPT.write_text(STUB.format(verdict=verdict, code=code))
    hook.SCRIPT.chmod(0o755)


def fired(sandbox):
    path = hook.SCRIPT.with_name("fired.txt")
    return path.read_text().splitlines() if path.exists() else []


def run(prompt, session="s1", capsys=None):
    """Drive main() with a payload on stdin, returning (exit code, stdout)."""
    payload = json.dumps({"prompt": prompt, "session_id": session,
                          "hook_event_name": "UserPromptSubmit"})
    sys.stdin = __import__("io").StringIO(payload)
    try:
        code = hook.main()
    finally:
        sys.stdin = sys.__stdin__
    out = capsys.readouterr().out if capsys else ""
    return code, out


# --------------------------------------------------------------------------
# Every key, never the first
# --------------------------------------------------------------------------

def test_a_multi_key_prompt_transitions_every_key(sandbox, capsys):
    """A batch prompt carries several keys; a hook that moves one looks like it
    worked and is worse than no hook."""
    install_stub(sandbox)

    code, out = run("PPA-1125, PPA-1126\n\nExecute as batch bat-cmd-08", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1125", "PPA-1126"]
    assert out == ""


def test_keys_are_deduplicated_and_uppercased(sandbox, capsys):
    install_stub(sandbox)

    run("ppa-900, PPA-900, PPA-901, PPA-900", capsys=capsys)

    assert fired(sandbox) == ["PPA-900", "PPA-901"]


def test_a_prompt_with_no_key_fires_nothing(sandbox, capsys):
    install_stub(sandbox)

    code, out = run("run the tests and report back", capsys=capsys)

    assert (code, out) == (0, "")
    assert fired(sandbox) == []


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("PPA-1125", ["PPA-1125"]),
        ("see PPA-1125.", ["PPA-1125"]),
        ("XPPA-1125", []),
        ("PPA-", []),
    ],
)
def test_key_matching_is_word_bounded(prompt, expected):
    assert hook.keys_in(prompt) == expected


# --------------------------------------------------------------------------
# It never blocks
# --------------------------------------------------------------------------

def test_a_script_failure_warns_and_exits_zero(sandbox, capsys):
    """A Jira or credential failure is bookkeeping, not a reason to refuse work."""
    install_stub(sandbox, verdict="HALT", code=1)

    code, out = run("PPA-1125", capsys=capsys)

    assert code == 0
    assert json.loads(out)["systemMessage"].startswith("PPA transition hook —")
    assert "PPA-1125" in json.loads(out)["systemMessage"]


# --------------------------------------------------------------------------
# PPA-1262 — a failure leaves a durable trace, not only a warning
# --------------------------------------------------------------------------
#
# Three dispatches on 07-SEP-2026 did not transition and the cause could not be
# recovered, because every failure path warned through systemMessage and
# returned 0. The warning is ephemeral; these tests pin the log that is not.
#
# No environment load is tested here, and none exists: pt_transition.py holds an
# absolute CREDENTIALS path and reads no os.environ, so the defect the original
# ticket described was not real. See the hook's module docstring.


def test_a_failing_subprocess_writes_a_log_line_and_exits_zero(sandbox, capsys):
    """The first amended named test — a non-zero exit is recorded.

    The record has to carry the exit code and the stderr, because a log saying
    only that something failed reproduces the hole it was added to close.
    """
    install_stub(sandbox, verdict="HALT", code=1)

    code, _ = run("PPA-1125", capsys=capsys)

    assert code == 0
    records = [r for r in log_records() if r["reason"] == "nonzero-exit"]
    assert len(records) == 1, f"expected one nonzero-exit record, got {log_records()}"
    record = records[0]
    assert record["keys"] == ["PPA-1125"]
    assert record["exit_code"] == 1
    assert record["at"], "a record with no timestamp cannot be placed in time"
    assert "HALT" in record["stdout"], "the reason for the halt lives on stdout"


def test_unparseable_output_writes_a_log_line_carrying_the_raw_output(
    sandbox, capsys
):
    """The second amended named test — a parse miss is recorded, with the text.

    A subprocess that ran and printed something this hook cannot read was
    indistinguishable from one that failed outright. The raw stdout is the
    whole evidence, so the record carries it verbatim.
    """
    hook.SCRIPT.write_text(
        "#!/usr/bin/env python3\n"
        "print('Traceback (most recent call last): something else entirely')\n"
    )
    hook.SCRIPT.chmod(0o755)

    code, _ = run("PPA-1125", capsys=capsys)

    assert code == 0
    records = [r for r in log_records() if r["reason"] == "unparseable-output"]
    assert len(records) == 1, f"expected one record, got {log_records()}"
    assert records[0]["keys"] == ["PPA-1125"]
    assert "something else entirely" in records[0]["stdout"], (
        "the raw output must be recorded verbatim, not summarized")


def test_an_all_halt_run_is_not_filed_as_a_parse_failure(sandbox, capsys):
    """A HALT is readable and settles nothing, which is not a parse failure.

    Filing the commonest real failure under "unparseable-output" would make the
    one reason that means "the log itself cannot be trusted" the noisiest one.
    """
    install_stub(sandbox, verdict="HALT", code=1)

    run("PPA-1125", capsys=capsys)

    assert [r["reason"] for r in log_records()] == ["nonzero-exit"]


def test_a_hook_exception_is_logged_and_still_exits_zero(sandbox, capsys):
    """Any exception is logged, including one the hook did not anticipate.

    Without the outer guard "every failure is logged" would hold only for the
    failures already thought of, which is the shape of the original defect.
    """
    install_stub(sandbox)

    def boom(_prompt):
        raise RuntimeError("keys_in blew up")

    original, hook.keys_in = hook.keys_in, boom
    try:
        code, out = run("PPA-1125", capsys=capsys)
    finally:
        hook.keys_in = original

    assert (code, out) == (0, "")
    assert [r["reason"] for r in log_records()] == ["hook-raised"]
    assert "keys_in blew up" in log_records()[0]["error"]


def test_a_success_writes_a_log_line_naming_the_keys(sandbox, capsys):
    """PPA-1548 - the named test. A success is an outcome and leaves a record.

    This case asserted the opposite until 22-SEP-2026, on the reasoning that a
    log growing on every prompt is a log nobody greps. PPA-1543 measured what
    that bought: a successful transition wrote to the per-session cache and
    nothing else, so PPA-1538 and PPA-1543 sitting at To Do could not be told
    apart from a hook that never fired. The volume is the price and the reason
    is greppable, so a reader after failures greps the reasons that are
    failures.

    Silent to the operator is unchanged - the record is a log line, not a
    warning, so stdout stays empty.
    """
    install_stub(sandbox)

    code, out = run("PPA-1125", capsys=capsys)

    assert (code, out) == (0, "")
    record, = log_records()
    assert record["reason"] == "transitioned"
    assert record["keys"] == ["PPA-1125"]
    assert record["target"] == "In Progress"
    assert record["exit_code"] == 0
    assert any("PPA-1125" in line and "PASS" in line
               for line in record["verdicts"]), (
        "the record names the verdict the subprocess produced per key")


def test_a_prose_prompt_records_that_it_dispatched_nothing(sandbox, capsys):
    """PPA-1548 - the named test. The quiet path says why it was quiet.

    This is the ambiguity the ticket was opened on. A prompt whose first line
    is prose resolves no key, transitions nothing and - until now - wrote
    nothing, which is also what a hook that never ran looks like. The record
    carries the line the resolver read, so the next occurrence names its own
    cause instead of needing a code read.
    """
    install_stub(sandbox)

    code, out = run("Read the close-out first.\n\nIt is on PPA-1543.",
                    capsys=capsys)

    assert (code, out) == (0, ""), "a prose prompt is silent to the operator"
    assert fired(sandbox) == [], "and transitions nothing"
    record, = log_records()
    assert record["reason"] == "no-dispatch"
    assert record["keys"] == [], "a key in the body is mentioned, not dispatched"
    assert record["first_line"] == "Read the close-out first."


def test_a_malformed_first_line_records_the_line_that_disqualified_itself(
    sandbox, capsys
):
    """The other half of "no keys resolved" - PPA-1434's case, now recorded.

    ``dispatched_keys`` returns [] for both, and the two reasons are what
    separates a line nobody meant as a dispatch from one that was.
    """
    install_stub(sandbox)

    run(MALFORMED, capsys=capsys)

    record, = log_records()
    assert record["reason"] == "malformed-dispatch"
    assert record["keys"] == ["PPA-1424", "PPA-1425", "PPA-1426"]
    assert record["first_line"] == MALFORMED.splitlines()[0]


def test_a_dispatch_whose_keys_are_already_settled_records_that(sandbox, capsys):
    """PPA-1548 - the named test. Nothing to do is an outcome, not an absence.

    The second prompt of a session re-states the same keys and the cache
    answers for them, so no subprocess runs. Without a record that prompt is
    indistinguishable from a hook that never fired on it.
    """
    install_stub(sandbox)
    run("PPA-1125", session="settled", capsys=capsys)
    hook.SCRIPT.with_name("fired.txt").unlink()

    code, out = run("PPA-1125", session="settled", capsys=capsys)

    assert (code, out) == (0, "")
    assert fired(sandbox) == [], "the cache answered; nothing was re-fired"
    assert [r["reason"] for r in log_records()] == ["transitioned",
                                                   "already-settled"]
    assert log_records()[1]["keys"] == ["PPA-1125"]


def test_an_unwritable_log_does_not_break_the_hook(sandbox, capsys):
    """A failure to record a failure still returns 0.

    The log lives under a directory the hook creates, so it can be absent or
    read-only. Refusing to start a session over it would trade a bookkeeping
    problem for a work stoppage.
    """
    install_stub(sandbox, verdict="HALT", code=1)
    blocker = sandbox / "log"
    blocker.write_text("not a directory")

    code, out = run("PPA-1125", capsys=capsys)

    assert code == 0
    assert "PPA-1125" in json.loads(out)["systemMessage"], (
        "the warning still fires when the log cannot be written")


def test_a_missing_script_warns_and_exits_zero(sandbox, capsys):
    """The case in a repo the script was never distributed into."""
    code, out = run("PPA-1125", capsys=capsys)

    assert code == 0
    assert "no script at" in json.loads(out)["systemMessage"]


def test_pt_transition_is_read_from_the_ci_workflows_clone():
    """PPA-1662. One home (PPA-1581), so never the session's own scripts/."""
    clone = Path.home() / "Documents" / "Claude-Projects" / "peech-ci-workflows"
    assert REAL.SCRIPT == clone / "scripts" / "pt_transition.py"
    assert REAL.SCRIPT.parents[1] != REAL.REPO


def test_an_absent_clone_warns_naming_it_and_exits_zero(
        sandbox, monkeypatch, capsys):
    """PPA-1662. No clone warns and passes; it never blocks a dispatch."""
    clone = sandbox / "Documents" / "Claude-Projects" / "peech-ci-workflows"
    monkeypatch.setattr(hook, "SCRIPT", clone / "scripts" / "pt_transition.py")

    code, out = run("PPA-1125", capsys=capsys)

    assert code == 0
    message = json.loads(out)["systemMessage"]
    assert f"Clone peech-ci-workflows to {clone}" in message
    assert "PPA-1125" in message
    assert [r["reason"] for r in log_records()] == ["no-script"]


def test_a_malformed_payload_exits_zero(sandbox, capsys):
    sys.stdin = __import__("io").StringIO("not json at all")
    try:
        assert hook.main() == 0
    finally:
        sys.stdin = sys.__stdin__
    assert capsys.readouterr().out == ""


def test_the_warning_is_json_so_it_never_lands_in_model_context(sandbox, capsys):
    """Plain-text stdout from a UserPromptSubmit hook is injected as context.
    A warning belongs to the operator, so it goes out as systemMessage JSON."""
    install_stub(sandbox, verdict="HALT", code=1)

    _, out = run("PPA-1125", capsys=capsys)

    assert set(json.loads(out)) == {"systemMessage"}


# --------------------------------------------------------------------------
# Once per key per session
# --------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", ["PASS", "NOOP"])
def test_a_settled_key_is_not_fired_again_in_the_same_session(
    sandbox, capsys, verdict
):
    """The hook fires on every prompt, so a settled key must stop costing a read."""
    install_stub(sandbox, verdict=verdict)
    run("PPA-1125", capsys=capsys)
    hook.SCRIPT.with_name("fired.txt").unlink()

    code, out = run("PPA-1125\n\nstill working on it", capsys=capsys)

    assert (code, out) == (0, "")
    assert fired(sandbox) == []


def test_a_halted_key_is_retried_on_the_next_prompt(sandbox, capsys):
    """A HALT means the key did not move, so it is not settled."""
    install_stub(sandbox, verdict="HALT", code=1)
    run("PPA-1125", capsys=capsys)

    run("PPA-1125\n\nstill working on it", capsys=capsys)

    assert fired(sandbox) == ["PPA-1125"]


def test_a_different_session_does_not_inherit_the_cache(sandbox, capsys):
    install_stub(sandbox)
    run("PPA-1125", session="s1", capsys=capsys)
    hook.SCRIPT.with_name("fired.txt").unlink()

    run("PPA-1125", session="s2", capsys=capsys)

    assert fired(sandbox) == ["PPA-1125"]


def test_only_the_unsettled_keys_of_a_batch_are_refired(sandbox, capsys):
    install_stub(sandbox)
    run("PPA-1125", capsys=capsys)

    run("PPA-1125, PPA-1126", capsys=capsys)

    assert fired(sandbox) == ["PPA-1126"]


def test_settled_parsing_reads_the_scripts_real_line_shape():
    stdout = (
        "PPA-1     'To Do' -> 'In Progress' hops=1 PASS\n"
        "PPA-2     'In Progress' -> 'In Progress' hops=0 NOOP — already at target\n"
        "PPA-3     'BLOCKED' -> 'BLOCKED' hops=0 HALT — off the lifecycle ladder\n"
    )
    assert hook.settled_from(stdout) == ["PPA-1", "PPA-2"]


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------

def test_the_hook_is_wired_in_hooks_json_and_is_executable():
    """PPA-1578. One UserPromptSubmit hook, run through CLAUDE_PLUGIN_ROOT, with
    a fallback for a session where that variable is unset."""
    config = json.loads((HOOK.parent / "hooks.json").read_text())
    # PPA-1586 added the other shared hooks; tests/test_hooks_json.py pins the
    # whole registration. This asserts the one this file covers.
    assert "UserPromptSubmit" in config["hooks"]
    commands = [
        h["command"]
        for block in config["hooks"]["UserPromptSubmit"]
        for h in block["hooks"]
    ]
    assert len(commands) == 1
    assert "${CLAUDE_PLUGIN_ROOT:-}" in commands[0]
    assert "hooks/transition_on_prompt.py" in commands[0]
    assert HOOK.stat().st_mode & 0o111, "a command hook is exec'd, so it needs +x"


@pytest.mark.parametrize("plugin_root_set", [True, False])
def test_the_hooks_json_command_finds_the_hook_with_or_without_plugin_root(
        tmp_path, plugin_root_set):
    """The command string, run by a shell as Claude Code runs it. With
    CLAUDE_PLUGIN_ROOT unset it falls back to the newest cached copy under
    HOME, which is the plugin cache layout for marketplace peech-ci."""
    (command,) = [h["command"]
                  for block in json.loads((HOOK.parent / "hooks.json").read_text())
                  ["hooks"]["UserPromptSubmit"] for h in block["hooks"]]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    env["HOME"] = str(tmp_path)
    if plugin_root_set:
        env["CLAUDE_PLUGIN_ROOT"] = str(HOOK.parents[1])
    else:
        cached = (tmp_path / ".claude" / "plugins" / "cache" / "peech-ci"
                  / "pt-automation-hooks" / "0.1.0" / "hooks")
        cached.mkdir(parents=True)
        # The sibling it imports the clone path from ships beside it (PPA-1662).
        for name in ("transition_on_prompt.py", "refresh_ci_workflows.py"):
            (cached / name).write_text((HOOK.parent / name).read_text())
    proc = subprocess.run(["sh", "-c", command], input="{}", capture_output=True,
                          text=True, env=env)
    assert (proc.returncode, proc.stdout) == (0, "")
    assert (tmp_path / ".claude" / "pt-transition-hook.log").is_file(), (
        "the hook ran and wrote its no-dispatch record")


def test_the_hooks_json_command_warns_and_allows_when_no_copy_is_found(tmp_path):
    (command,) = [h["command"]
                  for block in json.loads((HOOK.parent / "hooks.json").read_text())
                  ["hooks"]["UserPromptSubmit"] for h in block["hooks"]]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    env["HOME"] = str(tmp_path)
    proc = subprocess.run(["sh", "-c", command], input="{}", capture_output=True,
                          text=True, env=env)
    assert proc.returncode == 0
    assert "CLAUDE_PLUGIN_ROOT is unset" in json.loads(proc.stdout)["systemMessage"]


def test_the_hook_runs_as_a_subprocess_with_an_empty_payload(tmp_path):
    """The shape Claude Code actually invokes: exec the file, feed it stdin.

    PPA-1573. A monkeypatched LOG does not cross into a child process, so this
    case appended a no-dispatch record to the operator's live log on every run.
    HOME is what LOG resolves against, so the child gets a throwaway one.
    """
    proc = subprocess.run([str(HOOK)], input="{}", capture_output=True, text=True,
                          env={**os.environ, "HOME": str(tmp_path)})
    assert (proc.returncode, proc.stdout) == (0, "")
    assert (tmp_path / ".claude" / "pt-transition-hook.log").is_file(), (
        "the child's record lands under the throwaway HOME")


@pytest.mark.parametrize(
    ("label", "verdict", "code"),
    [
        ("success", "PASS", 0),
        ("noop", "NOOP", 0),
        ("halt", "HALT", 1),
    ],
)
def test_every_subprocess_outcome_returns_zero(sandbox, capsys, label, verdict, code):
    """PPA-1262 — the transition returns 0 on every path, asserted not assumed.

    Exit 2 is the only code that blocks a UserPromptSubmit hook, and no
    transition outcome may produce one. The logging added under PPA-1262
    introduced new failure paths, so the property is pinned per outcome
    instead of resting on the two cases that happened to be covered.

    PPA-1418 added the one thing in the file that can exit 2, and it sits
    ahead of this code rather than in it. The sandbox leaves the backlog
    empty, so nothing blocks and what is measured here is still the
    transition half alone.
    """
    install_stub(sandbox, verdict=verdict, code=code)

    assert run(f"PPA-1125\n\noutcome under test: {label}", capsys=capsys)[0] == 0


def test_a_malformed_payload_is_logged_and_returns_zero(sandbox, capsys):
    """Unreadable stdin is a caught exception, so it leaves a trace too."""
    sys.stdin = __import__("io").StringIO("not json at all")
    try:
        assert hook.main() == 0
    finally:
        sys.stdin = sys.__stdin__

    assert capsys.readouterr().out == "", "nothing is injected into model context"
    assert [r["reason"] for r in log_records()] == ["unreadable-payload"]


# --------------------------------------------------------------------------
# PPA-1418 — a dispatched key is not a mentioned one
# --------------------------------------------------------------------------
#
# At 21:22 EDT on 12-SEP-2026 a dispatch carrying PPA-1413 and PPA-1417 cited
# PPA-1407 once in its prose. At 21:23:33 PPA-1407 moved Reopened to In
# Progress, with no session working it. The regex matched a citation.

DISPATCH = (
    "PPA-1413, PPA-1417\n"
    "\n"
    "PPA-1413's halt is cleared. PPA-1417 carries the measurements it rests\n"
    "on in PPA-1407's rejection comment of 12-SEP-2026.\n"
)


def test_only_the_leading_key_line_is_dispatched(sandbox, capsys):
    """The founding case, replayed verbatim. PPA-1407 is cited and not moved."""
    install_stub(sandbox)

    run(DISPATCH, capsys=capsys)

    assert fired(sandbox) == ["PPA-1413", "PPA-1417"]
    assert "PPA-1407" not in fired(sandbox)


def test_the_mentioned_set_still_sees_every_key_in_the_prompt():
    """Both readings survive; only what each one drives has changed."""
    assert hook.keys_in(DISPATCH) == ["PPA-1413", "PPA-1417", "PPA-1407"]
    assert hook.dispatched_keys(DISPATCH) == ["PPA-1413", "PPA-1417"]


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("PPA-1416", ["PPA-1416"]),
        ("PPA-1416, PPA-1418, PPA-1407", ["PPA-1416", "PPA-1418", "PPA-1407"]),
        ("ppa-1416, ppa-1418", ["PPA-1416", "PPA-1418"]),
        ("PPA-1416 PPA-1418", ["PPA-1416", "PPA-1418"]),
        ("PPA-1416, PPA-1418.", ["PPA-1416", "PPA-1418"]),
        ("\n\n  PPA-1416  \n\nthen the prose", ["PPA-1416"]),
        # Prose on the leading line. Not a dispatch, however many keys follow.
        ("start PPA-1416", []),
        ("run the tests\n\nPPA-1416, PPA-1418", []),
        ("PPA-1416 in peech-pmo-automation", []),
        ("do not touch PPA-900", []),
        ("", []),
        ("no keys at all", []),
    ],
)
def test_what_counts_as_the_sanctioned_position(prompt, expected):
    assert hook.dispatched_keys(prompt) == expected


# --------------------------------------------------------------------------
# A pasted dispatch arrives wrapped - PPA-1573
#
# Claude Code delivers a pasted multi-line block inside a pasted_content tag,
# and the first-line rule read the tag. Measured 22-SEP-2026 in
# ~/.claude/pt-transition-hook.log, a four-key dispatch resolving nothing:
#
#   {"at": "2026-09-22T20:49:19-04:00", "reason": "no-dispatch", "keys": [],
#    "first_line": "<pasted_content id=\"c505\">"}

PASTED = (
    '<pasted_content id="c505">\n'
    "PPA-1566, PPA-1539, PPA-1136, PPA-997\n"
    "PPA-1566 carries an amendment comment that governs.\n"
    '</pasted_content id="c505">'
)


def test_a_pasted_dispatch_resolves_the_key_line_under_its_wrapper():
    assert hook.dispatched_keys(PASTED) == [
        "PPA-1566", "PPA-1539", "PPA-1136", "PPA-997"]


def test_a_pasted_prose_line_under_the_wrapper_still_resolves_nothing():
    """The wrapper is removed and nothing else relaxes: the line beneath it is
    judged exactly as a bare first line would be."""
    prompt = ('<pasted_content id="c505">\nRead the close-out first.\n'
              "PPA-1566, PPA-1539\n</pasted_content id=\"c505\">")
    assert hook.dispatched_keys(prompt) == []
    assert hook.first_nonblank_line(prompt) == "Read the close-out first."


def test_all_three_readers_see_the_line_under_the_wrapper():
    """A wrapped malformed dispatch warns, as the same line unwrapped does."""
    prompt = '<pasted_content id="c505">\nWork PPA-1 today.\n</pasted_content>'
    assert hook.first_nonblank_line(prompt) == "Work PPA-1 today."
    assert "PPA-1" in (hook.malformed_dispatch_warning(prompt) or "")


# --------------------------------------------------------------------------
# PPA-1418 — an incomplete dispatch is blocked
# --------------------------------------------------------------------------
#
# The five cases the ticket names, in its own order, then the block message and
# the repository derivation.


def backlog(sandbox, monkeypatch, *keys, repo="REPO: peech-skills"):
    monkeypatch.setattr(hook, "repo_components_of",
                        lambda ks, **kw: dict.fromkeys(ks, repo))
    monkeypatch.setattr(hook, "dispatchable_set", lambda component, **kw: list(keys))


def test_a_prompt_naming_the_complete_set_passes(sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    backlog(sandbox, monkeypatch, "PPA-1416", "PPA-1418")

    code, _ = run("PPA-1416, PPA-1418", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1416", "PPA-1418"]


def test_a_prompt_missing_one_key_blocks(sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    backlog(sandbox, monkeypatch, "PPA-1416", "PPA-1418", "PPA-1411")

    code, out = run("PPA-1416, PPA-1418", capsys=capsys)

    assert code == 2, "an incomplete dispatch must refuse, not warn"
    assert fired(sandbox) == [], "a blocked prompt transitions nothing"
    assert out == "", "the block rides on stderr, never into model context"
    assert [r["reason"] for r in log_records()] == ["dispatch-incomplete"]


def test_a_prompt_missing_one_key_but_naming_it_passes(
    sandbox, monkeypatch, capsys
):
    """Naming the omission is the opt-out, and it must not dispatch it."""
    install_stub(sandbox)
    backlog(sandbox, monkeypatch, "PPA-1416", "PPA-1418", "PPA-1411")

    code, _ = run("PPA-1416, PPA-1418\n\nLeaving PPA-1411; it is blocked.",
                  capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1416", "PPA-1418"]
    assert "PPA-1411" not in fired(sandbox), (
        "the opt-out would otherwise cause the very transition it exists to "
        "prevent")


def test_the_opt_out_match_is_case_insensitive(sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    backlog(sandbox, monkeypatch, "PPA-1416", "PPA-1411")

    assert run("PPA-1416\n\nleaving ppa-1411 for now", capsys=capsys)[0] == 0


def test_the_comparison_folds_case_on_both_sides():
    """End to end this holds either way, because ``keys_in`` uppercases what it
    returns. It is pinned here as well so the comparison keeps its own stated
    contract rather than borrowing one from its caller."""
    assert hook.missing_from(["PPA-1411"], ["ppa-1411"]) == []
    assert hook.missing_from(["ppa-1411"], ["PPA-1411"]) == []
    assert hook.missing_from(["PPA-1411"], ["PPA-1416"]) == ["PPA-1411"]


def test_a_jira_read_failure_warns_and_allows(sandbox, monkeypatch, capsys):
    """A dispatch must not depend on Jira being up."""
    def boom(component, **kw):
        raise OSError("connection reset by peer")

    install_stub(sandbox)
    monkeypatch.setattr(hook, "dispatchable_set", boom)

    code, out = run("PPA-1416", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1416"]
    assert "not checked" in json.loads(out)["systemMessage"]
    # PPA-1548: the dispatch was allowed through and the keys moved, so the
    # success record joins the reasons the failed read already wrote.
    assert [r["reason"] for r in log_records()] == [
        "dispatchable-read-failed", "transitioned"]


def test_a_read_timeout_warns_and_allows(sandbox, monkeypatch, capsys):
    def slow(component, **kw):
        raise TimeoutError("timed out")

    install_stub(sandbox)
    monkeypatch.setattr(hook, "dispatchable_set", slow)

    assert run("PPA-1416", capsys=capsys)[0] == 0
    assert fired(sandbox) == ["PPA-1416"]


def test_a_failed_repository_read_warns_and_allows(sandbox, monkeypatch, capsys):
    """The repository read is a Jira call too, and it fails the same way.

    The mismatch check and the completeness check both resolve components
    through ``repo_components_of``, so one outage is logged by each of them
    under its own reason. Both warn and allow, which is what this case is about.
    """
    def boom(keys, **kw):
        raise OSError("no route to host")

    install_stub(sandbox)
    monkeypatch.setattr(hook, "repo_components_of", boom)

    assert run("PPA-1416", capsys=capsys)[0] == 0
    assert fired(sandbox) == ["PPA-1416"]
    # The mismatch check reaches this function first and warns-and-allows on
    # the same failure, then the completeness check reaches it. Each is
    # recorded rather than one swallowing the other, because they are two
    # checks that did not run, and they are recorded in the order the dispatch
    # runs them. PPA-1662 removed the retired cross-repository check's third.
    # PPA-1548: the dispatch was allowed through and the keys moved, so the
    # success record joins the reasons the failed read already wrote.
    assert [r["reason"] for r in log_records()] == [
        "repo-match-read-failed", "repo-scope-read-failed", "transitioned"]


def test_a_prompt_naming_no_ppa_key_never_reaches_the_check(
    sandbox, monkeypatch, capsys
):
    """Proved by a test rather than by reading the code: the new path is not
    entered at all, so a prompt with no key cannot be blocked by a backlog it
    was never compared against."""
    reached = []

    def record(component, **kw):
        reached.append(component)
        return ["PPA-1411"]

    install_stub(sandbox)
    monkeypatch.setattr(hook, "dispatchable_set", record)

    code, out = run("run the tests and report back", capsys=capsys)

    assert (code, out) == (0, "")
    assert reached == [], "the dispatchable set was read for a non-dispatch"
    assert fired(sandbox) == []


def test_a_prose_prompt_citing_a_key_is_not_checked_either(
    sandbox, monkeypatch, capsys
):
    """Constraint from PPA-1418's amendment: a prompt naming no key in the
    sanctioned position transitions nothing and blocks nothing."""
    install_stub(sandbox)
    backlog(sandbox, monkeypatch, "PPA-1411")

    assert run("what is the status of PPA-1407?", capsys=capsys)[0] == 0
    assert fired(sandbox) == []


def test_the_block_message_names_the_missing_keys_and_the_opt_out():
    message = hook.block_message(["PPA-1411", "PPA-1420"],
                                 "REPO: peech-pmo-automation")

    assert "PPA-1411" in message and "PPA-1420" in message
    assert "REPO: peech-pmo-automation" in message
    assert "opt-out" in message or "naming a key" in message
    assert "PPA-1418" not in message, (
        "a conductor must be able to act on the block without opening the "
        "ticket that produced it")


# --------------------------------------------------------------------------
# PPA-1716 - the set is measured against the dispatch's own work type
# --------------------------------------------------------------------------
#
# Ruling 1A, 29-SEP-2026: Discovery tickets run in their own Opus session and
# Delegated tickets on Sonnet, so a dispatch of one type is not incomplete for
# lacking the other's keys, and a line naming both is refused.

DELEGATED = ["EXA: Delegated", "REPO: peech-skills"]
DISCOVERY = ["EXA: Delegated Discovery", "REPO: peech-skills"]

#: Two of each type, all open in one repository.
TYPED = {"PPA-11": DELEGATED, "PPA-12": DELEGATED,
         "PPA-21": DISCOVERY, "PPA-22": DISCOVERY}


def typed_backlog(monkeypatch):
    """Serve TYPED through the real readers, so the JQL that narrows the set is
    the JQL under test: whichever component clause the query carries decides
    which keys the stubbed Jira hands back."""
    def fake_get(path, timeout=None):
        jql = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)["jql"][0]
        if jql.startswith("key in"):
            return {"issues": [{"key": k, "fields": {
                "status": {"name": "To Do"},
                "components": [{"name": n} for n in TYPED[k]]}}
                for k in re.findall(r"PPA-\d+", jql)]}
        if 'component = "EXA: Delegated Discovery"' in jql:
            keys = ["PPA-21", "PPA-22"]
        elif 'component = "EXA: Delegated"' in jql:
            keys = ["PPA-11", "PPA-12"]
        else:
            keys = list(TYPED)
        return {"issues": [{"key": k, "fields": {"issuelinks": []}}
                           for k in keys]}

    for module in (hook, REAL):
        monkeypatch.setattr(module, "_jira_get", fake_get)
    for name in ("repo_components_of", "work_types_of", "dispatchable_set",
                 "dispatched_fields"):
        monkeypatch.setattr(hook, name, getattr(REAL, name))


def test_a_discovery_only_dispatch_is_not_refused_for_omitted_delegated_keys(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    typed_backlog(monkeypatch)

    code, _ = run("PPA-21, PPA-22", capsys=capsys)

    assert code == 0, "Delegated keys were demanded of a Discovery dispatch"
    assert fired(sandbox) == ["PPA-21", "PPA-22"]


def test_a_delegated_only_dispatch_is_not_refused_for_omitted_discovery_keys(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    typed_backlog(monkeypatch)

    code, _ = run("PPA-11, PPA-12", capsys=capsys)

    assert code == 0, "Discovery keys were demanded of a Delegated dispatch"
    assert fired(sandbox) == ["PPA-11", "PPA-12"]


def test_a_dispatch_missing_a_key_of_its_own_type_is_still_refused(
        sandbox, monkeypatch, capsys):
    """The check is narrowed, not removed, and the refusal says which set it
    measured, since the other type's keys are deliberately not in it."""
    install_stub(sandbox)
    typed_backlog(monkeypatch)

    code, _ = run("PPA-21", capsys=capsys)
    message = REAL.check_dispatch_complete("PPA-21", ["PPA-21"])

    assert code == 2 and fired(sandbox) == []
    assert "named nowhere in this prompt: PPA-22" in message
    assert "PPA-11" not in message and "PPA-12" not in message
    assert "Discovery tickets" in message


def test_naming_an_omitted_key_of_its_own_type_is_still_the_opt_out(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    typed_backlog(monkeypatch)

    code, _ = run("PPA-21\n\nLeaving PPA-22; it is blocked.", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-21"]


def test_a_leading_line_mixing_both_types_is_refused_with_the_split_named(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    typed_backlog(monkeypatch)

    code, _ = run("PPA-11, PPA-21", capsys=capsys)
    message = REAL.check_dispatch_complete("PPA-11, PPA-21", ["PPA-11", "PPA-21"])

    assert code == 2, "a mixed dispatch must refuse, not warn"
    assert fired(sandbox) == [], "a refused prompt transitions nothing"
    assert [r["reason"] for r in log_records()] == ["dispatch-mixed-work-types"]
    assert "claude --model opus --effort high" in message
    delegated_half, discovery_half = [
        line for line in message.splitlines() if line.startswith(
            ("Delegated", "Discovery"))]
    assert "PPA-11" in delegated_half and "PPA-21" not in delegated_half
    assert "PPA-21" in discovery_half and "PPA-11" not in discovery_half
    assert "claude --model opus --effort high" in discovery_half


def test_naming_every_key_does_not_clear_a_mixed_line(
        sandbox, monkeypatch, capsys):
    """The refusal has no opt-out: a completeness refusal clears by naming a
    key, and naming one here would put it in the wrong session."""
    install_stub(sandbox)
    typed_backlog(monkeypatch)

    code, _ = run("PPA-11, PPA-21\n\nPPA-12 and PPA-22 wait.", capsys=capsys)

    assert code == 2
    assert fired(sandbox) == []


def test_the_set_is_narrowed_in_the_query_and_a_ticket_with_both_is_discovery():
    delegated = REAL.dispatchable_jql("REPO: peech-skills", "Delegated")
    discovery = REAL.dispatchable_jql("REPO: peech-skills", "Discovery")
    both = REAL.dispatchable_jql("REPO: peech-skills")

    assert 'component = "EXA: Delegated"' in delegated
    assert 'component != "EXA: Delegated Discovery"' in delegated
    assert 'component = "EXA: Delegated Discovery"' in discovery
    assert "component in (" in both and "!=" not in both
    assert REAL.work_type_of(["EXA: Delegated", "EXA: Delegated Discovery"]) == (
        "Discovery")
    assert REAL.work_type_of(["EXA: Delegated"]) == "Delegated"
    assert REAL.work_type_of(["REPO: peech-skills"]) is None


def test_a_key_with_no_execution_component_has_no_type():
    """It must not decide which backlog the rest is measured against; the Bar
    check refuses it."""
    fields = {"PPA-31": {"components": ["REPO: peech-skills"]},
              "PPA-21": {"components": DISCOVERY}}

    assert REAL.work_types_of(["PPA-31", "PPA-21", "PPA-99"], fields=fields) == {
        "Discovery": ["PPA-21"]}


def test_the_dispatch_set_listing_shows_each_keys_work_type(monkeypatch):
    def fake_get(path, timeout=None):
        if "issuelinks" in path:
            return {"issues": [{"key": k, "fields": {"issuelinks": []}}
                               for k in ("PPA-11", "PPA-21")]}
        return {"issues": [{"key": k, "fields": {
            "status": {"name": "To Do"},
            "components": [{"name": n} for n in TYPED[k]],
            "description": adf("## Scope boundary\nOne file."),
            "customfield_10767": adf("[machine] One condition.")}}
            for k in ("PPA-11", "PPA-21")]}

    monkeypatch.setattr(REAL, "_jira_get", fake_get)

    assert REAL.dispatch_set_lines("peech-skills") == [
        "PPA-11\tTo Do\tDelegated\tPASS",
        "PPA-21\tTo Do\tDiscovery\tPASS",
    ]


# --------------------------------------------------------------------------
# PPA-1419 — the repository comes from the tickets, never from the checkout
# --------------------------------------------------------------------------
#
# PPA-1418 derived it from the working directory. Minutes after that merged, a
# dispatch of three peech-skills tickets was refused for being incomplete
# against REPO: peech-pmo-automation, naming two keys that belong to neither the
# dispatch nor the repository it was for.


def test_the_repository_comes_from_the_dispatched_tickets():
    scope = hook.scope_of({"PPA-1419": "REPO: peech-skills",
                           "PPA-1420": "REPO: peech-skills"})
    assert scope.component == "REPO: peech-skills"
    assert scope.blocked is None and scope.unscoped == []


def test_the_working_directory_is_not_an_input():
    """The founding case. A session rooted in peech-pmo-automation dispatching
    peech-skills tickets measures against peech-skills."""
    assert not hasattr(hook, "repo_component"), (
        "the working-directory derivation is still reachable")
    scope = hook.scope_of(dict.fromkeys(("PPA-1419", "PPA-1420", "PPA-1421"), "REPO: peech-skills"))
    assert scope.component == "REPO: peech-skills"


def test_keys_disagreeing_block_and_name_both_repositories(
    sandbox, monkeypatch, capsys
):
    """A dispatch spanning two remotes is the command being wrong. It does not
    pick one repository and measure against it."""
    install_stub(sandbox)
    monkeypatch.setattr(hook, "repo_components_of", lambda keys, **kw: {
        "PPA-1419": "REPO: peech-skills",
        "PPA-1422": "REPO: peech-pmo-automation"})

    code, out = run("PPA-1419, PPA-1422", capsys=capsys)

    assert code == 2
    assert fired(sandbox) == [], "a blocked prompt transitions nothing"
    assert out == "", "the block rides on stderr, never into model context"
    assert [r["reason"] for r in log_records()] == ["dispatch-spans-repositories"]


def test_the_spanning_block_message_names_both_and_picks_neither():
    message = hook.scope_of({"a": "REPO: peech-skills",
                             "b": "REPO: peech-pmo-automation"}).blocked
    assert "REPO: peech-skills" in message
    assert "REPO: peech-pmo-automation" in message
    assert "does not pick one" in message
    assert "one dispatch per repository" in message


def test_an_unscoped_key_is_named_never_silently_excluded(
    sandbox, monkeypatch, capsys
):
    """The repository still resolves from the keys that carry one, and the key
    that does not is reported."""
    install_stub(sandbox)
    monkeypatch.setattr(hook, "repo_components_of", lambda keys, **kw: {
        "PPA-1419": "REPO: peech-skills", "PPA-1999": None})
    monkeypatch.setattr(hook, "dispatchable_set", lambda component, **kw: [])

    code, out = run("PPA-1419, PPA-1999", capsys=capsys)

    assert code == 0
    assert "PPA-1999" in json.loads(out)["systemMessage"]
    assert "no REPO: component" in json.loads(out)["systemMessage"]
    # PPA-1548: the dispatch was allowed through and the keys moved, so the
    # success record joins the reasons the failed read already wrote.
    assert [r["reason"] for r in log_records()] == [
        "unscoped-keys", "transitioned"]


def test_no_key_carrying_a_repository_warns_and_allows(
    sandbox, monkeypatch, capsys
):
    """The check cannot derive a backlog, so it does not block on its own
    inability - the same trade every other unreadable path makes."""
    install_stub(sandbox)
    monkeypatch.setattr(hook, "repo_components_of",
                        lambda keys, **kw: dict.fromkeys(keys))
    reached = []
    monkeypatch.setattr(hook, "dispatchable_set",
                        lambda c, **kw: reached.append(c) or [])

    code, _ = run("PPA-1419", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1419"]
    assert reached == [], "no backlog should have been queried"


def test_the_repository_read_is_one_search_for_the_dispatched_keys(monkeypatch):
    """One search for the dispatched keys, not one read per key.

    It asked for ``components`` alone until PPA-1465 merged the three reads
    into one; it now asks for every field the three checks need between them,
    and the repository derivation takes its part out of the same answer.
    """
    seen = {}

    def fake_get(path, timeout=None):
        seen["path"] = path
        return {"issues": [{"key": "PPA-1419", "fields": {"components": [
            {"name": "EXA: Delegated"}, {"name": "REPO: peech-skills"}]}}]}

    monkeypatch.setattr(hook, "_jira_get", fake_get)
    mapping = hook.repo_components_of(["PPA-1419"])

    assert mapping == {"PPA-1419": "REPO: peech-skills"}
    assert "components" in seen["path"]
    assert "key+in" in seen["path"] or "key%20in" in seen["path"]


def test_a_key_jira_does_not_return_is_unscoped_not_assumed(monkeypatch):
    monkeypatch.setattr(hook, "_jira_get", lambda path, timeout=None: {"issues": []})
    assert hook.repo_components_of(["PPA-9999"]) == {"PPA-9999": None}


def test_the_dispatchable_set_is_defined_by_status_and_component():
    jql = hook.dispatchable_jql("REPO: peech-pmo-automation")

    assert '"To Do"' in jql and '"Reopened"' in jql
    assert '"EXA: Delegated"' in jql and '"EXA: Delegated Discovery"' in jql
    assert 'component = "REPO: peech-pmo-automation"' in jql
    assert "project = PPA" in jql


# --------------------------------------------------------------------------
# The Ticket Quality Bar, mechanical half — PPA-1427
#
# The nine cases the ticket names, in its own order, then the block message,
# the item definition, and the two judgement items it deliberately omits.


def bar(monkeypatch, **per_key):
    """Point bar_fields_of() at a fixture set keyed by ticket key."""
    monkeypatch.setattr(hook, "bar_fields_of", lambda keys, **kw: dict(per_key))


def test_a_dispatch_naming_a_key_with_two_repo_components_is_refused(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields(
        repo_components=["REPO: peech-skills", "REPO: peech-org-skills"])})
    code, _ = run("PPA-1")
    err = capsys.readouterr().err
    assert code == 2
    assert "PPA-1" in err and "exactly one REPO component" in err
    assert fired(sandbox) == []


def test_a_dispatch_naming_a_key_with_no_execution_component_is_refused(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields(components=["REPO: peech-skills"])})
    code, _ = run("PPA-1")
    assert code == 2
    assert "an execution component" in capsys.readouterr().err
    assert fired(sandbox) == []


@pytest.mark.parametrize("description", [
    "## Scope boundary\nEdits one file and nothing else.",
    "Skills to load and apply: [pt-dashboard-standards]\n\n"
    "## Scope boundary\nEdits one file and nothing else.",
], ids=["no skills line", "a skill outside the old default four"])
def test_a_dispatch_is_not_refused_on_its_skills_line(
        sandbox, monkeypatch, capsys, description):
    """PPA-1684, ruling 1A: skills load on their own descriptions, so neither
    an absent line nor one naming other skills is a reason to refuse."""
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields(description=description)})
    code, _ = run("PPA-1", capsys=capsys)
    assert code == 0
    assert fired(sandbox) == ["PPA-1"]


def test_a_dispatch_naming_a_key_with_no_scope_boundary_is_refused(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields(
        description="Skills to load and apply: [pt-backlog]")})
    code, _ = run("PPA-1")
    assert code == 2
    assert "a scope boundary" in capsys.readouterr().err
    assert fired(sandbox) == []


def test_a_dispatch_naming_a_key_with_an_empty_definition_of_done_is_refused(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields(dod="   ")})
    code, _ = run("PPA-1")
    assert code == 2
    assert "a non-empty Definition of Done" in capsys.readouterr().err
    assert fired(sandbox) == []


def test_a_dispatch_passing_every_mechanical_item_is_allowed(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields()})
    code, _ = run("PPA-1", capsys=capsys)
    assert code == 0
    assert fired(sandbox) == ["PPA-1"]


def test_the_opt_out_clears_a_bar_refusal_as_it_clears_a_completeness_refusal(
        sandbox, monkeypatch, capsys):
    """A second mention, in prose, waives the Bar exactly as it waives
    completeness. The dispatch-line mention cannot: it is what put the key in
    scope."""
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields(dod="")})

    code, _ = run("PPA-1")
    assert code == 2                      # refused with no opt-out
    capsys.readouterr()

    code, _ = run("PPA-1\n\nPPA-1 has no DoD yet; dispatching anyway.",
                  session="s2", capsys=capsys)
    assert code == 0
    assert fired(sandbox) == ["PPA-1"]


def test_a_jira_read_failure_during_the_bar_check_warns_and_allows(
        sandbox, monkeypatch, capsys):
    install_stub(sandbox)

    def boom(keys, **kw):
        raise TimeoutError("jira is slow")

    monkeypatch.setattr(hook, "bar_fields_of", boom)
    code, out = run("PPA-1", capsys=capsys)
    assert code == 0
    assert "Ticket Quality Bar not checked" in out
    assert fired(sandbox) == ["PPA-1"]
    # PPA-1548: the dispatch was allowed through and the keys moved, so the
    # success record joins the reasons the failed read already wrote.
    assert [r["reason"] for r in log_records()] == [
        "bar-read-failed", "transitioned"]


def test_a_settled_key_whose_live_status_is_reopened_is_transitioned(
        sandbox, monkeypatch, capsys):
    """The PPA-1407 case: cached as settled, rejected to Reopened outside the
    session, and skipped by a cache that had no way to know."""
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1407": bar_fields(status="In Progress")})
    run("PPA-1407", capsys=capsys)
    assert fired(sandbox) == ["PPA-1407"]          # cached settled by this run
    # The stub's record has to go, or the second assertion reads the first
    # run's write and passes whether or not the key fired again.
    hook.SCRIPT.with_name("fired.txt").unlink()

    bar(monkeypatch, **{"PPA-1407": bar_fields(status="Reopened")})
    code, _ = run("PPA-1407", capsys=capsys)
    assert code == 0
    assert fired(sandbox) == ["PPA-1407"]          # fired again, not skipped


def test_a_settled_key_whose_live_status_is_in_progress_is_still_skipped(
        sandbox, monkeypatch, capsys):
    """The cache still does the job it was built for."""
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": bar_fields(status="In Progress")})
    run("PPA-1", capsys=capsys)
    hook.SCRIPT.with_name("fired.txt").unlink()

    code, _ = run("PPA-1", capsys=capsys)
    assert code == 0
    assert fired(sandbox) == []


def test_the_bar_block_message_names_each_key_and_its_failing_items():
    message = hook.bar_block_message(
        {"PPA-1": ["a scope boundary"],
         "PPA-2": ["exactly one REPO component", "an execution component"]})
    assert "PPA-1 - missing a scope boundary" in message
    assert "PPA-2 - missing exactly one REPO component, an execution component" \
        in message
    assert "opt-out" in message


def test_the_bar_block_message_names_no_ticket_key_of_its_own():
    """A conductor acts on the refusal without opening the ticket that shipped
    it, so the message carries the failing keys and no other."""
    message = hook.bar_block_message({"PPA-1": ["a scope boundary"]})
    assert hook.keys_in(message) == ["PPA-1"]


def test_the_mechanical_bar_items_are_defined_as_a_list():
    """Five items since PPA-1684 retired the skills line. The last one's label
    is a callable rather than a string, because which bar a Definition of Done
    tripped is the part the conductor acts on and a fixed label cannot carry
    it."""
    labels = [label for label, _ in hook.BAR_ITEMS]

    assert labels[:4] == [
        "exactly one REPO component",
        "an execution component",
        "a scope boundary",
        "a non-empty Definition of Done",
    ]
    assert callable(labels[4])
    assert len(labels) == 5


def test_the_two_judgement_items_are_named_out_of_scope_in_the_source():
    """They are not approximated by a heuristic, and the reason is recorded
    where the items are defined rather than only in the ticket."""
    source = HOOK.read_text()
    assert "self-contained" in source
    assert "contradiction" in source


@pytest.mark.parametrize("phrasing", [
    "## Scope boundary\nEdits one file.",
    "## Out of scope\nThe Jira workflow.",
    "Edits transition_on_prompt.py and nothing else.",
    "Does not edit scripts/pt_transition.py.",
    "Class exclusion: other hook defects are reported, not fixed.",
])
def test_a_scope_boundary_is_recognised_however_it_is_phrased(phrasing):
    """Read off the four tickets live on 16-SEP-2026 rather than invented:
    matching the section heading alone would refuse PPA-1427's own boundary."""
    fields = bar_fields(description="Skills to load and apply: [x]\n" + phrasing)
    assert hook.bar_failures(fields) == []


def test_a_key_jira_does_not_return_is_not_treated_as_failing(
        sandbox, monkeypatch, capsys):
    """No answer and a bad ticket are different things; only the second
    refuses."""
    install_stub(sandbox)
    monkeypatch.setattr(hook, "bar_fields_of", lambda keys, **kw: {})
    code, _ = run("PPA-1", capsys=capsys)
    assert code == 0
    assert fired(sandbox) == ["PPA-1"]


def test_the_bar_read_asks_for_the_fields_the_items_need(monkeypatch):
    seen = {}

    def fake_get(path, timeout=None):
        seen["path"] = path
        return {"issues": []}

    monkeypatch.setattr(hook, "_jira_get", fake_get)
    hook.bar_fields_of(["PPA-1"])
    for field in ("status", "components", "description", "customfield_10767"):
        assert field in seen["path"]


def test_the_opt_out_ignores_the_dispatch_line_itself():
    assert hook.mentioned_beyond_dispatch_line("PPA-1, PPA-2") == set()
    assert hook.mentioned_beyond_dispatch_line(
        "PPA-1, PPA-2\n\nPPA-2 is going ahead anyway.") == {"PPA-2"}


def test_flatten_adf_pulls_every_text_run_out_of_the_node_tree():
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Skills to load and apply:"},
            {"type": "text", "text": " [pt-backlog]"}]},
        {"type": "heading", "content": [{"type": "text", "text": "Scope boundary"}]}]}
    assert hook.flatten_adf(doc) == [
        "Skills to load and apply:", " [pt-backlog]", "Scope boundary"]


def test_flatten_adf_reads_an_absent_field_as_empty():
    assert hook.flatten_adf(None) == []


# --------------------------------------------------------------------------
# A malformed dispatch is not a silent one — PPA-1434
#
# The five cases the ticket names, in its own order.

MALFORMED = "Work PPA-1424, PPA-1425 and PPA-1426."


def test_a_first_line_of_keys_and_separators_dispatches(sandbox, capsys):
    """The qualifying form, unchanged."""
    install_stub(sandbox)
    code, _ = run("PPA-1424, PPA-1425", capsys=capsys)
    assert code == 0
    assert fired(sandbox) == ["PPA-1424", "PPA-1425"]


def test_work_and_prose_around_keys_warns_and_transitions_nothing(
        sandbox, capsys):
    """PPA-1548 moved the sink: the warning is systemMessage, not stderr.

    stderr from a hook exiting 0 reaches the debug log only, so this warning
    was invisible to the operator it was written for. Everything else the case
    asserts - exit 0, nothing fired - is unchanged.
    """
    install_stub(sandbox)
    code, out = run(MALFORMED, capsys=capsys)
    assert code == 0
    assert fired(sandbox) == []
    assert json.loads(out)["systemMessage"].count("nothing was dispatched") == 1


def test_the_warning_names_the_keys_and_the_residue(sandbox, capsys):
    install_stub(sandbox)
    _code, out = run(MALFORMED, capsys=capsys)
    err = json.loads(out)["systemMessage"]
    # PPA-1470 Amendment 1. The keys half was asserted against the whole
    # message, and the message names the keys twice - once in the opening
    # sentence and again in the "make the first line" remedy. Deleting the
    # opening sentence's list left this green, so the assertion was carried by
    # the remedy and the half it was written for was untested. It is pinned to
    # the first sentence now, which is where a reader meets the keys.
    first_sentence = err.split("\n\n")[0]
    assert "PPA-1424, PPA-1425, PPA-1426" in first_sentence   # the keys found
    # The residue verbatim. The keys are removed and the allowed separators are
    # stripped from the ends only, so the spacing the removed keys left behind
    # survives in the middle - the ticket's trace collapses it for legibility,
    # and the warning does not, because this is what actually disqualified the
    # line.
    assert "'Work ,  and'" in err
    assert "make the first line: PPA-1424, PPA-1425, PPA-1426" in err


def test_a_first_line_with_no_keys_stays_silent(sandbox, capsys):
    """The deliberate quiet path PPA-1418 shipped. No warning is added."""
    install_stub(sandbox)
    code, out = run("Please summarise what changed yesterday.")
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out == ""
    assert fired(sandbox) == []


def test_the_warning_never_blocks(sandbox, capsys):
    """Exit 0, and no call into pt_transition.py."""
    install_stub(sandbox)
    code, _ = run(MALFORMED)
    capsys.readouterr()
    assert code == 0
    assert not hook.SCRIPT.with_name("fired.txt").exists()


def test_the_residue_and_the_qualifier_read_one_separator_set():
    """A second literal would let the warning describe a rule the qualifier no
    longer applies."""
    line = "PPA-1 & PPA-2;"
    assert hook.dispatched_keys(line) == ["PPA-1", "PPA-2"]
    assert hook.malformed_dispatch_warning(line) is None


def test_the_warning_reads_the_same_line_the_qualifier_reads():
    """First non-blank, never further down — the two can never disagree about
    which line is under test."""
    prompt = "\n\nWork PPA-1 today.\nPPA-2, PPA-3"
    assert hook.dispatched_keys(prompt) == []
    assert "PPA-1" in hook.malformed_dispatch_warning(prompt)
    assert "PPA-2" not in hook.malformed_dispatch_warning(prompt)


def test_a_qualifying_line_produces_no_warning():
    assert hook.malformed_dispatch_warning("PPA-1, PPA-2.") is None


def test_an_empty_prompt_produces_no_warning():
    assert hook.malformed_dispatch_warning("") is None
    assert hook.malformed_dispatch_warning(None) is None


# --------------------------------------------------------------------------
# The repository mismatch refusal, and the blocked-ticket exclusion — PPA-1465
#
# On 16-SEP-2026 a dispatch whose tickets targeted one repository was pasted
# into a session rooted in another, and the two sessions collided in one
# working tree. PPA-1460 made the target visible in the label; it could not
# refuse the paste. This is the refusal, plus the exclusion that stops a
# blocked ticket being demanded by the check beside it.
# --------------------------------------------------------------------------

def rooted_in(monkeypatch, tmp_path, name):
    """Root the session in a directory named for `name`, as Claude Code does."""
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


def test_a_dispatch_for_another_repository_is_refused(
        sandbox, monkeypatch, capsys):
    """The founding case. The tickets are peech-skills; the session is rooted in
    peech-pmo-automation, which is the paste that collided."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-pmo-automation")

    code, out = run("PPA-1416, PPA-1418", capsys=capsys)

    assert code == 2
    assert fired(sandbox) == [], "a refused prompt transitions nothing"
    assert out == "", "the refusal rides on stderr, never into model context"
    assert [r["reason"] for r in log_records()] == [
        "dispatch-for-another-repository"]


def test_the_refusal_names_both_repositories_and_every_mismatched_key():
    """Readable without opening the ticket that shipped it."""
    message = hook.mismatch_block_message(
        [("PPA-1416", "peech-skills"), ("PPA-1418", "peech-skills")],
        "peech-pmo-automation")

    assert "PPA-1416" in message and "PPA-1418" in message
    assert "peech-skills" in message, "the repository the tickets name"
    assert "peech-pmo-automation" in message, "the repository this session is in"
    assert "no opt-out" in message.lower()
    assert "PPA-1465" not in message, "it names no ticket key of its own"


def test_a_dispatch_for_this_repository_is_untouched(sandbox, monkeypatch, capsys):
    """The other half of the same rule: a matching dispatch behaves as before."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-skills")

    code, _ = run("PPA-1416, PPA-1418", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1416", "PPA-1418"]


def test_the_session_repository_comes_from_claude_project_dir(monkeypatch, tmp_path):
    """The derivation, stated. The last path segment is the repository name,
    because every checkout in the estate is cloned under its own name."""
    root = tmp_path / "peech-skills"
    root.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    assert hook.session_repository() == "peech-skills"

    assert hook.session_repository(str(root)) == "peech-skills"
    assert hook.session_repository(f"{root}/") == "peech-skills", "a trailing slash"


@pytest.mark.parametrize("value", ["", None])
def test_an_unset_project_dir_reads_as_unknown(monkeypatch, value):
    """Unset or empty is 'unknown', never a repository named '' that mismatches
    everything. The caller turns it into a warn-and-allow."""
    if value is None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", value)
    assert hook.session_repository() is None


def test_an_unreadable_project_dir_warns_and_allows(sandbox, monkeypatch, capsys):
    """Condition 6, first case. A session whose own root cannot be read does not
    get its dispatch refused over it."""
    install_stub(sandbox)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

    code, out = run("PPA-1416", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1416"]
    assert "CLAUDE_PROJECT_DIR" in json.loads(out)["systemMessage"]
    assert "session-repository-unreadable" in [r["reason"] for r in log_records()]


def test_the_refusal_has_no_opt_out(sandbox, monkeypatch, capsys):
    """Condition 3. Naming the key a second time in the prose clears a
    completeness refusal and a Bar refusal. It does not clear this one."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-pmo-automation")

    code, _ = run("PPA-1416\n\nPPA-1416 is dispatched deliberately from here.",
                  capsys=capsys)

    assert code == 2, "the second mention waives nothing"
    assert fired(sandbox) == []


def test_the_completeness_check_still_has_its_opt_out(sandbox, monkeypatch, capsys):
    """The contrast condition 3 asks for, asserted beside it rather than
    assumed: the opt-out this refusal refuses is a real, working opt-out."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-skills")
    backlog(sandbox, monkeypatch, "PPA-1416", "PPA-1418")

    code, _ = run("PPA-1416\n\nPPA-1418 is left out; it is blocked.", capsys=capsys)

    assert code == 0, "naming the omitted key in prose is the opt-out"
    assert fired(sandbox) == ["PPA-1416"]


def test_a_key_with_no_repo_component_is_not_a_mismatch(
        sandbox, monkeypatch, capsys):
    """Condition 6. It is already reported by the completeness check, and a
    ticket with no repository has not cleared the Bar. Two answers to one
    question would be one too many."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-pmo-automation")
    monkeypatch.setattr(hook, "repo_components_of",
                        lambda keys, **kw: dict.fromkeys(keys))

    code, _ = run("PPA-1416", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1416"]


def test_a_key_jira_does_not_return_is_not_a_mismatch(
        sandbox, monkeypatch, capsys):
    """Condition 6. 'No answer' is not 'belongs elsewhere'."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-pmo-automation")
    monkeypatch.setattr(hook, "repo_components_of",
                        lambda keys, **kw: dict.fromkeys(keys))

    assert run("PPA-9999", capsys=capsys)[0] == 0


@pytest.mark.parametrize(
    ("exc", "label"),
    [
        (OSError("no route to host"), "a Jira error"),
        (TimeoutError("timed out"), "a timeout"),
        (RuntimeError("no credentials"), "absent credentials"),
    ],
)
def test_every_read_failure_on_the_mismatch_path_warns_and_allows(
        sandbox, monkeypatch, capsys, exc, label):
    """Condition 6. A block fires only on a positive answer from Jira, because
    a dispatch must not depend on Jira being up."""
    def boom(keys, **kw):
        raise exc

    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-pmo-automation")
    monkeypatch.setattr(hook, "repo_components_of", boom)

    code, out = run("PPA-1416", capsys=capsys)

    assert code == 0, label
    assert fired(sandbox) == ["PPA-1416"]
    assert "repo-match-read-failed" in [r["reason"] for r in log_records()]


def test_a_spanning_dispatch_still_gets_the_spanning_refusal(
        sandbox, monkeypatch, capsys):
    """PPA-1419's refusal is not taken over. A dispatch spanning two remotes is
    the command being wrong whichever window it lands in, so that message still
    fires even when the session is rooted in one of the two."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-skills")
    monkeypatch.setattr(hook, "repo_components_of", lambda keys, **kw: {
        "PPA-1419": "REPO: peech-skills",
        "PPA-1422": "REPO: peech-pmo-automation"})

    code, _ = run("PPA-1419, PPA-1422", capsys=capsys)

    assert code == 2
    assert [r["reason"] for r in log_records()] == ["dispatch-spans-repositories"]


# ---- a blocked ticket is not dispatchable --------------------------------

def issue(key, blockers=(), blocker_status="In Progress"):
    """A search result row carrying `is blocked by` links, as Jira returns it."""
    return {"key": key, "fields": {"issuelinks": [
        {"type": {"name": "Blocks", "inward": "is blocked by",
                  "outward": "blocks"},
         "inwardIssue": {"key": b, "fields": {
             "status": {"name": blocker_status}}}}
        for b in blockers]}}


def test_a_ticket_with_an_open_blocker_is_outside_the_dispatchable_set(monkeypatch):
    """The measured case: PPA-1464 blocked by PPA-1456, which was In Progress on
    an unmerged pull request. It is never demanded and never needs an opt-out."""
    monkeypatch.setattr(hook, "_jira_get", lambda path, timeout=None: {"issues": [
        issue("PPA-1464", ["PPA-1456"]), issue("PPA-1465")]})

    excluded = []
    assert hook.dispatchable_set("REPO: x", excluded=excluded) == ["PPA-1465"]
    assert excluded == [("PPA-1464", ["PPA-1456"])]


@pytest.mark.parametrize("status", ["Done", "Closed"])
def test_a_resolved_blocker_releases_the_ticket_it_blocked(monkeypatch, status):
    """The second case condition 4 names. Once the blocker lands, the ticket is
    demanded again - the exclusion is a live read, not a property of the link."""
    monkeypatch.setattr(hook, "_jira_get", lambda path, timeout=None: {"issues": [
        issue("PPA-1464", ["PPA-1456"], blocker_status=status)]})

    excluded = []
    assert hook.dispatchable_set("REPO: x", excluded=excluded) == ["PPA-1464"]
    assert excluded == []


def test_a_ticket_with_no_links_is_unaffected(monkeypatch):
    """The third case condition 4 names."""
    monkeypatch.setattr(hook, "_jira_get", lambda path, timeout=None: {
        "issues": [{"key": "PPA-1", "fields": {}},
                   {"key": "PPA-2", "fields": {"issuelinks": []}}]})

    excluded = []
    assert hook.dispatchable_set("REPO: x", excluded=excluded) == ["PPA-1", "PPA-2"]
    assert excluded == []


def test_the_blocks_direction_does_not_hold_up_the_blocking_ticket(monkeypatch):
    """Only `is blocked by` gates readiness. A ticket that blocks others is not
    itself waiting on anything, and excluding it would drop the ticket the whole
    chain is waiting for."""
    monkeypatch.setattr(hook, "_jira_get", lambda path, timeout=None: {"issues": [
        {"key": "PPA-1456", "fields": {"issuelinks": [
            {"type": {"name": "Blocks", "inward": "is blocked by",
                      "outward": "blocks"},
             "outwardIssue": {"key": "PPA-1464", "fields": {
                 "status": {"name": "In Progress"}}}}]}}]})

    excluded = []
    assert hook.dispatchable_set("REPO: x", excluded=excluded) == ["PPA-1456"]
    assert excluded == []


def test_the_dispatchable_read_asks_for_the_links_it_needs(monkeypatch):
    seen = {}

    def fake_get(path, timeout=None):
        seen["path"] = path
        return {"issues": []}

    monkeypatch.setattr(hook, "_jira_get", fake_get)
    hook.dispatchable_set("REPO: peech-skills")

    assert "issuelinks" in seen["path"]


def test_an_excluded_ticket_is_named_never_dropped_in_silence(
        sandbox, monkeypatch, capsys):
    """Condition 4. A check that quietly shrinks its own population is worse
    than one that asks too much."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-skills")

    def with_exclusion(component, excluded=None, **kw):
        if excluded is not None:
            excluded.append(("PPA-1464", ["PPA-1456"]))
        return []

    monkeypatch.setattr(hook, "dispatchable_set", with_exclusion)

    code, out = run("PPA-1416", capsys=capsys)
    message = json.loads(out)["systemMessage"]

    assert code == 0
    assert "PPA-1464" in message and "PPA-1456" in message
    assert "blocking link" in message
    assert "blocked-tickets-excluded" in [r["reason"] for r in log_records()]


def test_an_unreadable_link_graph_excludes_nothing(monkeypatch):
    """Condition 6, last case. A row whose links cannot be read is left in the
    set rather than dropped - the failure direction that asks too much, not the
    one that goes quiet."""
    monkeypatch.setattr(hook, "_jira_get", lambda path, timeout=None: {"issues": [
        {"key": "PPA-1", "fields": {"issuelinks": "not a list at all"}}]})

    excluded = []
    unreadable = []
    assert hook.dispatchable_set(
        "REPO: x", excluded=excluded, unreadable=unreadable) == ["PPA-1"]
    assert excluded == []
    assert [key for key, _ in unreadable] == ["PPA-1"], (
        "the row stays in the set, but the read that failed is handed back")


def test_an_unreadable_link_graph_is_named_never_dropped_in_silence(
        sandbox, monkeypatch, capsys):
    """Condition 6, the record half. Leaving the row in the set is the safe
    direction; leaving it there with nothing on the record is the silent
    degrade every sibling failure path in this file refuses to be."""
    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-skills")

    def with_unreadable(component, excluded=None, unreadable=None, **kw):
        if unreadable is not None:
            unreadable.append(("PPA-1464", "TypeError('not a list at all')"))
        return []

    monkeypatch.setattr(hook, "dispatchable_set", with_unreadable)

    code, out = run("PPA-1416", capsys=capsys)
    message = json.loads(out)["systemMessage"]

    assert code == 0, "an unreadable link graph warns and allows"
    assert "PPA-1464" in message and "not a list at all" in message
    assert "blocker-read-failed" in [r["reason"] for r in log_records()]


# ---- one read pass -------------------------------------------------------

def adf(text):
    return {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def test_a_dispatch_makes_no_more_than_two_jira_calls(
        sandbox, monkeypatch, capsys):
    """Condition 5. Three searches before PPA-1465 - the repository derivation,
    the dispatchable set and the Bar - and two after, because the first and the
    third wanted the same issues and between them the same fields."""
    calls = []

    def fake_get(path, timeout=None):
        calls.append(path)
        if "issuelinks" in path:
            return {"issues": []}
        return {"issues": [{"key": "PPA-1416", "fields": {
            "status": {"name": "To Do"},
            "components": [{"name": "EXA: Delegated"},
                           {"name": "REPO: peech-skills"}],
            "description": adf("Skills to load and apply: [pt-backlog]\n"
                               "## Scope boundary\nOne file."),
            "customfield_10767": adf("One condition."),
        }}]}

    install_stub(sandbox)
    rooted_in(monkeypatch, sandbox, "peech-skills")
    monkeypatch.setattr(hook, "_jira_get", fake_get)
    monkeypatch.setattr(REAL, "_jira_get", fake_get)
    monkeypatch.setattr(hook, "read_dispatched", REAL.read_dispatched)
    monkeypatch.setattr(hook, "repo_components_of", REAL.repo_components_of)
    monkeypatch.setattr(hook, "work_types_of", REAL.work_types_of)
    monkeypatch.setattr(hook, "bar_fields_of", REAL.bar_fields_of)
    monkeypatch.setattr(hook, "dispatchable_set", REAL.dispatchable_set)

    code, _ = run("PPA-1416", capsys=capsys)

    assert code == 0, "a well-formed dispatch is not refused"
    assert fired(sandbox) == ["PPA-1416"]
    assert len(calls) <= 2, f"three reads became two; got {len(calls)}: {calls}"
    assert len(calls) == 2


def test_the_three_checks_read_one_shared_answer(monkeypatch):
    """The read is performed once and handed down, rather than each check
    reaching for it."""
    calls = []

    def fake_get(path, timeout=None):
        calls.append(path)
        return {"issues": [{"key": "PPA-1", "fields": {
            "status": {"name": "To Do"},
            "components": [{"name": "REPO: peech-skills"}],
            "description": adf("x"), "customfield_10767": adf("y")}}]}

    monkeypatch.setattr(REAL, "_jira_get", fake_get)
    fields, error = REAL.read_dispatched(["PPA-1"])

    assert error is None
    assert len(calls) == 1
    assert REAL.repo_components_of(["PPA-1"], fields=fields) == {
        "PPA-1": "REPO: peech-skills"}
    assert REAL.bar_fields_of(["PPA-1"], fields=fields) is fields
    assert len(calls) == 1, "neither derivation read again"


def test_the_shared_read_never_raises(monkeypatch):
    """The error rides out rather than propagating, because which warning is
    owed depends on which check went without."""
    def boom(path, timeout=None):
        raise OSError("no route to host")

    monkeypatch.setattr(REAL, "_jira_get", boom)
    fields, error = REAL.read_dispatched(["PPA-1"])

    assert fields is None
    assert isinstance(error, OSError)


def test_the_superseded_docstring_passage_is_gone():
    """Condition 7. A file that implements the block while asserting the
    opposite in its own docstring is a file that argues with itself."""
    source = HOOK.read_text()

    assert "the working directory is not an input here at all" not in source
    assert "The working directory is an input, to a different" in source
    assert "per repository is the standing practice" in source
    # The correction it replaced is still named rather than quietly dropped.
    assert "PPA-1413 and PPA-1417" in source


# --------------------------------------------------------------------------
# Deployed skill drift — PPA-1470 Amendment 2, as corrected 16-SEP-2026
#
# Two drift cases, and each test below names which one it covers.
#
#   marketplace freshness - the deployed copy is older than origin/main.
#   session binding       - a newer SHA sits in the same cache, so a session
#                           that launched before it arrived still serves the
#                           older copy.
#
# Amendment 2 asked for a fixture of "peech-personal 3 commits behind with
# autoUpdate true". The conductor's correction of 16-SEP-2026 withdrew it:
# that state was a timing window and no longer exists. The pair below is the
# one the correction names instead, and both SHAs are real -
# 352848b521a0 serving pt-terminal-formatting 6-2-0, af2b1001d7cc serving
# 6-5-0, both present in the peech-personal cache on the measuring machine.
# --------------------------------------------------------------------------

STALE_SHA, STALE_VERSION = "352848b521a0", "6-2-0"
FRESH_SHA, FRESH_VERSION = "af2b1001d7cc", "6-5-0"

#: The sandbox fixture replaces hook.report_skill_drift with a no-op, so the
#: two cases that exercise the real one hold a reference taken at import.
_real_report_skill_drift = hook.report_skill_drift


def skill_copy(root, sha, version, skill="pt-terminal-formatting"):
    """One deployed plugin copy at ``sha``, serving ``skill`` at ``version``."""
    target = (root / "cache" / "peech-personal" / "pt-personal-skills" / sha
              / "skills" / skill)
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"# {skill}\n\n*Version {version} • 16-SEP-2026*\n")
    return target.parents[1]


def plugins_root(tmp_path, deployed_sha, *also):
    """A ~/.claude/plugins tree with ``deployed_sha`` installed.

    Every copy is stamped to the same mtime, so no case inherits an ordering
    from the order the directories happened to be written. A case that wants
    one copy newer says so, by stamping it.
    """
    root = tmp_path / "plugins"
    root.mkdir(exist_ok=True)
    stamp = time.time()
    for sha, version in (deployed_sha, *also):
        os.utime(skill_copy(root, sha, version), (stamp, stamp))
    install = (root / "cache" / "peech-personal" / "pt-personal-skills"
               / deployed_sha[0])
    (root / "installed_plugins.json").write_text(json.dumps({
        "version": 2,
        "plugins": {"pt-personal-skills@peech-personal": [
            {"scope": "user", "installPath": str(install)}]},
    }))
    return root


def test_session_binding_drift_is_reported_with_both_versions(tmp_path):
    """SESSION BINDING. The deployed copy is 6-2-0 and a 6-5-0 copy sits
    beside it in the same cache, which is the pair the correction names."""
    root = plugins_root(tmp_path, (STALE_SHA, STALE_VERSION))
    fresh = skill_copy(root, FRESH_SHA, FRESH_VERSION)
    os.utime(fresh, (time.time() + 60, time.time() + 60))

    findings, _notes = hook.skill_drift(root)

    assert len(findings) == 1
    assert "session binding" in findings[0]
    assert f"pt-terminal-formatting {STALE_VERSION} -> {FRESH_VERSION}" in findings[0]
    assert FRESH_SHA in findings[0] and STALE_SHA in findings[0]


def test_the_fresh_half_of_the_pair_reports_nothing(tmp_path):
    """SESSION BINDING. The same tree with the newer copy deployed: no
    finding. A stale-then-fresh pair is two runs, and this is the second."""
    root = plugins_root(tmp_path, (FRESH_SHA, FRESH_VERSION),
                        (STALE_SHA, STALE_VERSION))

    findings, _notes = hook.skill_drift(root)

    assert [f for f in findings if "session binding" in f] == []


def test_a_newer_sha_carrying_the_same_version_is_not_drift(tmp_path):
    """SESSION BINDING. A pull that changed some other skill moves the cache
    without moving this one. Reporting that would train the reader to skip."""
    root = plugins_root(tmp_path, (STALE_SHA, STALE_VERSION))
    same = skill_copy(root, "cafebabe0001", STALE_VERSION)
    os.utime(same, (time.time() + 60, time.time() + 60))

    findings, _notes = hook.skill_drift(root)

    assert [f for f in findings if "session binding" in f] == []


def test_marketplace_freshness_drift_is_reported_with_both_versions(tmp_path):
    """MARKETPLACE FRESHNESS. The deployed copy is behind origin/main, which
    is the case Amendment 2 was written for and the one that is not the
    session-binding case."""
    root = plugins_root(tmp_path, (STALE_SHA, STALE_VERSION))
    clone = root / "marketplaces" / "peech-personal"
    (clone / "skills" / "pt-terminal-formatting").mkdir(parents=True)
    (clone / "skills" / "pt-terminal-formatting" / "SKILL.md").write_text(
        f"# pt-terminal-formatting\n\n*Version {FRESH_VERSION} • 16-SEP-2026*\n")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"],
                ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
                ["branch", "-f", "origin/main", "main"]):
        subprocess.run(["git", "-C", str(clone), *cmd], check=True,
                       capture_output=True)

    findings, _notes = hook.skill_drift(root)

    fresh = [f for f in findings if "marketplace freshness" in f]
    assert len(fresh) == 1
    assert f"deployed {STALE_VERSION}, origin/main {FRESH_VERSION}" in fresh[0]


def test_no_marketplace_clone_is_a_note_and_never_a_finding(tmp_path):
    """An absent clone is not drift. Where the comparison cannot run the hook
    says so in one line - PPA-1470's condition, and it names no skill stale."""
    root = plugins_root(tmp_path, (FRESH_SHA, FRESH_VERSION))

    findings, notes = hook.skill_drift(root)

    assert findings == []
    assert any("no marketplace clone" in n for n in notes)


def test_an_absent_plugins_tree_is_a_note_and_never_a_finding(tmp_path):
    findings, notes = hook.skill_drift(tmp_path / "nothing")

    assert findings == []
    assert notes


def test_the_comparison_reads_the_deployed_path_never_a_working_tree(tmp_path):
    """PPA-1470's condition, asserted rather than asserted in prose: the path
    compared is the installPath installed_plugins.json records."""
    root = plugins_root(tmp_path, (FRESH_SHA, FRESH_VERSION))

    (marketplace, plugin, path), = hook.installed_plugins(root)

    assert (marketplace, plugin) == ("peech-personal", "pt-personal-skills")
    assert path.name == FRESH_SHA
    assert "plugins" in path.parts and str(root) in str(path)


def test_the_drift_report_never_refuses_a_dispatch(sandbox, monkeypatch, capsys):
    """It warns. A stale skill is a fact worth knowing at dispatch, and it is
    not the command being wrong."""
    install_stub(sandbox)
    monkeypatch.setattr(
        hook, "skill_drift",
        lambda root=None: (["pt-personal-skills/pt-x is stale: deployed 1-0-0, "
                            "origin/main 2-0-0 (marketplace freshness)."], []))
    monkeypatch.setattr(hook, "report_skill_drift", _real_report_skill_drift)

    code, out = run("PPA-1416", capsys=capsys)

    assert code == 0
    assert "deployed skills have drifted" in out
    assert fired(sandbox) == ["PPA-1416"]


def test_a_raising_drift_check_still_lets_the_dispatch_through(monkeypatch,
                                                              capsys):
    """A report that breaks must not break a dispatch."""
    def boom(root=None):
        raise RuntimeError("cache unreadable")

    monkeypatch.setattr(hook, "skill_drift", boom)

    _real_report_skill_drift()

    assert "deployed skills not compared" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Finding 2 — the locked skills statement, and what reads it
#
# PPA-1470 Amendment 3 found one reader of the statement, a Ticket Quality Bar
# item matching the colon prefix. PPA-1684 retired that item under ruling 1A
# (PPA-1659 comment 30108), so no stored form refuses a dispatch any more.
# --------------------------------------------------------------------------

#: The three forms measured live on 17-SEP-2026 across the eight dispatched
#: tickets, and the fourth the hook refused.
PLAIN_COLON = "Skills to load and apply: pt-backlog, pt-conduct-gates"
PLAIN_BRACKETS = "Skills to load and apply: [pt-backlog, pt-conduct-gates]"
ESCAPED_BRACKETS = r"Skills to load and apply: \[pt-backlog, pt-conduct-gates\]"
NO_COLON = "_Skills to load and apply_\npt-backlog, pt-conduct-gates"


@pytest.mark.parametrize("form", [
    PLAIN_COLON, PLAIN_BRACKETS, ESCAPED_BRACKETS, NO_COLON,
], ids=["plain", "brackets", "escaped brackets", "no colon"])
def test_no_stored_form_of_the_skills_line_fails_the_bar(form):
    """The no-colon form is the one PPA-1473 was refused for on 17-SEP-2026."""
    scope = "\n## Scope boundary\nEdits one file."
    assert hook.bar_failures(bar_fields(description=form + scope)) == []


# --------------------------------------------------------------------------
# Every failure path this ticket adds writes a record — PPA-1470, 17-SEP-2026
#
# Each one degrades towards letting the dispatch through, which is right. The
# condition is about what it leaves behind on the way: a check that disables
# itself and says nothing is indistinguishable from a check that ran and found
# nothing. One case per path, each asserting the record rather than the return.
# --------------------------------------------------------------------------

@pytest.fixture
def logged(tmp_path, monkeypatch):
    """hook.LOG redirected, and the records it collected, read on demand.

    The cases below call the helpers directly rather than through a dispatch,
    so they do not get the sandbox fixture's redirection and would otherwise
    append to the operator's own failure log.
    """
    monkeypatch.setattr(hook, "LOG", tmp_path / "log" / "hook.log")
    return log_records


def reasons(logged):
    return [record["reason"] for record in logged()]


def test_an_unreadable_installed_plugins_file_is_recorded(tmp_path, logged):
    """Without the record this is indistinguishable from nothing installed,
    which skill_drift() already notes in those words."""
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "installed_plugins.json").write_text("{ not json")

    assert hook.installed_plugins(root) == []
    assert "plugins-unreadable" in reasons(logged)


def test_an_unreadable_skill_header_is_recorded(tmp_path, logged):
    """None here drops the skill out of the comparison, so a skill whose
    SKILL.md cannot be read silently stops being compared."""
    unreadable = tmp_path / "SKILL.md"
    unreadable.mkdir()

    assert hook.version_in(unreadable) is None
    assert "skill-version-unreadable" in reasons(logged)


@pytest.mark.parametrize("failing_call, step", [(0, "ls-tree"), (1, "cat-file")])
def test_a_marketplace_read_that_fails_is_recorded(
        tmp_path, logged, monkeypatch, failing_call, step):
    """Two git reads, two records. The clone is present and git failed, which
    is not the absent clone skill_drift() notes."""
    root = tmp_path / "plugins"
    (root / "marketplaces" / "peech-personal" / ".git").mkdir(parents=True)
    listing = ("100644 blob " + "a" * 40
               + "\tskills/pt-terminal-formatting/SKILL.md\n")
    calls = []

    def flaky(argv, **kw):
        calls.append(argv)
        if len(calls) - 1 == failing_call:
            raise OSError("git is not on this machine")
        return subprocess.CompletedProcess(argv, 0, stdout=listing, stderr="")

    monkeypatch.setattr(hook.subprocess, "run", flaky)

    assert hook.marketplace_skill_versions("peech-personal", root) == {}
    assert [r["step"] for r in logged()
            if r["reason"] == "marketplace-read-failed"] == [step]


def test_an_unreadable_cache_directory_is_recorded(tmp_path, logged):
    """The session-binding half reports nothing from here, and nothing is also
    what it reports when there is no newer copy. Only the record tells them
    apart."""
    parent = tmp_path / "pt-personal-skills"
    parent.mkdir()

    assert hook.newer_cache_copies(parent / "never-installed") == []
    assert "cache-copies-unreadable" in reasons(logged)


# --------------------------------------------------------------------------
# The barred-artifact Bar item — PPA-1520
#
# scripts/check_dod_barred_artifacts.py existed and nothing called it: its
# main() returns 0 whatever it finds. The hook already reads customfield_10767
# for the Ticket Quality Bar, so the read costs nothing and the wiring is one
# BAR_ITEMS entry. The site is the dispatch and not the Stop event - at Stop
# the ticket is already written and the dispatch is already spent.


def dod_adf(*conditions):
    """A Definition of Done in the shape customfield_10767 returns."""
    return {"type": "doc", "version": 1, "content": [{
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [{
            "type": "paragraph",
            "content": [{"type": "text", "text": text}]}]}
            for text in conditions]}]}


#: A condition demanding the one artifact BARS carries. Written as PPA-1428
#: condition 8 was - "the change-log rows are quoted" - rather than invented.
BARRED = "[machine] The change-log rows are quoted from the updated file."
CLEAN = "[machine] pytest counts for scripts/ are quoted."


def barred_fields(*conditions):
    """Bar-passing fields whose Definition of Done carries these conditions."""
    return bar_fields(dod_adf=dod_adf(*conditions),
                      dod=" ".join(conditions))


def test_a_barred_condition_refuses_the_dispatch_naming_the_key_and_the_bar(
        sandbox, monkeypatch, capsys):
    """Named test 1. The refusal names the key so it can be acted on, and the
    bar so the conductor is not sent to the check to find out which."""
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": barred_fields(CLEAN, BARRED)})

    code, _ = run("PPA-1")
    err = capsys.readouterr().err

    assert code == 2
    assert "PPA-1" in err
    assert "change log or revision-history entry" in err, err
    assert fired(sandbox) == [], "a refused dispatch transitioned its ticket"


def test_the_existing_prose_opt_out_waves_the_same_key_through(
        sandbox, monkeypatch, capsys):
    """Named test 2. The opt-out is the Bar's own - naming the key again below
    the dispatch line - and PPA-1520 adds no second one."""
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": barred_fields(BARRED)})

    code, _ = run("PPA-1\n\nPPA-1's change-log condition is being amended; "
                  "dispatching anyway.", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1"]


def test_no_second_opt_out_was_added():
    """The same rule from the other side: the only thing that waves a barred
    ticket through is mentioned_beyond_dispatch_line(), which every other Bar
    item already uses. A bar-specific escape would be a second one."""
    fields = barred_fields(BARRED)

    assert hook.bar_failures(fields), "the item did not fire at all"
    assert hook.bar_failures(dict(fields, dod_adf=None)) == [], (
        "an absent field is the only other thing that clears it")


def test_a_clean_ticket_is_unaffected(sandbox, monkeypatch, capsys):
    """Named test 3."""
    install_stub(sandbox)
    bar(monkeypatch, **{"PPA-1": barred_fields(CLEAN)})

    code, _ = run("PPA-1", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1"]


def test_an_amended_condition_still_naming_the_artifact_is_not_refused(
        sandbox, monkeypatch, capsys):
    """The four shipped conditions were amended in place and each still names
    the artifact, because each says which demand it removes. A substring test
    would refuse every one of them - the check's withdrawal rule is what stops
    that, and wiring it here must not have bypassed it."""
    install_stub(sandbox)
    amended = ("[machine] No change-log row is required and none is quoted; "
               "the original condition demanded one.")
    bar(monkeypatch, **{"PPA-1": barred_fields(amended)})

    code, _ = run("PPA-1", capsys=capsys)

    assert code == 0
    assert fired(sandbox) == ["PPA-1"]


def test_a_jira_read_failure_warns_and_allows_the_barred_item(
        sandbox, monkeypatch, capsys):
    """Named test 4. The shared read failing is already handled by
    check_quality_bar(), which warns and allows; this asserts the new item did
    not turn that into a refusal."""
    install_stub(sandbox)

    def boom(keys, **kw):
        raise RuntimeError("Jira unreachable")

    monkeypatch.setattr(hook, "bar_fields_of", boom)

    code, _ = run("PPA-1", capsys=capsys)

    assert code == 0, "a read failure refused the dispatch"
    assert fired(sandbox) == ["PPA-1"]


def test_a_check_that_will_not_import_warns_and_allows(monkeypatch, capsys):
    """The check lives in peech-pmo-automation alone. In the two siblings the
    import finds nothing and the item declines to run, exactly as the
    byte-identity register's does - a check that cannot look must not refuse."""
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "check_dod_barred_artifacts":
            raise ModuleNotFoundError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)

    assert hook.barred_artifacts(barred_fields(BARRED)) == []
    assert hook.bar_failures(barred_fields(BARRED)) == []


def test_a_check_that_raises_is_recorded_rather_than_swallowed(
        sandbox, monkeypatch):
    """A check that is present and will not work has silently disabled a Bar
    item, which is the degrade every other failure path here puts on record."""
    import builtins

    real = builtins.__import__

    def explode(name, *args, **kwargs):
        if name == "check_dod_barred_artifacts":
            raise ValueError("syntax error in the check")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", explode)

    assert hook.barred_artifacts(barred_fields(BARRED)) == []
    reasons = [r["reason"] for r in log_records()]
    assert "barred-artifact-check-unreadable" in reasons, reasons


def test_the_item_reads_the_unflattened_field_and_makes_no_second_jira_call(
        monkeypatch):
    """The check reports per condition, and the flattened ``dod`` string the
    other items use has lost the boundaries between them. The raw field rides
    out of the same read rather than costing another."""
    seen = []

    def fake_get(path, timeout=None):
        seen.append(path)
        return {"issues": [{"key": "PPA-1", "fields": {
            "status": {"name": "In Progress"},
            "components": [{"name": "REPO: peech-skills"}],
            "description": {"type": "doc", "content": []},
            "customfield_10767": dod_adf(BARRED)}}]}

    monkeypatch.setattr(hook, "_jira_get", fake_get)
    fields = hook.dispatched_fields(["PPA-1"])["PPA-1"]

    assert len(seen) == 1, "the new item cost a second Jira call"
    assert fields["dod_adf"] == dod_adf(BARRED)
    assert hook.barred_artifacts(fields) == [
        "a change log or revision-history entry"]


def test_what_the_check_detects_and_its_bar_list_are_unchanged():
    """The scope boundary, asserted rather than asserted about: PPA-1520 added
    an entry point and touched neither BARS nor the detection."""
    sys.path.insert(0, str(HOOK.resolve().parents[1] / "scripts"))
    import check_dod_barred_artifacts as check

    assert len(check.BARS) == 1
    assert check.BARS[0].artifact == "a change log or revision-history entry"
    assert check.barred_demands("PPA-1", dod_adf(BARRED))
    assert check.barred_demands("PPA-1", dod_adf(CLEAN)) == []
    assert check.barred_demands("PPA-1", None) == []


# --------------------------------------------------------------------------
# --dispatch-set <repo> - PPA-1660
# --------------------------------------------------------------------------

def _backlog_get(calls=None):
    """Three open tickets for one repository: PPA-1 blocked by an open issue,
    PPA-2 clearing the Bar, PPA-3 carrying no scope boundary."""
    def fake_get(path, timeout=None):
        if calls is not None:
            calls.append(path)
        if "issuelinks" in path:
            return {"issues": [
                {"key": "PPA-1", "fields": {"issuelinks": [{
                    "type": {"inward": "is blocked by"},
                    "inwardIssue": {"key": "PPA-9", "fields": {
                        "status": {"name": "In Progress"}}}}]}},
                {"key": "PPA-2", "fields": {"issuelinks": []}},
                {"key": "PPA-3", "fields": {"issuelinks": []}},
            ]}
        base = [{"name": "EXA: Delegated"}, {"name": "REPO: peech-skills"}]
        return {"issues": [
            {"key": "PPA-2", "fields": {
                "status": {"name": "To Do"}, "components": base,
                "description": adf("Skills to load and apply: [pt-backlog]\n"
                                   "## Scope boundary\nOne file."),
                "customfield_10767": adf("[machine] One condition.")}},
            {"key": "PPA-3", "fields": {
                "status": {"name": "Reopened"}, "components": base,
                "description": adf("Skills to load and apply: [pt-backlog]"),
                "customfield_10767": adf("[machine] One condition.")}},
        ]}
    return fake_get


def test_the_dispatch_set_is_the_set_the_hook_demands(monkeypatch):
    """The mode prints the keys ``dispatchable_set`` returns, and those are the
    keys the completeness check refuses a dispatch for omitting."""
    monkeypatch.setattr(REAL, "_jira_get", _backlog_get())
    monkeypatch.setattr(REAL, "log", lambda *a, **k: None)
    monkeypatch.setattr(REAL, "warn", lambda message: None)
    monkeypatch.setattr(REAL, "repo_components_of",
                        lambda keys, **kw: dict.fromkeys(keys, "REPO: peech-skills"))

    printed = [line.split("\t")[0]
               for line in REAL.dispatch_set_lines("peech-skills")
               if not line.startswith("#")]
    hook_set = REAL.dispatchable_set("REPO: peech-skills")

    assert printed == hook_set == ["PPA-2", "PPA-3"]
    blocked = REAL.check_dispatch_complete("PPA-7", ["PPA-7"])
    assert "named nowhere in this prompt: PPA-2, PPA-3" in blocked


def test_a_key_failing_the_bar_is_printed_with_its_reason(monkeypatch):
    monkeypatch.setattr(REAL, "_jira_get", _backlog_get())

    lines = REAL.dispatch_set_lines("REPO: peech-skills")

    assert lines == [
        "PPA-2\tTo Do\tDelegated\tPASS",
        "PPA-3\tReopened\tDelegated\tFAIL - missing a scope boundary",
        "# not demanded, blocked by PPA-9: PPA-1",
    ]


def test_the_mode_exits_zero_on_a_bar_failure_and_one_on_a_read_failure(
        monkeypatch, capsys):
    monkeypatch.setattr(REAL, "_jira_get", _backlog_get())
    assert REAL.dispatch_set_main(["--dispatch-set", "peech-skills"]) == 0
    assert "FAIL - missing a scope boundary" in capsys.readouterr().out

    def boom(path, timeout=None):
        raise OSError("no route to host")

    monkeypatch.setattr(REAL, "_jira_get", boom)
    assert REAL.dispatch_set_main(["--dispatch-set", "peech-skills"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no route to host" in captured.err


def test_the_mode_writes_nothing_to_jira(monkeypatch):
    """Every request the mode makes is a search read."""
    calls = []
    monkeypatch.setattr(REAL, "_jira_get", _backlog_get(calls))
    REAL.dispatch_set_lines("peech-skills")
    assert calls and all(path.startswith("/search/jql?") for path in calls)
