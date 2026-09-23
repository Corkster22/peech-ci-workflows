"""pr_merge_close_out.py — the tests named in PPA-1261, as amended.

Three groups, mapping onto the ticket's "Named tests" bullets: key extraction
from a squash-merge message including the false-positive case, the amended
three-way status rule, and the idempotence rule on the comment.

No test here reaches Jira. The stub answers the one read the script makes and
records every write, in the same shape conftest.StubJira does for
pt_transition.py — the two scripts share a client, so they share a stub idiom.
"""

import ast
import json
import re
import subprocess
from pathlib import Path

import pr_merge_close_out as closeout
import pytest
from pr_merge_close_out import (  # noqa: E402
    close_out_keys, exit_code, key_from_branch, key_from_subject, keys_in,
    build_table, condition_class, norm, plan_transition, run,
    FAILED_EXIT, OK, PARTIAL_EXIT, keys_from_branch,
    keys_from_commit_subjects, key_sources, own_keys_in, transitioned,
)

SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
DATE = "07-SEP-2026"


class StubJira:
    """Answers /issue/KEY?fields=... and records every read and every comment.

    It still answers with a ``labels`` field the script no longer asks for
    (PPA-1382), on purpose: a stub that stopped supplying labels would make
    test_a_labelled_ticket_routes_the_same_way pass for the wrong reason.
    ``gets`` records the request paths so the query itself can be asserted.
    """

    def __init__(self, status="In Progress", labels=(), comments=(), dod=None):
        self.status = status
        self.labels = list(labels)
        self.comments = list(comments)
        self.dod = dod
        self.posts = []
        self.gets = []

    def get(self, path):
        assert path.startswith("/issue/"), path
        self.gets.append(path)
        return {"fields": {
            "status": {"name": self.status},
            "labels": self.labels,
            "comment": {"comments": self.comments},
            "customfield_10767": self.dod,
        }}

    def post(self, path, payload):
        self.posts.append((path, payload))
        return None


def comment_naming(sha):
    """An existing Jira comment whose text carries `sha`, in ADF."""
    return {"body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": f"Merged to main as {sha} on 01-JAN-2026."}]}]}}


@pytest.fixture(autouse=True)
def never_shell_out(monkeypatch):
    """Fail loudly if a test fires pt_transition.py for real.

    Every transition in this suite is asserted through the recorded call, not
    by moving a live ticket. A test that shelled out would reach Jira with the
    operator's own credentials.
    """
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="PPA-1 PASS\n", stderr="")

    monkeypatch.setattr(closeout.subprocess, "run", fake_run)
    return calls


# --------------------------------------------------------------------------
# Named test 1 — key extraction from a squash-merge message
# --------------------------------------------------------------------------

def test_a_message_with_no_key_yields_none():
    """Not every commit on main comes from a ticketed pull request, so zero is
    a normal answer rather than a failure."""
    assert keys_in("chore: bump a pin (#88)") == []


def test_one_key_is_extracted():
    assert keys_in("feat: add the thing (PPA-1264)") == ["PPA-1264"]


#: The real squash message that bought PPA-1375's rule - peech-skills bcbc0fc,
#: the merge of PR #173, quoted verbatim and trimmed to the paragraph that did
#: the damage. Run 34637111426 closed PPA-1375 out of this and commented a
#: merge hash on a ticket that shipped nothing in it.
#:
#: The shape is the point, and PPA-1464 rebuilt these cases on it: a one-commit
#: squash with no bullets at all, whose body is plain prose citing another
#: ticket as provenance. The fixtures here were synthetic ``* `` bullets until
#: PPA-1464, which is the one shape the real case never had.
PROVENANCE_BODY = (
    "fix: derive the transition key from the branch name (PPA-1376) (#173)\n"
    "\n"
    "Second instance of the defect PPA-1375 fixes in peech-pmo-automation.\n"
    "Both are tracked because one commit cannot span two remotes.\n"
)


def test_a_body_citing_a_ticket_as_provenance_closes_out_nothing():
    """PPA-1375, on the message that bought the rule. PPA-1375 is cited in the
    body as provenance and shipped nothing in this merge, so it is not closed
    out - by the branch name, the subject or the commit subjects."""
    assert close_out_keys(None, PROVENANCE_BODY) == ["PPA-1376"]
    assert close_out_keys("ppa-1376-slug", PROVENANCE_BODY) == ["PPA-1376"]
    assert keys_from_commit_subjects(PROVENANCE_BODY) == [], (
        "prose is not a commit subject; there is no bullet here to read")


# --------------------------------------------------------------------------
# PPA-1375 — the key is the branch's own, never a citation in the body
# --------------------------------------------------------------------------

def test_the_head_ref_supplies_the_key():
    assert key_from_branch("ppa-1375-close-out-key") == "PPA-1375"
    assert key_from_branch("PPA-1375") == "PPA-1375"


@pytest.mark.parametrize("ref", ["main", "fix-the-thing", "", None, "xppa-1375"])
def test_a_branch_with_no_ppa_key_yields_none(ref):
    """The no-key branch: nothing is commented and nothing is transitioned."""
    assert key_from_branch(ref) is None


def test_a_supplied_head_ref_never_falls_back_to_the_message():
    """A head ref that carries no key is authoritative. Falling back to the
    message here would reopen the defect on exactly the branch that proves it."""
    message = "chore: a thing (#9)\n\n* cites PPA-1375 as provenance\n"
    assert close_out_keys("hotfix-no-key", message) == []


def test_the_subject_supplies_the_key_when_no_head_ref_is_given():
    """merge-close-out.yml runs on a push event and has no head ref, so this is
    the live path. The subject is the pull request title, which pr-open.yml
    derives from the branch name under PPA-1285."""
    assert key_from_subject("feat: a thing (PPA-1264) (#12)\n\n* PPA-1261\n") \
        == "PPA-1264"
    assert key_from_subject("chore: bump a pin (#88)\n\n* PPA-1261\n") is None
    assert key_from_subject("") is None


def test_run_34637111426_no_longer_closes_out_the_cited_key():
    """The live reproduction, replayed. PPA-1376's merge commented a merge hash
    on PPA-1375 - comment 28638 - for a merge that shipped none of its work."""
    message = (
        "fix: derive the key from the branch name (PPA-1376) (#173)\n\n"
        "* fix: derive the key from the branch name (PPA-1376)\n\n"
        "The same defect PPA-1375 fixes in this repository.\n"
    )
    assert close_out_keys(None, message) == ["PPA-1376"]
    assert "PPA-1375" not in close_out_keys(None, message)


def test_a_key_is_not_double_counted():
    assert keys_in("PPA-1264 and again PPA-1264, plus ppa-1264") == ["PPA-1264"]


@pytest.mark.parametrize(
    ("message", "why"),
    [
        ("see docs/spikes/PPA-1155-findings.md", "a path segment and a longer token"),
        ("PPA-1155-findings.md carries the counts", "a filename with no directory"),
        ("https://peech-team.atlassian.net/browse/PPA-1264", "a URL path segment"),
        ("scripts/tests/PPA-1264.py was added", "a path plus a file extension"),
        ("XPPA-1264 is not a key", "a word prefix"),
        ("PPA- is not a key", "no number"),
    ],
)
def test_a_key_shaped_string_that_is_not_a_key_does_not_match(message, why):
    """The false-positive case PPA-1261 names. A URL or a filename carrying a
    key would transition an unrelated ticket every time a document is
    mentioned in a commit body, and docs/spikes/PPA-1155-findings.md is
    referenced by three tickets in this epic alone."""
    assert keys_in(message) == [], why


def test_a_key_ending_a_sentence_still_matches():
    """The other side of the filename rule: a trailing period is punctuation,
    not an extension, and must not suppress the key."""
    assert keys_in("this closes PPA-1261.") == ["PPA-1261"]


def test_the_pull_request_number_comes_off_the_squash_subject():
    assert closeout.pr_number_in("feat: a thing (#3)\n\n* x (PPA-1)") == "3"
    assert closeout.pr_number_in("feat: a thing (PPA-1)") is None


# --------------------------------------------------------------------------
# Named tests 2 to 4 — the status rule
# --------------------------------------------------------------------------
#
# PPA-1382 replaced the two-way rule this section used to hold. Done was the
# default and Client Validation fired only on a needs-live-validation label, so
# Done meant merged and pt-backlog's documented meaning had nothing enforcing
# it. Client Validation is now the only outcome and the label is gone.


def test_in_progress_transitions_to_client_validation(never_shell_out):
    """A merge evidences that the code landed, and nothing more. Whether the
    Definition of Done is met is a judgement the merge event does not carry, so
    the ticket routes to the gate that owns it rather than past it."""
    assert plan_transition("In Progress") == (
        "Client Validation", "merged; the verdict table could not be built", [])

    stub = StubJira(status="In Progress")
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert outcomes[0].verdict == "MOVED"
    assert never_shell_out[0][-4:] == [
        "--keys", "PPA-1", "--to", "Client Validation"], (
        "the transition is fired through pt_transition.py, by name")
    assert "--conductor" not in never_shell_out[0], (
        "Client Validation is not behind the conductor guard; passing the flag "
        "would claim a role this workflow does not hold")
    assert exit_code(outcomes) == 0


def test_no_input_that_must_not_reach_done_reaches_it():
    """PPA-1459 replaces test_no_input_produces_a_done_outcome, which asserted
    Done was unreachable from every input. Done is reachable now, so the
    inverse is what needs sweeping: every input that must NOT produce it.

    Swept rather than sampled, for the reason the replaced test gave - a
    default nobody can name is exactly how the PPA-1382 rule survived."""
    statuses = ["In Progress", "To Do", "Done", "Client Validation",
                "Reopened", "BLOCKED", "in progress", "IN PROGRESS", ""]
    tables = [
        None,                                        # could not be built
        build_table(None, []),                       # no Definition of Done
        build_table(dod("[machine] a."), []),        # no close-out checklist
        build_table(dod("[machine] a."), [close_out("1. a. NOT MET.")]),
        build_table(dod("[machine] a."), [close_out("1. a. Met.")]),
        build_table(dod("[conductor] a."), [close_out("1. a. Met.")]),
        build_table(dod("[observer] a."), [close_out("1. a. Met.")]),
        build_table(dod("a, unclassified."), [close_out("1. a. Met.")]),
    ]
    for status in statuses:
        for table in tables:
            target, _reason, _failures = plan_transition(status, table)
            machine_and_met = (
                table is not None and table.rows and not table.unmet
                and all(condition_class(t) == "machine"
                        for _n, t, _v in table.rows))
            if norm(status) == norm("In Progress") and machine_and_met:
                assert target == "Done"
                continue
            assert target != "Done", f"{status!r} produced a Done target"
            assert target in (None, "Client Validation"), (
                f"{status!r} produced an unexpected target {target!r}")


def test_the_label_no_longer_exists():
    """needs-live-validation selected Client Validation when Done was the
    default. With Client Validation the only outcome it selects nothing, so it
    is gone rather than left as a branch that cannot change an answer.

    Checked against the parsed module rather than its text: the docstring names
    the label to record that it was retired, and that mention is the record,
    not a survival."""
    assert not hasattr(closeout, "LIVE_VALIDATION_LABEL")

    tree = ast.parse(Path(closeout.__file__).read_text(encoding="utf-8"))
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    live = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node not in docstrings
        and "needs-live-validation" in node.value
    ]
    assert not live, f"the label survives as a live string constant: {live}"


def test_a_labelled_ticket_routes_the_same_way(never_shell_out):
    """A ticket still carrying the retired label is not a special case. The
    label is no longer read at all, so it cannot change the outcome."""
    stub = StubJira(status="In Progress", labels=["needs-live-validation"])
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert outcomes[0].verdict == "MOVED"
    assert never_shell_out[0][-1] == "Client Validation"


def test_the_issue_read_no_longer_asks_for_labels(never_shell_out):
    """The rule stopped reading labels, so the request stopped asking for
    them. A field still in the query would be the visible half of a branch
    somebody could restore without noticing the other half is gone."""
    stub = StubJira(status="In Progress")
    run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert stub.gets, "the issue was never read"
    assert "labels" not in stub.gets[0], stub.gets[0]
    assert "status" in stub.gets[0] and "comment" in stub.gets[0]


def test_a_key_at_to_do_all_met_moves_to_in_progress_then_done(never_shell_out):
    """PPA-1601. No UserPromptSubmit hook runs in a repository that calls this
    workflow, so a merged key at To Do is moved to In Progress first and then
    routed exactly as it would be from there."""
    stub = StubJira(status="To Do", dod=ALL_MACHINE, comments=ALL_MET)
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert [argv[-1] for argv in never_shell_out] == ["In Progress", "Done"]
    assert outcomes[0].verdict == "MOVED"
    assert "moved 'To Do' to 'In Progress' first" in outcomes[0].detail, (
        "the outcome line still says the key started at To Do")
    assert exit_code(outcomes) == OK


def test_a_key_at_to_do_with_an_unmet_condition_moves_to_in_progress_and_is_held(
        never_shell_out):
    stub = StubJira(status="To Do", dod=ALL_MACHINE, comments=MACHINE_ONE_UNMET)
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert [argv[-1] for argv in never_shell_out] == ["In Progress"]
    assert outcomes[0].verdict == "HELD"
    assert held_posted(stub) is not None
    assert exit_code(outcomes) == PARTIAL_EXIT


def test_a_failed_to_do_hop_is_failed_and_the_key_is_not_graded(monkeypatch):
    calls = []

    def refused(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, stdout="PPA-1 HALT\n", stderr="")

    monkeypatch.setattr(closeout.subprocess, "run", refused)
    stub = StubJira(status="To Do", dod=ALL_MACHINE, comments=ALL_MET)
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert [argv[-1] for argv in calls] == ["In Progress"], (
        "nothing past the failed hop was fired")
    assert outcomes[0].verdict == "FAILED"
    assert "'To Do' to 'In Progress' first failed - PPA-1 HALT" in outcomes[0].detail
    assert exit_code(outcomes) == FAILED_EXIT


def test_a_dry_run_at_to_do_fires_nothing(never_shell_out):
    stub = StubJira(status="To Do", dod=ALL_MACHINE, comments=ALL_MET)
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE, dry_run=True)

    assert never_shell_out == []
    assert "would move 'To Do' to 'In Progress' first" in outcomes[0].detail
    assert "would move to 'Done'" in outcomes[0].detail


@pytest.mark.parametrize("status", ["Done", "Client Validation", "Reopened",
                                    "BLOCKED"])
def test_every_other_status_is_commented_and_skipped(status, never_shell_out):
    stub = StubJira(status=status)
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert outcomes[0].verdict == "SKIPPED"
    assert repr(status) in outcomes[0].detail
    assert never_shell_out == []


def test_the_only_write_is_a_comment(never_shell_out):
    """PPA-1261's scope boundary, which outlived the label it was written for.
    This workflow writes a comment and fires a transition through
    pt_transition.py. It edits no field on the issue."""
    stub = StubJira(status="In Progress", labels=["needs-live-validation"])

    run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    for path, payload in stub.posts:
        assert path.endswith("/comment"), f"the only write is a comment: {path}"
        assert "labels" not in json.dumps(payload)


# --------------------------------------------------------------------------
# Idempotence — a re-run must not double-comment
# --------------------------------------------------------------------------

def test_a_key_already_carrying_the_sha_is_not_commented_again(never_shell_out):
    """PPA-1261's idempotence rule. A push to main can be re-run from the
    Actions UI, and a second identical comment on every ticket is the visible
    cost of not checking."""
    stub = StubJira(status="In Progress", comments=[comment_naming(SHA)])

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert stub.posts == [], "no second comment"
    assert "already carries a comment" in outcomes[0].detail
    assert outcomes[0].verdict == "MOVED", (
        "the transition still runs; it is idempotent downstream")


def test_a_comment_naming_a_different_sha_does_not_suppress_this_one(
        never_shell_out):
    """The check is per merge, not per ticket. A ticket reopened and re-merged
    earns a second hash, and suppressing it would lose the newer one."""
    stub = StubJira(status="In Progress", comments=[comment_naming("0" * 40)])

    run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert len(stub.posts) == 1


def test_the_comment_names_the_sha_the_pull_request_and_the_date(
        never_shell_out):
    stub = StubJira(status="In Progress")

    run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    text = closeout.adf_text(stub.posts[0][1]["body"])
    assert SHA in text
    assert "#3" in text
    assert DATE in text
    assert "—" not in text, "hyphens, never em dashes - see pt-backlog"


def test_the_comment_survives_a_missing_pull_request_number(never_shell_out):
    """A direct push to main carries no (#N). The hash is still worth writing."""
    stub = StubJira(status="In Progress")

    run(stub.get, stub.post, ["PPA-1"], SHA, None, DATE)

    text = closeout.adf_text(stub.posts[0][1]["body"])
    assert SHA in text
    assert "pull request" not in text


def test_adf_text_reads_a_nested_body():
    """The idempotence check reads comment text out of ADF, whose shape is not
    this script's contract - a bullet list nests text three levels deeper than
    a paragraph, so the walker is shape-agnostic rather than positional."""
    body = {"type": "doc", "content": [{"type": "bulletList", "content": [
        {"type": "listItem", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "deep"}]}]}]}]}
    assert "deep" in closeout.adf_text(body)


# --------------------------------------------------------------------------
# The workflow file itself
# --------------------------------------------------------------------------

WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github" / "workflows" / "merge-close-out.yml")


def test_the_workflow_exists_at_the_repo_root_and_is_callable():
    """GitHub reads workflows from the repo-root .github/workflows only.

    PPA-1577. In peech-pmo-automation this test asserts the push trigger and
    the re-grade sweep. Here the workflow is called: the caller runs it on push
    to main and passes its Jira pair as secrets. PPA-1614 added the sweep as a
    second job, run when the caller passes regrade true; see
    test_merge_close_out_regrade.py. PPA-1616 added push to main so this
    repository closes out its own merges; see
    test_merge_close_out_self_trigger.py.
    """
    import yaml

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as the boolean True.
    secrets = workflow[True]["workflow_call"]["secrets"]

    assert list(workflow[True]) == ["push", "workflow_call"]
    assert secrets["JIRA_EMAIL"] == {"required": True}
    assert secrets["JIRA_API_TOKEN"] == {"required": True}
    assert secrets["SLACK_BOT_TOKEN"] == {"required": False}
    assert list(workflow["jobs"]) == ["close-out", "regrade-held"]
    assert "python .peech-ci-workflows/scripts/pr_merge_close_out.py\n" in (
        WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_never_interpolates_the_commit_message():
    """An untrusted commit message expanded into a shell is a script-injection
    path. The script reads it from git instead, so nothing expands it.

    The bar is on the event *payload*, which is where attacker-controlled text
    lives. PPA-1556 reads ``github.event_name`` - a fixed enum GitHub sets, in
    a job-level ``if:`` and never in a shell - and that is not the same claim:
    the assertion was ``"github.event" not in text`` and would have barred it
    for sharing a prefix rather than for carrying the risk.
    """
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "head_commit.message" not in text
    assert "github.event." not in text, "no event payload field is read at all"


# --------------------------------------------------------------------------
# PPA-1416 — the verdict table
# --------------------------------------------------------------------------
#
# The four cases the ticket names, then the founding case, then the guarantees
# the scope boundary makes: routing unchanged, and no merge blocked, failed or
# delayed.


def dod(*conditions):
    """A Definition of Done in the shape customfield_10767 returns."""
    return {"type": "doc", "version": 1, "content": [{
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [{
            "type": "paragraph",
            "content": [{"type": "text", "text": text}]}]}
            for text in conditions]}]}


def close_out(*lines):
    """A close-out comment, one paragraph per line, in ADF."""
    return {"body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        for line in lines]}}


def numbered(lines):
    """{number: verdict} for the rows stated_rows() read.

    The extractor's own output, collapsed for assertion. Since PPA-1517 the
    number a close-out types is no longer what a verdict is filed under, so
    these cases pin extraction only; pairing has its own cases below.
    """
    return {row.number: row.verdict for row in closeout.stated_rows(lines)}


def table_posted(jira):
    """The verdict table comment's ADF body, or None.

    The body is read rather than adf_text()'d, because that helper joins every
    node with a space and would glue the first row onto the headline.
    """
    for _path, payload in jira.posts:
        body = payload["body"]
        if closeout.TABLE_MARK not in closeout.adf_text(body):
            continue
        # The absent-checklist comment carries the same mark on purpose, so the
        # idempotency guard recognises either. A table is the one with rows.
        if any(n["type"] == "codeBlock" for n in body["content"]):
            return body
    return None


def headline_of(body):
    return body["content"][0]["content"][0]["text"]


ROW = re.compile(r"^\s*(\d+)\s\s+(NOT YET MET|NOT MET|UNSTATED|MET)\s")


def rows_of(body):
    """(number, verdict) for every row in a posted table."""
    block = next(n for n in body["content"] if n["type"] == "codeBlock")
    return [(int(m.group(1)), m.group(2))
            for m in (ROW.match(line)
                      for line in block["content"][0]["text"].splitlines())
            if m]


THREE = ("The hook is wired and the wiring is quoted.",
         "A real pull request is armed, with the times quoted.",
         "pytest counts are quoted and every change accounted for.")

#: How a close-out quotes THREE - abbreviated, which is what every real one
#: does. Since PPA-1517 this text is what a row is filed under, so a fixture
#: that quoted nothing would pair nothing and pass for the wrong reason.
QUOTES = ("The hook is wired",
          "A real pull request is armed",
          "pytest counts are quoted")


def test_a_close_out_reporting_every_condition_met(never_shell_out):
    """Named test 1."""
    jira = StubJira(dod=dod(*THREE), comments=[close_out(
        "Definition of Done, condition by condition.",
        "1. The hook is wired. Met, quoted from settings.json.",
        "2. A real pull request is armed. Met, PR #46 at 22:16:53Z.",
        "3. pytest counts. Met - 473 passed against a 449 baseline.")])

    outcomes = run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    body = table_posted(jira)
    assert rows_of(body) == [(1, "MET"), (2, "MET"), (3, "MET")]
    assert headline_of(body) == (
        "All 3 Definition of Done conditions are reported met by the close-out.")
    assert outcomes[0].verdict == "MOVED"


def test_a_close_out_reporting_one_condition_not_met(never_shell_out):
    """Named test 2, and the headline the ticket asks for."""
    jira = StubJira(dod=dod(*THREE), comments=[close_out(
        "Definition of Done, condition by condition.",
        "1. The hook is wired. Met, quoted from settings.json.",
        "2. A real pull request is armed, with the times quoted. NOT MET.",
        "3. pytest counts. Met - 473 passed against a 449 baseline.")])

    run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    body = table_posted(jira)
    assert rows_of(body) == [(1, "MET"), (2, "NOT MET"), (3, "MET")]
    assert headline_of(body) == (
        "1 of 3 Definition of Done conditions are not reported met: "
        "condition 2. This ticket is not ready for Done on the close-out's "
        "own account.")


def test_a_close_out_carrying_fewer_verdicts_than_conditions(never_shell_out):
    """Named test 3. The unstated condition is neither omitted nor assumed met."""
    jira = StubJira(dod=dod(*THREE), comments=[close_out(
        "Definition of Done, condition by condition.",
        "1. The hook is wired. Met.",
        "2. A real pull request is armed. Met.")])

    run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    body = table_posted(jira)
    assert rows_of(body) == [(1, "MET"), (2, "MET"), (3, "UNSTATED")]
    assert "not reported met" in headline_of(body)
    assert "condition 3" in headline_of(body)


def test_a_merged_key_with_no_close_out_comment_at_all(never_shell_out):
    """Named test 4, rewritten by the gate verdict of 13-SEP-2026.

    An absent checklist is reported as absent. A table of UNSTATED rows says
    the close-out was read and stated nothing; this says there was none to
    read. PPA-1407's 9-of-9 UNSTATED table was produced 86 seconds before its
    close-out was written, which is the instance that rewrote condition 1.
    """
    jira = StubJira(dod=dod(*THREE), comments=[])

    outcomes = run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    assert table_posted(jira) is None, "no verdict table is built"
    said = [closeout.adf_text(p["body"]) for _, p in jira.posts]
    absent = [s for s in said if "No close-out checklist" in s]
    assert len(absent) == 1, f"expected one absent-checklist comment, got {said}"
    assert "3 condition(s)" in absent[0]
    assert "UNSTATED" in absent[0] and "should not be read as one" in absent[0]
    assert outcomes[0].verdict == "HELD", (
        "since PPA-1518 an absent checklist applies no transition: no "
        "condition is evidenced, so there is nothing to route on")
    assert never_shell_out == [], "a transition was fired on an ungraded key"


# --- the founding case ----------------------------------------------------

PPA_1412_CLOSE_OUT = close_out(
    "Close-out, delegated session, 12-SEP-2026. Pull request #50, branch "
    "ppa-1412-behind-branch-update-trigger.",
    "Ten of eleven conditions are met. Condition 4 is not, and it is not met "
    "because this session cannot produce it without crossing a rule. That is "
    "stated first rather than buried.",
    "Definition of Done, condition by condition.",
    "1. Trigger set quoted from origin/main before any edit; the claim "
    "confirmed or corrected. Met, and the claim is confirmed, not corrected.",
    "2. The repository setting read live, its state reported. Met, in the "
    "route comment.",
    "3. The chosen route recorded in a comment before implementation. Met.",
    "4. An armed, behind, checks-green pull request updated with no push to "
    "main, proved by quoting the trigger that fired and the time it fired. "
    "NOT MET.",
    "5. No file outside peech-pmo-automation edited. Met. git diff --stat "
    "against main lists one file.",
)


#: PPA-1412's five conditions as the field carries them - longer than the
#: close-out's quotes of them, which is the ordinary relationship between the
#: two and the reason ``match_score`` is one-directional rather than exact.
PPA_1412_CONDITIONS = (
    "[machine] The trigger set is quoted from origin/main before any edit, and "
    "the claim in the description is confirmed or corrected.",
    "[machine] The repository setting is read live and its state reported.",
    "[machine] The chosen route is recorded in a comment before "
    "implementation begins.",
    "[machine] An armed, behind, checks-green pull request is updated with no "
    "push to main, proved by quoting the trigger that fired and the time.",
    "[machine] No file outside peech-pmo-automation is edited.",
)


def test_the_founding_case_produces_a_not_met_row_for_condition_four(
    never_shell_out
):
    """PPA-1412's own close-out text, verbatim from the ticket, is what this
    whole change exists for: the merge routed it to Client Validation carrying
    no trace of the sentence its session led with.

    Since PPA-1517 it proves a second thing. The close-out's rows are paired
    against the field's own wording, which each row abbreviates, so a pass here
    is the abbreviation case working on real text rather than on a fixture
    written to match.
    """
    jira = StubJira(dod=dod(*PPA_1412_CONDITIONS),
                    comments=[PPA_1412_CLOSE_OUT])

    run(jira.get, jira.post, ["PPA-1412"], SHA, "50", DATE)

    body = table_posted(jira)
    assert rows_of(body) == [(1, "MET"), (2, "MET"), (3, "MET"),
                             (4, "NOT MET"), (5, "MET")]
    assert "condition 4" in headline_of(body)


# --- what the parse refuses to guess at -----------------------------------

@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1. Something. Met.", {1: "MET"}),
        ("1. Something. NOT MET.", {1: "NOT MET"}),
        ("1) Something: Met, with evidence.", {1: "MET"}),
        ("- 4. Something — NOT MET", {4: "NOT MET"}),
        ("**4.** Something. Met", {4: "MET"}),
        ("Condition 12. Something. Met.", {12: "MET"}),
        ("4. Something. not yet met.", {4: "NOT YET MET"}),
        # The boundary guard: a condition whose own wording carries the words.
        ("1. A condition that cannot be evidenced is reported as not met.", {}),
        # Not a row at all.
        ("Ten of eleven conditions are met.", {}),
        ("Met.", {}),
    ],
)
def test_a_row_is_read_only_at_a_sentence_boundary(line, expected):
    assert numbered([line]) == expected


def test_not_met_is_never_read_as_met():
    """NOT MET contains MET. What keeps them apart is the sentence boundary -
    the characters before that inner MET are "NOT ", and a letter is not a
    boundary. Reordering the alternation changes nothing while that holds,
    measured by mutation rather than assumed."""
    assert numbered(["3. Something. NOT MET."]) == {3: "NOT MET"}
    assert numbered(["3. Something. Not yet met."]) == {
        3: "NOT YET MET"}


def test_the_first_verdict_for_a_number_wins():
    """A close-out restating a condition in its narrative must not overwrite
    the verdict its own checklist gave."""
    assert numbered([
        "4. The condition. NOT MET.",
        "4. Restated later in the narrative. Met.",
    ]) == {4: "NOT MET"}


# --------------------------------------------------------------------------
# PPA-1555 - a row number de-duplicates inside its checklist, not across the text
# --------------------------------------------------------------------------


def test_two_checklists_in_one_text_each_keep_their_rows():
    """PPA-1555 - the named test. A multi-ticket close-out is not eaten.

    Observed 18-SEP-2026: the session working PPA-1541, PPA-1546, PPA-1549 and
    PPA-1551 numbered its checklist 1 to 38 globally because the second
    ticket's rows 1 and 2 were dropped as duplicates of the first ticket's.
    Both sets are read now; the boundary is the row numbered 1 that follows a
    higher-numbered row.
    """
    rows = closeout.stated_rows([
        "PPA-1541",
        "1. The hook is wired. MET.",
        "2. A real pull request is armed. MET.",
        "PPA-1546",
        "1. pytest counts are quoted. NOT MET.",
        "2. The workflow is unchanged. MET.",
    ])

    assert [(r.number, r.verdict) for r in rows] == [
        (1, "MET"), (2, "MET"), (1, "NOT MET"), (2, "MET")], (
        "the second checklist's rows were dropped as duplicates of the first")
    assert [r.quoted for r in rows] == [
        "The hook is wired", "A real pull request is armed",
        "pytest counts are quoted", "The workflow is unchanged"], (
        "each row must carry its own quoted text, which is what pairs it")


def test_a_restatement_further_down_one_checklist_still_loses():
    """The rule PPA-1555 had to keep. Only a 1 opens a checklist, so a
    restatement of any other number is still the duplicate it always was."""
    rows = closeout.stated_rows([
        "1. The hook is wired. MET.",
        "2. A real pull request is armed. MET.",
        "3. pytest counts are quoted. MET.",
        "Condition 2 is restated here for the reader.",
        "2. A real pull request is armed, restated. NOT MET.",
    ])

    assert [(r.number, r.verdict) for r in rows] == [
        (1, "MET"), (2, "MET"), (3, "MET")], (
        "a narrative restatement must not displace the checklist's own row")


def test_a_second_checklist_is_paired_against_the_field_in_its_own_right():
    """The defect end to end: the rows are extracted, so they can pair.

    Before PPA-1555 the second ticket's rows never reached ``pair_rows`` at
    all, so its conditions read UNSTATED with their evidence in the same text.
    """
    rows = closeout.stated_rows([
        f"1. {QUOTES[0]}. MET.",
        f"2. {QUOTES[1]}. MET.",
        f"1. {QUOTES[2]}. NOT MET.",
    ])
    pairing = closeout.pair_rows(list(THREE), rows)

    assert pairing.verdicts == {1: "MET", 2: "MET", 3: "NOT MET"}


def test_a_comment_stating_no_row_is_not_part_of_the_close_out():
    """PPA-1412 carries a correction after its close-out and a merge-hash
    comment after that, and neither states a verdict row."""
    comments = [
        close_out("Route decision, recorded before implementation."),
        close_out("Definition of Done, condition by condition.",
                  "1. The workflow file is quoted from origin/main. NOT MET."),
        close_out("Correction to the close-out above: the branch commit is "
                  "236dfdb, not bb4ff5a."),
        comment_naming(SHA),
    ]
    stated, used, _defects = closeout.merged_verdicts(
        comments, ["[machine] The workflow file is quoted from origin/main."])

    assert stated == {1: "NOT MET"}
    assert len(used) == 1, "only the comment stating a row is part of it"


# --- PPA-1416 gate rejection, 13-SEP-2026: recency was the wrong selector ---


def test_a_correction_overrides_only_the_rows_it_names(never_shell_out):
    """Instance 1, PPA-1418, replayed. Its correction carried exactly one
    numbered row and the table reported the other twelve UNSTATED, while the
    close-out it corrected had reported twelve of thirteen MET."""
    jira = StubJira(dod=dod(*THREE), comments=[
        close_out("Definition of Done, condition by condition.",
                  f"1. {QUOTES[0]}. Met.", f"2. {QUOTES[1]}. Met.",
                  f"3. {QUOTES[2]}. Met."),
        close_out("Correction to the close-out above, on one row.",
                  f"2. {QUOTES[1]}, restated. NOT MET."),
    ])

    run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    assert rows_of(table_posted(jira)) == [
        (1, "MET"), (2, "NOT MET"), (3, "MET")], (
        "the correction replaced the checklist instead of amending it")


def test_the_base_is_the_most_complete_checklist_not_the_latest():
    stated, used, _defects = closeout.merged_verdicts([
        close_out(f"1. {QUOTES[0]}. Met.", f"2. {QUOTES[1]}. Met.",
                  f"3. {QUOTES[2]}. Met."),
        close_out(f"2. {QUOTES[1]}, corrected. NOT MET."),
    ], list(THREE))
    assert stated == {1: "MET", 2: "NOT MET", 3: "MET"}
    assert len(used) == 2


def test_a_later_consolidation_of_equal_length_becomes_the_base():
    """A consolidation restating every row supersedes the checklist it
    restates, which is how PPA-1418's own tables were repaired by hand.

    The verdicts hold either way - an equal-length checklist that is not the
    base is applied as an override over every row it carries and reaches the
    same answer - so what is pinned here is which comment is reported as the
    base, which is the only thing the tie-break decides.
    """
    first = close_out(f"1. {QUOTES[0]}. Met.", f"2. {QUOTES[1]}. Met.")
    consolidation = close_out(
        "Consolidated checklist.", f"1. {QUOTES[0]}. NOT MET.",
        f"2. {QUOTES[1]}. NOT MET.")
    stated, used, _defects = closeout.merged_verdicts(
        [first, consolidation], list(THREE[:2]))

    assert stated == {1: "NOT MET", 2: "NOT MET"}
    assert used == [consolidation], (
        "the earlier checklist was reported as the base")


def test_a_subset_never_replaces_the_checklist_it_corrects():
    """The property condition 1 names, asserted directly: a comment carrying
    fewer rows than the base cannot become the base."""
    base = close_out(f"1. {QUOTES[0]}. Met.", f"2. {QUOTES[1]}. Met.",
                     f"3. {QUOTES[2]}. Met.")
    subset = close_out(f"2. {QUOTES[1]}. NOT MET.")
    stated, _used, _defects = closeout.merged_verdicts(
        [base, subset], list(THREE))
    assert set(stated) == {1, 2, 3}, "rows outside the correction were dropped"


def test_corrections_apply_in_order_and_the_last_one_wins_a_row():
    stated, _used, _defects = closeout.merged_verdicts([
        close_out(f"1. {QUOTES[0]}. Met.", f"2. {QUOTES[1]}. Met."),
        close_out(f"2. {QUOTES[1]}. NOT MET."),
        close_out(f"2. {QUOTES[1]}, on reflection. Met."),
    ], list(THREE[:2]))
    assert stated == {1: "MET", 2: "MET"}


def test_two_full_checklists_that_disagree_resolve_to_the_later_one():
    """The named case PPA-1517 owes. A refused stop produces a second close-out,
    so two full checklists on one ticket is a common shape rather than an exotic
    one, and the rule is that the later one's verdicts win row by row.

    It holds twice over - the later equal-length checklist wins the tie-break
    and becomes the base, and a later checklist that is not the base overrides
    every row it carries - so the answer does not rest on the tie-break alone.
    """
    first = close_out("Close-out, first attempt.",
                      f"1. {QUOTES[0]}. Met.", f"2. {QUOTES[1]}. NOT MET.",
                      f"3. {QUOTES[2]}. Met.")
    second = close_out("Close-out, after the stop was refused.",
                       f"1. {QUOTES[0]}. NOT MET.", f"2. {QUOTES[1]}. Met.",
                       f"3. {QUOTES[2]}. NOT MET.")

    stated, used, _defects = closeout.merged_verdicts(
        [first, second], list(THREE))

    assert stated == {1: "NOT MET", 2: "MET", 3: "NOT MET"}, (
        "the earlier checklist's verdicts survived the later one")
    assert used == [second], "the later full checklist is the base"


def test_a_bulleted_close_out_is_read_as_readily_as_a_numbered_one():
    """adf_lines() reaches a list item's paragraph, so the shape of the
    checklist is not something a close-out has to get right."""
    body = {"type": "doc", "version": 1, "content": [{
        "type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "1. The condition. Met."}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "2. The other. NOT MET."}]}]}]}]}

    assert numbered(closeout.adf_lines(body)) == {
        1: "MET", 2: "NOT MET"}


def test_an_ordered_list_keeps_its_ordinal_through_adf():
    """A Markdown "1." reaches Jira as list structure, not as text (PPA-1531).

    The case above this one builds its "numbered" fixture as a bulletList whose
    text literally contains "1.", which is what a close-out types and not what
    Jira stores. It passed throughout, while every real numbered close-out
    arrived with nothing at the head of the line for _ROW_RE to match. Eight
    tickets merged on 18-SEP-2026 against numbered close-outs and seven were
    reported to carry none at all.

    The ordinal is read from attrs.order, not counted from one, because Jira
    ends the list at a code block and restarts the next orderedList at the
    number it left off - the shape the real PPA-1505 comment has, reproduced
    here.
    """
    body = {"type": "doc", "version": 1, "content": [
        {"type": "orderedList", "attrs": {"order": 1}, "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "\"The first condition.\" - MET."}]}]}]},
        {"type": "codeBlock", "content": [
            {"type": "text", "text": "the evidence that split the list"}]},
        {"type": "orderedList", "attrs": {"order": 2}, "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "\"The second condition.\" - NOT MET."}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "\"The third condition.\" - MET."}]}]}]}]}

    assert numbered(closeout.adf_lines(body)) == {
        1: "MET", 2: "NOT MET", 3: "MET"}


def test_a_code_block_inside_a_numbered_item_is_not_itself_numbered():
    """Only the first line an item produces carries the ordinal.

    A numbered condition whose evidence is a code block is the ordinary shape
    of a close-out in this estate, and numbering the code's first line too
    would file a second verdict under the next condition's number.
    """
    body = {"type": "doc", "version": 1, "content": [
        {"type": "orderedList", "attrs": {"order": 1}, "content": [
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "\"The condition.\" - MET."}]},
                {"type": "codeBlock", "content": [
                    {"type": "text", "text": "2. NOT MET in the evidence"}]}]}]}]}

    lines = closeout.adf_lines(body)
    assert lines[0].startswith("1. ")
    assert lines[1] == "2. NOT MET in the evidence", (
        "the code block keeps its own text and gains no ordinal")
    assert numbered(lines) == {1: "MET", 2: "NOT MET"}, (
        "the code line still reads as typed - this pins that the ordinal is "
        "added once, not that a code block is filtered")


def test_an_ordered_list_with_no_order_attribute_starts_at_one():
    """attrs.order is absent on a list Jira never split."""
    body = {"type": "doc", "version": 1, "content": [
        {"type": "orderedList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "\"The only condition.\" - MET."}]}]}]}]}

    assert numbered(closeout.adf_lines(body)) == {1: "MET"}


# --- the scope boundary ---------------------------------------------------

def test_which_status_a_merged_key_reaches_is_unchanged(never_shell_out):
    """The routing rule is still pure - no client, no credentials, no network.

    It does read the table since PPA-1459, and a call that passes none is the
    failure path: Client Validation, never Done."""
    assert plan_transition("In Progress")[0] == "Client Validation"
    assert plan_transition("To Do")[0] is None
    assert plan_transition("Client Validation")[0] is None


def test_an_unclassified_ticket_routes_to_client_validation_however_it_grades(
    never_shell_out
):
    """THREE carries no class token on any condition, so the class check
    settles this before the grade is consulted at all - which is the ordering
    PPA-1518 relies on to keep pre-12-SEP-2026 tickets out of the held outcome.

    Named for what it asserts since PPA-1518. It read "the table does not
    change where a merged key is routed", which stopped being true at PPA-1459
    and was simply passing on the unclassified branch.
    """
    jira = StubJira(dod=dod(*THREE), comments=[close_out(
        "1. The hook is wired. NOT MET.")])

    run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    assert never_shell_out[0][-2:] == ["--to", "Client Validation"], (
        "an unclassified condition needs a conductor whatever its verdict, so "
        "it is routed rather than held")


def test_an_unreadable_definition_of_done_still_comments_the_hash(
    never_shell_out
):
    jira = StubJira(dod="not adf at all", comments=[])

    outcomes = run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    assert outcomes[0].verdict == "MOVED"
    assert exit_code(outcomes) == 0
    assert table_posted(jira) is None
    assert any("Merged to main" in closeout.adf_text(p["body"])
               for _, p in jira.posts)


def test_a_table_that_cannot_be_posted_never_fails_the_run(never_shell_out):
    """The whole of the failure policy: it degrades to posting the hash."""
    calls = []

    def post(path, payload):
        calls.append(path)
        if closeout.TABLE_MARK in closeout.adf_text(payload["body"]):
            raise RuntimeError("Jira said no")

    jira = StubJira(dod=dod(*THREE), comments=[close_out("1. It. Met.")])

    outcomes = run(jira.get, post, ["PPA-1"], SHA, "46", DATE)

    assert outcomes[0].verdict == "MOVED"
    assert exit_code(outcomes) == 0
    assert "verdict table not posted" in outcomes[0].detail


def test_a_re_run_does_not_post_the_table_twice(never_shell_out):
    """The hash comment's guard looks for the full SHA, which the table
    carries only in its short form, so the table signs itself."""
    first = StubJira(dod=dod(*THREE), comments=[close_out("1. It. Met.")])
    run(first.get, first.post, ["PPA-1"], SHA, "46", DATE)
    posted = [{"body": p["body"]} for _, p in first.posts]

    again = StubJira(dod=dod(*THREE),
                     comments=[close_out("1. It. Met."), *posted])
    run(again.get, again.post, ["PPA-1"], SHA, "46", DATE)

    assert table_posted(again) is None


def test_the_issue_read_asks_for_the_definition_of_done(never_shell_out):
    jira = StubJira(dod=dod(*THREE))

    run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    assert jira.gets == ["/issue/PPA-1?fields=status,comment,customfield_10767"]


def test_a_dry_run_writes_no_table(never_shell_out):
    jira = StubJira(dod=dod(*THREE), comments=[close_out("1. It. NOT MET.")])

    outcomes = run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE, dry_run=True)

    assert jira.posts == []
    assert "would post a verdict table" in outcomes[0].detail


# --------------------------------------------------------------------------
# PPA-1456 — a branch carries two tickets and the merge closes out both
# --------------------------------------------------------------------------

def test_pr_59_closes_out_both_keys_it_carried():
    """The live case. PR #59 shipped PPA-1427 and PPA-1434 on a branch named
    for PPA-1427 alone; PPA-1434 was left at In Progress with no hash comment
    and nothing saying so, until a hand read caught it."""
    message = (
        "fix: Bar check at dispatch; malformed line warns "
        "(PPA-1427, PPA-1434) (#59)\n\n"
        "Both tickets change .claude/hooks/transition_on_prompt.py, so they\n"
        "were planned together and made in one pass over that file.\n"
    )
    assert close_out_keys("ppa-1427-bar-check", message) == [
        "PPA-1427", "PPA-1434"]
    assert close_out_keys(None, message) == ["PPA-1427", "PPA-1434"]


def test_the_branch_key_leads_and_is_never_duplicated():
    """The branch's own key is first whether or not the subject repeats it."""
    message = "fix: a thing (PPA-1434, PPA-1427) (#59)"
    assert close_out_keys("ppa-1427-slug", message) == ["PPA-1427", "PPA-1434"]


def test_a_one_ticket_branch_is_unchanged():
    """The ordinary shape behaves exactly as it did before PPA-1456."""
    message = "fix: derive the key from the branch name (PPA-1376) (#173)"
    assert close_out_keys("ppa-1376-slug", message) == ["PPA-1376"]
    assert close_out_keys(None, message) == ["PPA-1376"]


def test_a_subject_with_no_key_contributes_nothing():
    assert close_out_keys(None, "chore: bump a pin (#88)") == []
    assert close_out_keys("ppa-99-x", "chore: bump a pin (#88)") == ["PPA-99"]


def test_a_second_key_never_comes_from_body_prose():
    """PPA-1375 stands where PPA-1456 widened around it. A second key reaches
    the close-out from the branch name, the subject or a commit subject - never
    from a paragraph citing a ticket as provenance."""
    assert close_out_keys("ppa-1376-slug", PROVENANCE_BODY) == ["PPA-1376"]

    prose = (
        "fix: one ticket's work (PPA-1400) (#90)\n\n"
        "This builds on PPA-1399 and supersedes the approach in PPA-1398.\n"
        "Neither shipped anything in this merge.\n"
    )
    assert close_out_keys("ppa-1400-slug", prose) == ["PPA-1400"]


def test_every_derived_key_is_commented_and_transitioned(monkeypatch):
    """Both keys receive the hash comment and the transition, not just the
    key the branch is named after."""
    posted, moved = [], []
    issue = {"fields": {"status": {"name": "In Progress"},
                        "comment": {"comments": []},
                        "customfield_10767": None}}

    class Proc:
        returncode = 0
        stdout = "moved"
        stderr = ""

    monkeypatch.setattr(closeout.subprocess, "run",
                        lambda cmd, **kw: moved.append(cmd) or Proc())
    outcomes = closeout.run(
        lambda path: issue,
        lambda path, body: posted.append(path),
        ["PPA-1427", "PPA-1434"], "abc1234def", "59", "16-SEP-2026")

    assert [o.key for o in outcomes] == ["PPA-1427", "PPA-1434"]
    assert [o.verdict for o in outcomes] == ["MOVED", "MOVED"]
    assert posted == ["/issue/PPA-1427/comment", "/issue/PPA-1434/comment"]
    assert [c[c.index("--keys") + 1] for c in moved] == [
        "PPA-1427", "PPA-1434"]


# --------------------------------------------------------------------------
# PPA-1459 — Auto-Done
#
# pt-backlog section Auto-Done: a ticket whose conditions are all [machine] and
# all reported met closes to Done with no conductor hop. The ruling, recorded
# 12-SEP-2026: the conductor gate is a scheduling step, not a judgement step.
# PPA-1418 is the case that paid for it - 13 conditions, every one
# machine-checkable and met with evidence, and the hop was ceremony.
# --------------------------------------------------------------------------

ALL_MACHINE = dod("[machine] pytest counts for scripts/ are quoted.",
                  "[machine] No file outside this repository is edited.")
ALL_MET = [close_out("Definition of Done, condition by condition.",
                     "1. pytest counts. Met.", "2. No file outside. Met.")]


def test_a_machine_only_ticket_all_met_closes_to_done(never_shell_out):
    """The four conditions hold together, so the hop is not needed."""
    target, reason, _failures = plan_transition("In Progress",
                                     build_table(ALL_MACHINE, ALL_MET))

    assert target == "Done"
    assert "Auto-Done" in reason and "all 2 conditions" in reason

    stub = StubJira(status="In Progress", dod=ALL_MACHINE, comments=ALL_MET)
    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert outcomes[0].verdict == "MOVED"
    assert never_shell_out[0][-4:] == ["--keys", "PPA-1", "--to", "Done"]


@pytest.mark.parametrize(("why", "status", "table_dod", "comments"), [
    ("not at In Progress", "To Do", ALL_MACHINE, ALL_MET),
    ("no condition at all", "In Progress", None, ALL_MET),
    ("a condition is not [machine]", "In Progress",
     dod("[machine] a.", "[conductor] b."), ALL_MET),
    ("a condition is not reported met", "In Progress", ALL_MACHINE,
     [close_out("1. pytest counts. Met.", "2. No file outside. NOT MET.")]),
])
def test_each_of_the_four_failing_on_its_own_withholds_done(
        why, status, table_dod, comments):
    """Each of the four conditions fails alone; none of them reaches Done."""
    target, _reason, _failures = plan_transition(status, build_table(table_dod, comments))
    assert target != "Done", why
    assert target in (None, "Client Validation"), why


@pytest.mark.parametrize(("case", "table_dod", "comments"), [
    ("no class token", dod("pytest counts are quoted."), ALL_MET),
    ("[conductor]", dod("[conductor] the voice is consistent."), ALL_MET),
    ("[observer]", dod("[observer] the first ticket to close is named."),
     ALL_MET),
    ("empty Definition of Done", dod(), ALL_MET),
    ("absent Definition of Done", None, ALL_MET),
])
def test_a_condition_the_merge_cannot_evidence_routes_to_client_validation(
        case, table_dod, comments):
    """Outcome 2. A condition carrying no class token is not a [machine]
    condition - classes are forward-only from 12-SEP-2026, so most open
    tickets carry none and hold here, which is the safe direction.

    The last two cases are not gradeable at all rather than gradeable and
    failed, which is why they sit here and not with outcome 3: a machine that
    found no condition has found no failing condition either."""
    target, reason, failures = plan_transition(
        "In Progress", build_table(table_dod, comments))

    assert target == "Client Validation", f"{case}: {reason}"
    assert failures == [], f"{case}: a routed ticket reported held conditions"


@pytest.mark.parametrize("failure", [
    None,                                   # the table could not be built
    "malformed",                            # a Definition of Done of the wrong shape
])
def test_a_failure_path_routes_to_client_validation_never_done(failure):
    """No failure path may produce Done. Holding a finished ticket costs a
    conductor hop; closing an unfinished one costs a false record."""
    table = None if failure is None else build_table("not adf at all", ALL_MET)
    target, _reason, _failures = plan_transition("In Progress", table)
    assert target == "Client Validation"


def test_an_unparseable_verdict_table_never_reaches_done(monkeypatch):
    """safe_table() returns None when build_table raises, and None routes to
    Client Validation rather than failing the merge or closing the ticket."""
    monkeypatch.setattr(closeout, "build_table",
                        lambda dod, comments: (_ for _ in ()).throw(
                            ValueError("unparseable")))

    assert closeout.safe_table(ALL_MACHINE, ALL_MET) is None
    assert plan_transition("In Progress", None)[0] == "Client Validation"


def test_a_jira_read_failure_transitions_nothing(never_shell_out):
    """The read fails before any routing, so nothing is commented and nothing
    is moved - least of all to Done."""
    def boom(path):
        raise closeout.urllib.error.URLError("unreachable")

    outcomes = run(boom, lambda p, b: None, ["PPA-1"], SHA, "3", DATE)

    assert outcomes[0].verdict == "FAILED"
    assert never_shell_out == []


def test_the_hash_comment_is_posted_before_any_done_hop(monkeypatch):
    """The graduation gate's second requirement is met at the moment the status
    changes: close_out() posts the hash, then the table, then transitions."""
    order = []
    stub = StubJira(status="In Progress", dod=ALL_MACHINE, comments=ALL_MET)

    def post(path, payload):
        order.append(("comment", path))
        return stub.post(path, payload)

    def shell(argv, **kwargs):
        order.append(("transition", argv[-1]))
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(closeout.subprocess, "run", shell)
    run(stub.get, post, ["PPA-1"], SHA, "3", DATE)

    assert order[0] == ("comment", "/issue/PPA-1/comment")
    assert order[-1] == ("transition", "Done")
    assert [kind for kind, _ in order].index("transition") == len(order) - 1


def test_nothing_in_this_change_can_reach_reopened():
    """A rejection is a judgement no workflow observes, and Client Validation
    to Reopened stays with the conductor."""
    statuses = ["In Progress", "To Do", "Done", "Client Validation",
                "Reopened", "BLOCKED", ""]
    tables = [None, build_table(None, []), build_table(ALL_MACHINE, ALL_MET),
              build_table(dod("[conductor] a."), [close_out("1. a. Met.")]),
              build_table(dod("[machine] a."), [close_out("1. a. NOT MET.")])]
    reachable = {plan_transition(s, t)[0] for s in statuses for t in tables}

    assert reachable == {None, "Client Validation", "Done"}
    assert "Reopened" not in reachable


# --------------------------------------------------------------------------
# PPA-1464 — every key the merge carried, and a partial close-out that says so
#
# Two real merges are the fixtures, quoted rather than invented. The first is
# the defect's own case; the second is the stacked pair that produced it twice.
# --------------------------------------------------------------------------

#: peech-skills PR #207, squash-merged as e8a0fc4 at 2026-09-16T16:08:43Z. Four
#: tickets on one branch, five commits, and a subject naming one of them. The
#: run three seconds later moved PPA-1451 and concluded success; PPA-1453,
#: PPA-1457 and PPA-1460 were still at In Progress with their work on main.
#:
#: Subject and bullets are verbatim from the merge commit. The commit bodies
#: between the bullets are elided - they are prose, and their absence is what
#: makes this fixture a test of the bullets rather than of the prose.
PR_207_BRANCH = "ppa-1451-1453-1457-1460"
PR_207_MESSAGE = (
    "fix: correct a closed-ticket citation and name the no-merge hop owner "
    "(PPA-1451) (#207)\n"
    "\n"
    "* fix: correct a closed-ticket citation and name the no-merge hop owner "
    "(PPA-1451)\n"
    "\n"
    "pt-backlog cited PPA-1347 as open coverage for the In Progress hook\n"
    "question; it closed Done on 09-SEP-2026.\n"
    "\n"
    "* fix: split the standing findings condition so Auto-Done is reachable "
    "(PPA-1457)\n"
    "\n"
    "* feat: carry three conductor rules in the skills that own them "
    "(PPA-1453)\n"
    "\n"
    "* fix: pin the Code Terminal label to the repository and require a "
    "context directive (PPA-1460)\n"
    "\n"
    "* fix: correct the third site of the stale PPA-1347 citation (PPA-1451)\n"
)

#: Branch-name order, which is the order key_sources() reports because the
#: branch name is read first. The commit subjects arrive 1451, 1457, 1453, 1460.
PR_207_KEYS = ["PPA-1451", "PPA-1453", "PPA-1457", "PPA-1460"]


def test_pr_207_yields_all_four_keys_from_its_commit_subjects():
    """The production path. The workflow supplies no head ref, so the branch
    name is unavailable and the subject names one of the four tickets - the
    commit subjects are the only source that reaches the other three."""
    assert sorted(close_out_keys(None, PR_207_MESSAGE)) == sorted(PR_207_KEYS)


def test_pr_207_yields_all_four_keys_from_its_branch_name_alone():
    """A four-ticket branch is named for all four. ``ppa-1451-1453-1457-1460``
    read as PPA-1451 until PPA-1464, which is one of the two sources that
    failed on this merge."""
    assert keys_from_branch(PR_207_BRANCH) == PR_207_KEYS


def test_pr_207_reports_where_each_of_its_keys_came_from():
    """Condition 1: every key and the source that produced it. PPA-1451 is
    carried by all three sources and the other three by two, and an operator
    reading the run can tell which claim is which."""
    sources = key_sources(PR_207_BRANCH, PR_207_MESSAGE)

    assert sorted(sources) == sorted(PR_207_KEYS)
    assert sources["PPA-1451"] == ["branch name", "squash subject",
                                   "commit subject"]
    for key in ("PPA-1453", "PPA-1457", "PPA-1460"):
        assert sources[key] == ["branch name", "commit subject"], key


def test_pr_207s_citation_of_a_closed_ticket_contributes_no_key():
    """PPA-1347 appears twice in this message and shipped nothing in it: once
    in a commit body, and once inside a commit *subject* as the thing being
    corrected. Neither is its own work, and PPA-1375's bar has to hold in both
    places or the defect simply moves down a level."""
    assert PR_207_MESSAGE.count("PPA-1347") == 2, "both citations are present"
    assert "* fix: correct the third site of the stale PPA-1347 citation " \
           "(PPA-1451)\n" in PR_207_MESSAGE, "the subject-level citation"

    assert "PPA-1347" not in close_out_keys(PR_207_BRANCH, PR_207_MESSAGE)
    assert "PPA-1347" not in keys_from_commit_subjects(PR_207_MESSAGE)


def test_a_commit_subject_names_its_own_work_in_its_trailing_parentheses():
    """The description is not read. Both shapes here are real: PR #207's fifth
    subject cites a closed ticket, and main's own e4b7dce carries two keys."""
    assert own_keys_in(
        "fix: correct the third site of the stale PPA-1347 citation (PPA-1451)"
    ) == ["PPA-1451"]
    assert own_keys_in(
        "fix: Bar check at dispatch; malformed line warns (PPA-1427, PPA-1434)"
    ) == ["PPA-1427", "PPA-1434"]
    assert own_keys_in("chore: no key at all") == []


#: peech-pmo-automation PR #64, squash-merged as 91645d0. Its branch
#: ppa-1459-auto-done was cut from ppa-1456-two-ticket-branch rather than from
#: main, because both tickets edit close_out() and the batch rule puts one pass
#: over one file. So one squash carries two tickets' commits, and PPA-1456's
#: own pull request #63 never merged - the lower ticket of a stacked pair can
#: be left with no squash of its own.
STACKED_BRANCH = "ppa-1459-auto-done"
STACKED_MESSAGE = (
    "feat: Auto-Done in the merge close-out (PPA-1459) (#64)\n"
    "\n"
    "* fix: derive a pull request's keys from its commit subjects too "
    "(PPA-1456)\n"
    "\n"
    "The branch name alone matched one ticket, so the second ticket on a\n"
    "two-ticket branch was invisible to both readers.\n"
    "\n"
    "* feat: Auto-Done in the merge close-out (PPA-1459)\n"
    "\n"
    "pt-backlog section Auto-Done says a ticket whose conditions are all\n"
    "[machine] and all reported met closes to Done with no conductor hop.\n"
)


def test_a_stacked_squash_finds_both_tickets_it_carried():
    """The lower ticket of the pair reaches the close-out on the upper
    ticket's squash, which is the only squash it ever gets. Neither the branch
    name nor the subject names PPA-1456."""
    assert keys_from_branch(STACKED_BRANCH) == ["PPA-1459"]
    assert key_from_subject(STACKED_MESSAGE) == "PPA-1459"
    assert close_out_keys(STACKED_BRANCH, STACKED_MESSAGE) == [
        "PPA-1459", "PPA-1456"]


def test_no_key_a_stacked_squash_carried_is_dropped_unnamed(
        monkeypatch, capsys, never_shell_out):
    """Condition 4. Either a carried key is transitioned, or it is named in the
    output with the reason - never neither. PPA-1456 is at Client Validation
    here, so it is found, skipped, and reported rather than silently left
    behind. It was To Do until PPA-1601, which walks a To Do key forward."""
    statuses = {"PPA-1459": "In Progress", "PPA-1456": "Client Validation"}

    def get(path):
        key = path.split("/")[2].split("?")[0]
        return {"fields": {"status": {"name": statuses[key]},
                           "comment": {"comments": []},
                           "customfield_10767": None}}

    monkeypatch.setattr(closeout, "make_client", lambda creds: (get, _post))
    monkeypatch.setattr(closeout, "load_credentials", lambda: {})
    monkeypatch.setattr(closeout, "merge_message", lambda: STACKED_MESSAGE)
    monkeypatch.setattr(closeout.subprocess, "run", _moved)

    code = closeout.main(["--sha", SHA, "--head-ref", STACKED_BRANCH])
    out = capsys.readouterr().out

    assert code == PARTIAL_EXIT, "a carried key was not transitioned"
    assert "NOT TRANSITIONED: 1 of 2 key(s)" in out
    assert "PPA-1456" in out.split("NOT TRANSITIONED")[1], (
        "the key it carried and did not move is named after the heading")
    assert "'Client Validation'" in out, (
        "and the reason it was not moved rides with it")


def _post(path, payload):
    return {}


def _moved(argv, **kwargs):
    return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")


def test_the_run_names_every_key_and_its_source_before_attempting_anything(
        monkeypatch, capsys):
    """Condition 1, end to end. The sources are printed from the derivation, so
    a run that dies part way through has still said what it was working from."""
    monkeypatch.setattr(closeout, "make_client", lambda creds: (
        lambda path: {"fields": {"status": {"name": "In Progress"},
                                 "comment": {"comments": []},
                                 "customfield_10767": None}}, _post))
    monkeypatch.setattr(closeout, "load_credentials", lambda: {})
    monkeypatch.setattr(closeout, "merge_message", lambda: PR_207_MESSAGE)
    monkeypatch.setattr(closeout.subprocess, "run", _moved)

    closeout.main(["--sha", SHA, "--head-ref", PR_207_BRANCH])
    out = capsys.readouterr().out

    assert "found 4 key(s)" in out
    for key in PR_207_KEYS:
        assert f"{key:<10} found in " in out, key
    assert "found in branch name, squash subject, commit subject" in out
    # Every key moved, so nothing is reported as left behind.
    assert "NOT TRANSITIONED" not in out


def test_found_and_transitioned_differs_from_found_and_skipped():
    """Condition 2. The two outcomes are distinguishable by exit code, and a
    skip is still not a failure."""
    moved = [closeout.Outcome("PPA-1", "MOVED", "ok")]
    skipped = [closeout.Outcome("PPA-1", "MOVED", "ok"),
               closeout.Outcome("PPA-2", "SKIPPED", "not transitioned - To Do")]
    failed = [closeout.Outcome("PPA-1", "FAILED", "read failed")]

    assert exit_code(moved) == OK
    assert exit_code(skipped) == PARTIAL_EXIT
    assert exit_code(failed) == FAILED_EXIT
    assert OK != PARTIAL_EXIT != FAILED_EXIT


def test_transitioned_reads_a_dry_run_as_having_moved_nothing_real():
    """A dry run writes nothing, so COMMENTED is what it reports for a key it
    would have moved. It counts as transitioned here because the alternative is
    every dry run reporting itself as partial, which reports nothing."""
    assert transitioned(closeout.Outcome("PPA-1", "MOVED", ""))
    assert transitioned(closeout.Outcome("PPA-1", "COMMENTED", ""))
    assert not transitioned(closeout.Outcome("PPA-1", "SKIPPED", ""))
    assert not transitioned(closeout.Outcome("PPA-1", "FAILED", ""))


def test_a_commit_subject_must_be_a_bullet_in_the_commit_form():
    """Both halves of SUBJECT_BULLET_RE earn their place. A bullet that is not
    a commit subject is a markdown list in a body; a commit-form line that is
    not a bullet is a body paragraph that happens to open with a word."""
    assert keys_from_commit_subjects(
        "s (#1)\n\n* fix: real subject (PPA-1)\n") == ["PPA-1"]
    assert keys_from_commit_subjects(
        "s (#1)\n\n* see PPA-2 for background\n") == [], "not the commit form"
    assert keys_from_commit_subjects(
        "s (#1)\n\nfix: PPA-3 is cited here\n") == [], "not a bullet"


def test_the_subject_line_itself_is_never_read_as_a_commit_subject():
    """The first line is the squash subject and has its own reader. Reading it
    twice would double-count rather than mislead, but the sources it reports
    would be wrong."""
    message = "* fix: a subject that looks like a bullet (PPA-1) (#2)\n"
    assert keys_from_commit_subjects(message) == []
    assert key_sources(None, message) == {"PPA-1": ["squash subject"]}


def test_the_workflow_step_name_matches_what_the_step_does():
    """Condition 6. The step claimed every key while closing out one. It now
    reports the ones it does not, and the name says so."""
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows"
                / "merge-close-out.yml").read_text()

    assert "Close out every PPA key the merge carried, and report any it does not" in workflow
    assert "python .peech-ci-workflows/scripts/pr_merge_close_out.py" in workflow


# --- a close-out written as a Markdown table (PPA-1489) ---------------------
#
# Jira stores a Markdown table as an ADF `table` node, so the pipes the author
# typed are gone by the time the workflow reads the comment. Before PPA-1489 a
# row's cells arrived as separate paragraphs and the number cell carried no
# delimiter, so `_ROW_RE` matched nothing and the checklist read as absent.
# Measured on the four close-outs posted 16-SEP and 17-SEP-2026.


def adf_table(rows, header=("#", "Condition", "Verdict", "Evidence")):
    """An ADF table node of the shape Jira stores a Markdown table as.

    Header cells are `tableHeader` and body cells are `tableCell`, each holding
    a paragraph - read off comment 29101 on PPA-1481 rather than assumed.
    """
    def row(cells, kind):
        return {"type": "tableRow", "content": [
            {"type": kind, "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": str(cell)}]}]} for cell in cells]}

    content = [row(header, "tableHeader")] if header else []
    content += [row(cells, "tableCell") for cells in rows]
    return {"type": "doc", "version": 1,
            "content": [{"type": "table", "content": content}]}


#: PPA-1481's real close-out, comment 29101, posted 2026-09-17T11:44 and read
#: by nothing. Carried verbatim: every cell below is the stored text.
PPA_1481_CLOSE_OUT = (
    ("1",
     'PNIIG-74 and PNIIG-177 each carry six Phase children; a live JQL read quoted',
     "MET", "Below"),
    ("2",
     'PNIIG-73 and PNIIG-176 unchanged in key, summary and parent; nothing re-parented',
     "MET", "Below"),
    ("3",
     "Exactly ten issues created, all of type Phase; the run's count line quoted",
     "MET", "Below"),
    ("4",
     'No Project, Epic or Story created in any Jira project',
     "MET", "Below"),
    ("5",
     'Scope Classification reads In Scope on all ten, by read-back',
     "MET", "Below"),
    ("6",
     'Every date and budget field unset on all ten',
     "MET", "Below"),
    ("7",
     'Dry by default, writes nothing without --live; the close-out names which script and why',
     "MET", "Below"),
    ("8",
     'The suite passes, with a named case for each behaviour',
     "MET", "51 passed"),
    ("9",
     'No Jira issue outside the three written to; no scope-boundary file modified',
     "MET", "Below"),
    ("10",
     'Every finding names one of the three outcomes',
     "MET", "Below"),
)


def test_ppa_1481s_real_close_out_table_yields_ten_met_rows():
    """The case this change exists for. Ten conditions, every one [machine] and
    every one reported met, posted nineteen minutes before the merge and read
    as an absent checklist. It qualified for Auto-Done exactly."""
    stated = numbered(closeout.adf_lines(adf_table(PPA_1481_CLOSE_OUT)))

    assert stated == dict.fromkeys(range(1, 11), "MET")
    assert len(stated) == 10


def test_a_table_close_out_agrees_with_the_same_content_as_numbered_rows():
    """The shape a close-out is written in must not change the verdict map."""
    rows = (("1", "The first condition", "MET", "Below"),
            ("2", "The second condition", "NOT MET", "Below"),
            ("3", "The third condition", "NOT YET MET", "Below"))
    prose = {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        for text in ("1. The first condition. MET.",
                     "2. The second condition. NOT MET.",
                     "3. The third condition. NOT YET MET.")]}

    as_table = numbered(closeout.adf_lines(adf_table(rows)))
    as_prose = numbered(closeout.adf_lines(prose))

    assert as_table == as_prose == {1: "MET", 2: "NOT MET", 3: "NOT YET MET"}


def test_a_not_met_cell_reads_not_met_and_never_met():
    """The whole-cell anchor is a stronger guard than the sentence boundary it
    mirrors: 'NOT MET' cannot match '^MET$' at all, so the answer does not
    depend on the alternation order."""
    body = adf_table((("1", "A condition", "NOT MET", "Below"),
                      ("2", "Another", "not met", "Below")))

    assert numbered(closeout.adf_lines(body)) == {
        1: "NOT MET", 2: "NOT MET"}


def test_a_verdict_word_inside_a_condition_cell_yields_no_verdict():
    """A verdict must occupy a whole cell. This is the pipe-delimited
    equivalent of the sentence boundary _VERDICT_RE applies, and it carries the
    same reason: it stops the restated condition being read as its own verdict.
    """
    body = adf_table((("1", "The condition is reported not met", "", "Below"),
                      ("2", "A condition naming MET in its own prose", "", "x")))

    assert numbered(closeout.adf_lines(body)) == {}


def test_a_hedged_verdict_cell_yields_no_verdict():
    """PPA-1473 comment 29095 row 3 reads 'NOT MET in part'. The whole-cell
    rule refuses to guess which verdict that is. The row falls to UNSTATED,
    which is not MET, so it holds Auto-Done back either way."""
    body = adf_table((("1", "A condition", "NOT MET in part", "Below"),
                      ("2", "Another", "MET", "Below")))

    assert numbered(closeout.adf_lines(body)) == {2: "MET"}


def test_the_header_row_yields_nothing():
    """'#' is not a condition number, so the header falls out of the
    first-cell rule without being named."""
    header_only = adf_table((), header=("#", "Condition", "Verdict", "Evidence"))

    assert numbered(closeout.adf_lines(header_only)) == {}


def test_a_separator_row_yields_nothing():
    """ADF drops the separator, so this only arises for a table typed as
    literal text - which table_cells() reads too."""
    assert numbered(["| --- | --- | --- | --- |",
                                 "|:---|:---:|---:|---|"]) == {}


def test_a_table_typed_as_literal_text_is_read_too():
    """A close-out pasted into a code block keeps its pipes, so the same rule
    has to reach it."""
    assert numbered(["| # | Condition | Verdict |",
                                 "| --- | --- | --- |",
                                 "| 1 | The first | MET |",
                                 "| 2 | The second | NOT MET |"]) == {
        1: "MET", 2: "NOT MET"}


def test_emphasis_markers_around_a_verdict_cell_are_stripped():
    """'**MET**' and '`MET`' are the same verdict as 'MET'."""
    body = adf_table((("1", "A condition", "**MET**", "Below"),
                      ("2", "Another", "`NOT MET`", "Below")))

    assert numbered(closeout.adf_lines(body)) == {
        1: "MET", 2: "NOT MET"}


def test_a_comment_carrying_both_a_table_and_a_numbered_list_parses_both():
    """One close-out may state some rows in a table and the rest in prose."""
    body = {"type": "doc", "version": 1, "content": [
        adf_table((("1", "The first condition", "MET", "Below"),))["content"][0],
        {"type": "paragraph", "content": [
            {"type": "text", "text": "2. The second condition. NOT MET."}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "3. The third. MET."}]}]}]}]}

    assert numbered(closeout.adf_lines(body)) == {
        1: "MET", 2: "NOT MET", 3: "MET"}


def test_the_first_statement_of_a_number_still_wins_across_shapes():
    """verdicts_in()'s first-wins rule is not weakened by the table branch: a
    row restated later in the narrative must not overwrite the checklist."""
    body = {"type": "doc", "version": 1, "content": [
        adf_table((("1", "The condition", "MET", "Below"),))["content"][0],
        {"type": "paragraph", "content": [
            {"type": "text", "text": "1. Restating the condition. NOT MET."}]}]}

    assert numbered(closeout.adf_lines(body)) == {1: "MET"}


def test_a_row_whose_number_cell_is_not_bare_digits_yields_nothing():
    """'Condition 1' and '1.' in the number cell are not the shape the rule
    names. Keeping it strict is what makes the header and separator rows fall
    out without a special case."""
    body = adf_table((("Condition 1", "A condition", "MET", "Below"),
                      ("1.", "Another", "MET", "Below")))

    assert numbered(closeout.adf_lines(body)) == {}


# --------------------------------------------------------------------------
# PPA-1517 — a verdict is filed under the condition it quotes
# --------------------------------------------------------------------------
#
# The six cases the ticket names. The number a close-out types is a label; the
# condition text it quotes is the key. PPA-1479's amendment close-out numbered
# its two conditions 14 and 15 where the field carries them at 13 and 14, and
# every verdict from there on filed one row late - including one that read met
# on evidence written for something else.

#: Five conditions with no shared distinctive vocabulary, so a mis-pairing
#: cannot pass by accident. Written as the field carries them, class token and
#: all.
FIVE = (
    "[machine] The repo-wide rule runner passes, with its count quoted.",
    "[machine] No literal Sheet identifier appears in any committed source.",
    "[machine] The burndown notifier addresses each project manager by name.",
    "[machine] Every finding names one of the three outcomes.",
    "[machine] The Apps Script bundle is deployed and its version recorded.",
)

#: How a close-out quotes FIVE, abbreviated as a real one is.
FIVE_QUOTES = (
    "The repo-wide rule runner passes",
    "No literal Sheet identifier in committed source",
    "The burndown notifier addresses each project manager",
    "Every finding names one of the three outcomes",
    "The Apps Script bundle is deployed",
)


def paired(conditions, *lines):
    """The Pairing for one checklist stated as numbered prose lines."""
    return closeout.pair_rows(list(conditions), closeout.stated_rows(lines))


# --- case 1: order is not the key -----------------------------------------

def test_rows_quoted_out_of_order_pair_to_the_condition_each_one_quotes():
    """Case 1. A close-out is free to state its rows in any order; what files a
    verdict is the text, so the field's own order is restored on the way in."""
    pairing = paired(
        FIVE,
        f"3. {FIVE_QUOTES[2]}. NOT MET.",
        f"1. {FIVE_QUOTES[0]}. Met.",
        f"5. {FIVE_QUOTES[4]}. Met.",
        f"2. {FIVE_QUOTES[1]}. Met.",
        f"4. {FIVE_QUOTES[3]}. Met.",
    )

    assert pairing.verdicts == {1: "MET", 2: "MET", 3: "NOT MET",
                                4: "MET", 5: "MET"}
    assert pairing.defects == []


# --- case 2: the PPA-1479 off-by-one --------------------------------------

def test_a_checklist_numbered_one_off_pairs_correctly_and_says_so():
    """Case 2, and the measured failure. PPA-1479's close-out numbered its rows
    one past the field's numbering; under the old rule each verdict filed one
    condition late and the last row fell off the end entirely."""
    pairing = paired(
        FIVE,
        f"2. {FIVE_QUOTES[0]}. Met.",
        f"3. {FIVE_QUOTES[1]}. Met.",
        f"4. {FIVE_QUOTES[2]}. NOT MET.",
        f"5. {FIVE_QUOTES[3]}. Met.",
        f"6. {FIVE_QUOTES[4]}. Met.",
    )

    assert pairing.verdicts == {1: "MET", 2: "MET", 3: "NOT MET",
                                4: "MET", 5: "MET"}, (
        "the written numbers were used as the key")
    assert any("numbers rows differently" in d for d in pairing.defects), (
        f"the numbering mismatch was not reported: {pairing.defects}")
    assert any("row 2 is condition 1" in d for d in pairing.defects)


def test_the_old_rule_would_have_filed_every_verdict_one_row_late():
    """What case 2 costs when the number is the key, asserted rather than
    described: condition 1 reads unstated and its evidence lands on 2."""
    rows = closeout.stated_rows([
        f"2. {FIVE_QUOTES[0]}. Met.",
        f"3. {FIVE_QUOTES[1]}. NOT MET.",
    ])
    by_number = {row.number: row.verdict for row in rows}

    assert 1 not in by_number, "the old key left condition 1 unstated"
    assert by_number == {2: "MET", 3: "NOT MET"}
    assert paired(FIVE, f"2. {FIVE_QUOTES[0]}. Met.",
                  f"3. {FIVE_QUOTES[1]}. NOT MET.").verdicts == {
        1: "MET", 2: "NOT MET"}


# --- case 3: a row quoting nothing the field carries ------------------------

def test_a_row_quoting_no_condition_is_a_defect_and_files_no_verdict():
    """Case 3. The row names something the Definition of Done does not, so
    there is nothing to file it against and guessing is what this replaces."""
    pairing = paired(
        FIVE,
        f"1. {FIVE_QUOTES[0]}. Met.",
        "2. The invoice reconciliation spreadsheet balances to the penny. Met.",
    )

    assert pairing.verdicts == {1: "MET"}, "the unmatched row filed a verdict"
    assert any("matching no condition" in d for d in pairing.defects), (
        pairing.defects)
    assert any("invoice reconciliation" in d for d in pairing.defects), (
        "the defect does not quote the row it could not pair")


def test_an_unpairable_row_leaves_its_condition_unstated_in_the_table(
    never_shell_out
):
    """The consequence on the comment a conductor reads: UNSTATED, which is not
    MET, so the ticket cannot reach Done on it either."""
    jira = StubJira(dod=dod(*THREE), comments=[close_out(
        f"1. {QUOTES[0]}. Met.",
        f"2. {QUOTES[1]}. Met.",
        "3. Something the Definition of Done never mentions anywhere. Met.")])

    run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    body = table_posted(jira)
    assert rows_of(body) == [(1, "MET"), (2, "MET"), (3, "UNSTATED")]
    assert "did not pair cleanly" in closeout.adf_text(body)


# --- case 4: the row count disagrees with the field -------------------------

def test_a_row_count_differing_from_the_field_is_a_defect():
    """Case 4. Four rows against five conditions is a checklist that has not
    been written against the field, whatever each row pairs to."""
    pairing = paired(FIVE, *[f"{i}. {q}. Met."
                             for i, q in enumerate(FIVE_QUOTES[:4], 1)])

    assert pairing.verdicts == {1: "MET", 2: "MET", 3: "MET", 4: "MET"}
    assert any("states 4 row(s)" in d and "5 condition(s)" in d
               for d in pairing.defects), pairing.defects


def test_more_rows_than_conditions_is_the_same_defect():
    pairing = paired(THREE, *[f"{i}. {q}. Met."
                              for i, q in enumerate(QUOTES, 1)],
                     "4. A fourth row the field does not carry at all. Met.")

    assert any("states 4 row(s)" in d and "3 condition(s)" in d
               for d in pairing.defects), pairing.defects


# --- case 6: a condition nothing quotes ------------------------------------

def test_a_condition_no_row_quotes_reads_unstated(never_shell_out):
    """Case 6. The close-out declined to state it, so the table says so rather
    than assuming it met - which is the direction the whole mechanism leans."""
    jira = StubJira(dod=dod(*THREE), comments=[close_out(
        f"1. {QUOTES[0]}. Met.", f"3. {QUOTES[2]}. Met.")])

    run(jira.get, jira.post, ["PPA-1"], SHA, "46", DATE)

    assert rows_of(table_posted(jira)) == [
        (1, "MET"), (2, "UNSTATED"), (3, "MET")]
    assert never_shell_out[0][-2:] == ["--to", "Client Validation"], (
        "an unstated condition is not a met one")


# --- the pairing rule itself ------------------------------------------------

def test_the_pairing_key_is_the_quoted_text_and_not_the_number():
    """The property, stated as directly as it can be: hold the quoted text
    still and vary only the numbers, and every verdict lands where it did."""
    by_field_numbers = paired(THREE, *[f"{i}. {q}. Met."
                                       for i, q in enumerate(QUOTES, 1)])
    by_wrong_numbers = paired(THREE, f"9. {QUOTES[0]}. Met.",
                              f"7. {QUOTES[1]}. Met.",
                              f"8. {QUOTES[2]}. Met.")

    assert by_field_numbers.verdicts == by_wrong_numbers.verdicts == {
        1: "MET", 2: "MET", 3: "MET"}


def test_one_condition_takes_one_row():
    """Two rows quoting the same condition cannot both file against it. The
    stronger quote claims it and the weaker one is reported as unpaired."""
    pairing = paired(THREE, f"1. {QUOTES[0]}. Met.",
                     f"2. {QUOTES[0]} and the wiring is quoted. NOT MET.")

    assert len(pairing.verdicts) <= 2
    assert 1 in pairing.verdicts
    assert pairing.defects, "a second row for one condition went unreported"


def test_a_row_quoting_nothing_at_all_pairs_to_nothing():
    """A bare "4. MET." quotes no condition, so there is nothing to pair on.
    match_score returns 0.0 rather than matching the first condition going."""
    assert closeout.match_score("", THREE[0]) == 0.0
    assert closeout.match_score("the and of", THREE[0]) == 0.0, (
        "stopwords alone are not a quote")


def test_the_class_token_is_not_counted_as_shared_vocabulary():
    """Every condition opens '[machine]' and no row quoting one repeats it, so
    counting it would give every pair a free point of similarity."""
    assert closeout.match_score("[machine] something unrelated entirely",
                                FIVE[0]) == 0.0


def test_a_quote_may_abbreviate_but_may_not_invent():
    """The measure is one-directional. Dropping words from a quote costs
    nothing; adding words the condition does not carry is what costs."""
    condition = FIVE[0]
    assert closeout.match_score("repo-wide rule runner", condition) == 1.0
    assert closeout.match_score(
        "repo-wide rule runner alpha beta gamma delta", condition) < 0.5


# --- the extractor half -----------------------------------------------------

def test_stated_rows_carries_the_quoted_text_off_a_numbered_row():
    row, = closeout.stated_rows(["4. The hook is wired, with the wiring. MET."])

    assert (row.number, row.verdict) == (4, "MET")
    assert row.quoted == "The hook is wired, with the wiring"


def test_stated_rows_carries_the_quoted_text_off_a_table_row():
    rows = closeout.stated_rows(closeout.adf_lines(
        adf_table((("1", "The hook is wired", "MET", "Below"),))))

    assert [(r.number, r.quoted, r.verdict) for r in rows] == [
        (1, "The hook is wired", "MET")]


def test_the_two_extractors_reach_the_same_rows():
    """The separation PPA-1517 keeps: two source shapes, two adapters, one
    pairing function. A comment arrives as ADF and a turn's own output arrives
    as plain text, and the rows have to be indistinguishable by the time they
    reach pair_rows()."""
    text = "\n".join(f"{i}. {q}. MET." for i, q in enumerate(QUOTES, 1))
    from_text = closeout.stated_rows(text.splitlines())
    from_adf = closeout.stated_rows(closeout.adf_lines(
        close_out(*text.splitlines())["body"]))

    assert from_text == from_adf
    assert (closeout.pair_rows(list(THREE), from_text).verdicts
            == closeout.pair_rows(list(THREE), from_adf).verdicts
            == {1: "MET", 2: "MET", 3: "MET"})


def test_delegation_md_carries_the_close_out_shape_statement():
    """The other half of PPA-1517: the parser is widened and the shape a
    close-out must take is written where a session reads it before writing one.
    PPA-1609 moved the delegation rules out of CLAUDE.md into delegation.md,
    which every repository's CLAUDE.md imports.
    """
    block = (Path(__file__).resolve().parents[2] / "delegation.md").read_text()

    for sentence in (
        "Write one row per Definition of Done condition, in the field's own "
        "order.",
        "Each row carries the condition number, the condition text quoted from "
        "the Definition of Done field, the verdict MET or NOT MET, and the "
        "evidence.",
        "A Markdown table and a numbered list are both read.",
        "A row that does not quote its condition text cannot be paired, and is "
        "reported as unstated rather than filed.",
    ):
        assert sentence in block, sentence


# --------------------------------------------------------------------------
# PPA-1518 — the merge's three outcomes, as amended 17-SEP-2026
# --------------------------------------------------------------------------
#
# Done, Client Validation, or no transition at all. The third is the amendment:
# the original text routed a failed grade to Reopened, which is not reachable.
# Read live from the PPA workflow on 17-SEP-2026, a ticket at In Progress is
# offered seven transitions and none of them reaches Reopened - it is offered
# only from Client Validation, by "Client Rejected - Restart Work".

#: The seven transitions a PPA ticket at In Progress actually offers, read live
#: from PPA-1517 on 17-SEP-2026 through getTransitionsForJiraIssue. Carried as
#: data so the claim in plan_transition()'s docstring is checkable rather than
#: asserted.
LIVE_TARGETS_FROM_IN_PROGRESS = (
    "Info Provided", "Need More Info - Client", "BLOCKED",
    "Closed - Not Needed", "Done", "Client Validation", "To Do",
)

#: Two [machine] conditions and a close-out quoting them, one NOT MET.
MACHINE_ONE_UNMET = [close_out(
    "Definition of Done, condition by condition.",
    "1. pytest counts. Met.",
    "2. No file outside this repository is edited. NOT MET.")]


# --- outcome 1: Done -------------------------------------------------------

def test_all_machine_and_all_met_transitions_to_done(never_shell_out):
    """Named test 1. Unchanged by the amendment and re-asserted here so the
    three outcomes are pinned in one place."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE, comments=ALL_MET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert outcomes[0].verdict == "MOVED"
    assert never_shell_out[0][-2:] == ["--to", "Done"]
    assert exit_code(outcomes) == OK


# --- outcome 3: no transition ----------------------------------------------

def test_one_condition_not_met_applies_no_transition_and_comments(
    never_shell_out
):
    """Named test 2. The ticket is not finished, so Client Validation would
    assert something false and Reopened is not this workflow's to apply."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert never_shell_out == [], "a transition was fired on a failed grade"
    assert outcomes[0].verdict == "HELD"
    assert "not transitioned" in outcomes[0].detail
    assert held_posted(stub) is not None, "no comment named the failure"


def test_a_checklist_the_parser_could_not_read_applies_no_transition(
    never_shell_out
):
    """Named test 3. No verdict row anywhere on the ticket, so nothing was
    evidenced - which is not the same as evidenced and passed."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE, comments=[
        close_out("A close-out written as prose, stating no numbered row.")])

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert never_shell_out == []
    assert outcomes[0].verdict == "HELD"


def test_the_held_key_exits_partial_and_not_ok(never_shell_out):
    """A held key is one the run found and did not transition, which is what
    PARTIAL_EXIT means. It is not a failure: nothing went wrong in the run."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert exit_code(outcomes) == PARTIAL_EXIT
    assert not transitioned(outcomes[0])


def test_held_is_distinct_from_skipped(never_shell_out):
    """SKIPPED means the key was never graded; HELD means it was graded and
    failed. Collapsing them would hide the case this ticket exists for."""
    graded = StubJira(status="In Progress", dod=ALL_MACHINE,
                      comments=MACHINE_ONE_UNMET)
    ungraded = StubJira(status="Client Validation", dod=ALL_MACHINE,
                        comments=MACHINE_ONE_UNMET)

    held = run(graded.get, graded.post, ["PPA-1"], SHA, "3", DATE)[0]
    skipped = run(ungraded.get, ungraded.post, ["PPA-2"], SHA, "3", DATE)[0]

    assert held.verdict == "HELD" and skipped.verdict == "SKIPPED"
    assert held_posted(graded) is not None
    assert held_posted(ungraded) is None, "an ungraded key was commented on"


# --- the comment the held outcome posts ------------------------------------

def held_posted(jira):
    """The held comment's ADF body, or None."""
    for _path, payload in jira.posts:
        if closeout.HELD_MARK in closeout.adf_text(payload["body"]):
            return payload["body"]
    return None


def test_the_held_comment_names_every_condition_that_caused_it(
    never_shell_out
):
    """Named test 7. The conductor's next act is to decide what happens to this
    ticket, and a count does not support that."""
    dod_field = dod("[machine] pytest counts for scripts/ are quoted.",
                    "[machine] No file outside this repository is edited.",
                    "[machine] The workflow file is quoted from origin/main.")
    stub = StubJira(status="In Progress", dod=dod_field, comments=[close_out(
        "1. pytest counts. Met.",
        "2. No file outside this repository is edited. NOT MET.",
        "3. The workflow file is quoted from origin/main. NOT MET.")])

    run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    said = closeout.adf_text(held_posted(stub))
    assert "No file outside this repository is edited" in said
    assert "The workflow file is quoted from origin/main" in said
    assert "pytest counts for scripts/ are quoted" not in said, (
        "a met condition was named as having held the ticket")
    assert "2 Definition of Done condition(s) are not reported met" in said


def test_the_held_comment_on_an_absent_checklist_names_every_condition(
    never_shell_out
):
    """With no checklist at all, every condition is what held the ticket."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE, comments=[])

    run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    said = closeout.adf_text(held_posted(stub))
    assert "pytest counts for scripts/ are quoted" in said
    assert "No file outside this repository is edited" in said


def test_a_re_run_does_not_post_the_held_comment_twice(never_shell_out):
    first = StubJira(status="In Progress", dod=ALL_MACHINE,
                     comments=MACHINE_ONE_UNMET)
    run(first.get, first.post, ["PPA-1"], SHA, "3", DATE)
    posted = [{"body": p["body"]} for _, p in first.posts]

    again = StubJira(status="In Progress", dod=ALL_MACHINE,
                     comments=[*MACHINE_ONE_UNMET, *posted])
    run(again.get, again.post, ["PPA-1"], SHA, "3", DATE)

    assert held_posted(again) is None


def test_a_dry_run_holds_without_writing(never_shell_out):
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE, dry_run=True)

    assert stub.posts == []
    assert "would report 1 condition(s) holding this ticket" in outcomes[0].detail


def test_a_comment_failure_never_fails_the_merge(never_shell_out):
    """The held comment degrades exactly as the verdict table does: the routing
    decision stands whether or not the comment landed."""
    def post(path, payload):
        if closeout.HELD_MARK in closeout.adf_text(payload["body"]):
            raise RuntimeError("Jira said no")

    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)
    outcomes = run(stub.get, post, ["PPA-1"], SHA, "3", DATE)

    assert outcomes[0].verdict == "HELD"
    assert "held comment not posted" in outcomes[0].detail
    assert exit_code(outcomes) == PARTIAL_EXIT, "a comment failure is not a FAILED"


# --- outcome 2, and the ordering that keeps it ahead of outcome 3 -----------

@pytest.mark.parametrize(("case", "condition"), [
    ("[conductor]", "[conductor] the voice reads as one author."),
    ("[observer]", "[observer] the first ticket to close under this is named."),
    ("unclassified", "a condition authored before 12-SEP-2026."),
])
def test_a_non_machine_condition_routes_to_client_validation_even_when_unmet(
    case, condition, never_shell_out
):
    """Named tests 4, 5 and 6. Each of these is unmet as well as non-[machine],
    so the two outcomes compete and the class check has to win - otherwise
    every pre-12-SEP-2026 ticket is held rather than routed, which is the
    amendment's own carve-out."""
    stub = StubJira(status="In Progress", dod=dod(condition),
                    comments=[close_out("1. the condition. NOT MET.")])

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "3", DATE)

    assert never_shell_out[0][-2:] == ["--to", "Client Validation"], case
    assert outcomes[0].verdict == "MOVED", case
    assert held_posted(stub) is None, f"{case} was held rather than routed"


# --- the module names no status the workflow does not offer -----------------

def test_every_target_this_module_can_produce_is_offered_by_the_workflow():
    """Condition 6. Swept rather than sampled: every reachable target is
    checked against the live set, so a status added later cannot slip in
    unoffered."""
    statuses = ["In Progress", "To Do", "Done", "Client Validation",
                "Reopened", "BLOCKED", ""]
    tables = [None, build_table(None, []), build_table(ALL_MACHINE, ALL_MET),
              build_table(ALL_MACHINE, MACHINE_ONE_UNMET),
              build_table(dod("[conductor] a."), [close_out("1. a. Met.")]),
              build_table(ALL_MACHINE, [])]
    reachable = {plan_transition(s, t)[0] for s in statuses for t in tables}

    assert reachable == {None, "Client Validation", "Done"}
    for target in reachable - {None}:
        assert target in LIVE_TARGETS_FROM_IN_PROGRESS, target
    assert "Reopened" not in LIVE_TARGETS_FROM_IN_PROGRESS, (
        "the premise the amendment rests on")


def test_reopened_is_never_a_destination_this_module_can_name():
    """Condition 6's other half. Reopened appears in this module's prose - the
    docstring records why it is not a destination, and the held comment tells
    the conductor the same thing - so a text search finds it and proves
    nothing. What must hold is that it is never a status this module hands to
    pt_transition.py.
    """
    statuses = [name for name, value in vars(closeout).items()
                if name.startswith("MERGED_") and isinstance(value, str)]

    assert sorted(statuses) == ["MERGED_FROM", "MERGED_TO", "MERGED_TO_DONE"]
    for name in statuses:
        value = getattr(closeout, name)
        assert value != "Reopened", name
        assert value in LIVE_TARGETS_FROM_IN_PROGRESS or value == "In Progress", (
            f"{name} is {value!r}, which the live workflow does not offer")


def test_the_destination_is_resolved_by_label_not_by_a_transition_id():
    """Condition 6. This module names a status and hands it to
    pt_transition.py, which reads the live transition set and matches on the
    label - so no transition id exists here to go stale."""
    source = Path(closeout.__file__).read_text(encoding="utf-8")
    assert '"--to", target' in source or "'--to', target" in source or (
        '"--to", target]' in source) or "--to" in source

    transition = Path(closeout.SCRIPT).read_text(encoding="utf-8")
    assert 'norm(t["to"]["name"]) == norm(target)' in transition, (
        "pt_transition.py no longer resolves the destination by label")
    assert "transitions" in transition and "/transitions" in transition, (
        "pt_transition.py no longer reads the live transition set")


# --------------------------------------------------------------------------
# PPA-1556 - a held ticket gets a second reader
# --------------------------------------------------------------------------
#
# merge-close-out.yml reads a ticket's comments once, on the merge event. A
# close-out landing after that was invisible to it: PPA-1505 merged as 0a2daca
# at 11:51 and its verdict table was posted at 12:09; PPA-1541 merged as
# 4d41d5b at 17:48 and its close-out at 17:55. Both were recorded as absent and
# both were closed by hand. The hand hop is the workaround, not the fix.

#: The held comment a merge run leaves on a ticket it did not transition. The
#: mark is what the sweep keys on, so it is quoted from the module rather than
#: retyped - a fixture carrying a near-miss would pass for the wrong reason.
def held_comment():
    return close_out(
        "No transition was applied. 1 Definition of Done condition(s) are not "
        "reported met by the close-out.",
        f"Recorded on merge {SHA[:12]}, {closeout.HELD_MARK}.")


MACHINE = ("[machine] The hook is wired and the wiring is quoted.",
           "[machine] pytest counts are quoted and every change accounted for.")


def test_a_held_ticket_gaining_a_full_checklist_is_regraded_and_transitioned(
        never_shell_out):
    """PPA-1556 - the named test. The eighteen-minute case, replayed.

    The merge run read the comments before the checklist arrived and held the
    ticket. The sweep reads them again and applies the transition that run
    would have applied - Done here, because every condition is [machine] and
    every one is reported met.
    """
    jira = StubJira(dod=dod(*MACHINE), comments=[
        comment_naming(SHA),
        held_comment(),
        close_out("Definition of Done, condition by condition.",
                  "1. The hook is wired. MET.",
                  "2. pytest counts are quoted. MET."),
    ])

    outcome, = closeout.regrade_run(jira.get, jira.post, ["PPA-1"])

    assert outcome.verdict == "MOVED", outcome.detail
    assert never_shell_out[0][-2:] == ["--to", "Done"], (
        "the sweep reaches the status plan_transition() names, not a new one")
    posted, = [body for path, body in jira.posts if path.endswith("/comment")]
    text = closeout.adf_text(posted["body"])
    assert closeout.REGRADE_MARK in text, (
        "a status that moves hours after the merge needs a reason on the ticket")
    assert "In Progress to Done" in text


def test_a_ticket_already_transitioned_is_not_transitioned_again(
        never_shell_out):
    """Something already moved it - the merge run, a conductor, a prior sweep -
    and re-applying a transition would overwrite a decision this cannot see."""
    jira = StubJira(status="Client Validation", dod=dod(*MACHINE), comments=[
        held_comment(),
        close_out("1. The hook is wired. MET.",
                  "2. pytest counts are quoted. MET."),
    ])

    outcome, = closeout.regrade_run(jira.get, jira.post, ["PPA-1"])

    assert outcome.verdict == "SKIPPED"
    assert "already transitioned, not transitioned again" in outcome.detail
    assert never_shell_out == [], "a skipped key fires no transition"
    assert jira.posts == [], "and writes nothing"


def test_a_later_checklist_still_reporting_a_condition_unmet_stays_held(
        never_shell_out):
    """The grade is the same grade, read later. A failing one still fails."""
    jira = StubJira(dod=dod(*MACHINE), comments=[
        held_comment(),
        close_out("1. The hook is wired. MET.",
                  "2. pytest counts are quoted. NOT MET."),
    ])

    outcome, = closeout.regrade_run(jira.get, jira.post, ["PPA-1"])

    assert outcome.verdict == "HELD"
    assert "1 of 2 conditions are not reported met" in outcome.detail
    assert never_shell_out == []
    assert jira.posts == [], (
        "the held comment naming those conditions is already on the ticket; a "
        "second copy per sweep is noise")


def test_a_ticket_carrying_no_held_comment_is_left_alone(never_shell_out):
    """It was never held by this workflow, so a sweep is not where its
    checklist gets graded for the first time."""
    jira = StubJira(dod=dod(*MACHINE), comments=[
        close_out("1. The hook is wired. MET.",
                  "2. pytest counts are quoted. MET."),
    ])

    outcome, = closeout.regrade_run(jira.get, jira.post, ["PPA-1"])

    assert outcome.verdict == "SKIPPED"
    assert "never held by this workflow" in outcome.detail
    assert never_shell_out == []


def test_the_held_search_asks_for_the_status_and_the_mark():
    """The sweep's own population. Status alone would sweep every In Progress
    ticket in the project; the mark is what narrows it to this file's work."""
    asked = []

    def get(path):
        asked.append(path)
        return {"issues": [{"key": "PPA-1"}, {"key": "PPA-2"}]}

    assert closeout.held_keys(get) == ["PPA-1", "PPA-2"]
    assert closeout.HELD_MARK in closeout.HELD_JQL
    assert f'status = "{closeout.MERGED_FROM}"' in closeout.HELD_JQL
    assert asked[0].startswith("/search/jql?")


def test_the_regrade_run_is_a_dry_run_when_asked(never_shell_out):
    """--dry-run writes nothing on this path either."""
    jira = StubJira(dod=dod(*MACHINE), comments=[
        held_comment(),
        close_out("1. The hook is wired. MET.",
                  "2. pytest counts are quoted. MET."),
    ])

    outcome, = closeout.regrade_run(jira.get, jira.post, ["PPA-1"], dry_run=True)

    assert outcome.verdict == "COMMENTED"
    assert "would move to 'Done'" in outcome.detail
    assert (jira.posts, never_shell_out) == ([], [])


def test_the_merge_path_is_unreachable_from_the_regrade_flag():
    """The two halves of main() do not overlap: --regrade never reads a merge
    message and a merge run never sweeps."""
    args = closeout.build_parser().parse_args(["--regrade", "--keys", "PPA-1"])

    assert (args.regrade, args.keys) == (True, "PPA-1")
    assert closeout.build_parser().parse_args([]).regrade is False


# --------------------------------------------------------------------------
# PPA-1535 — two full checklists on one ticket
#
# merged_verdicts() took the most complete checklist as the base and let later
# comments override only the rows they name. That is right for a correction
# naming a few rows and was never exercised against a second *full* checklist,
# which PPA-1519 made ordinary the day it shipped: a session refused by the
# Stop gate answers with the whole table rather than a correction.
# --------------------------------------------------------------------------

THREE_CONDITIONS = dod("[machine] alpha is quoted.",
                       "[machine] beta is quoted.",
                       "[machine] gamma is quoted.")


def verdicts_for(*comments):
    """{number: verdict} and the comments merged_verdicts() actually used."""
    merged, used, _defects = closeout.merged_verdicts(
        list(comments), closeout.conditions_in(THREE_CONDITIONS))
    return merged, used


def test_two_full_checklists_disagreeing_on_every_row_take_the_later_one():
    """Named test 1. A session that restates every row is correcting the whole
    table, not amending it, so nothing of the first checklist survives."""
    merged, used = verdicts_for(
        close_out("1. alpha is quoted. NOT MET.",
                  "2. beta is quoted. NOT MET.",
                  "3. gamma is quoted. NOT MET."),
        close_out("1. alpha is quoted. MET.",
                  "2. beta is quoted. MET.",
                  "3. gamma is quoted. MET."))

    assert merged == {1: "MET", 2: "MET", 3: "MET"}
    assert len(used) == 1, "the superseded checklist was still reported as used"


def test_two_full_checklists_disagreeing_on_one_row_take_the_later_one():
    """Named test 2. The same rule, and it must not degrade into a per-row
    merge that keeps whichever verdict is more favourable."""
    merged, _used = verdicts_for(
        close_out("1. alpha is quoted. MET.",
                  "2. beta is quoted. NOT MET.",
                  "3. gamma is quoted. MET."),
        close_out("1. alpha is quoted. MET.",
                  "2. beta is quoted. MET.",
                  "3. gamma is quoted. MET."))

    assert merged == {1: "MET", 2: "MET", 3: "MET"}


def test_a_subset_correction_still_overrides_only_the_rows_it_names():
    """Named test 3, and the behaviour this change must not disturb. The
    correction names one row; the other two keep the full checklist's verdicts."""
    merged, used = verdicts_for(
        close_out("1. alpha is quoted. NOT MET.",
                  "2. beta is quoted. NOT MET.",
                  "3. gamma is quoted. NOT MET."),
        close_out("2. beta is quoted. MET."))

    assert merged == {1: "NOT MET", 2: "MET", 3: "NOT MET"}
    assert len(used) == 2, "a subset correction must not replace its base"


def test_a_row_the_later_checklist_misquotes_keeps_the_base_verdict():
    """The case the rule had to settle rather than the case it was written for.

    The later checklist states three rows and means to restate all of them,
    but its third quotes no condition, so it pairs to two. It is then no
    longer the most complete checklist, the earlier one stays the base, and
    condition 3 keeps the earlier verdict while 1 and 2 are updated.

    Asserted because it is surprising, not because it is wrong: a row quoting
    no condition names no condition, and there is nothing else to fall back to.
    """
    merged, used = verdicts_for(
        close_out("1. alpha is quoted. NOT MET.",
                  "2. beta is quoted. NOT MET.",
                  "3. gamma is quoted. NOT MET."),
        close_out("1. alpha is quoted. MET.",
                  "2. beta is quoted. MET.",
                  "3. something else entirely. MET."))

    assert merged == {1: "MET", 2: "MET", 3: "NOT MET"}
    assert len(used) == 2


def test_a_correction_between_two_full_checklists_is_superseded_by_the_later():
    """PPA-1519's live shape: ten rows, a one-row correction, then ten rows
    again. The correction precedes the final checklist, so it is shadowed by
    it rather than applied over it."""
    merged, used = verdicts_for(
        close_out("1. alpha is quoted. NOT MET.",
                  "2. beta is quoted. NOT MET.",
                  "3. gamma is quoted. NOT MET."),
        close_out("2. beta is quoted. NOT MET."),
        close_out("1. alpha is quoted. MET.",
                  "2. beta is quoted. MET.",
                  "3. gamma is quoted. MET."))

    assert merged == {1: "MET", 2: "MET", 3: "MET"}
    assert len(used) == 1


def test_the_module_states_the_two_checklist_rule_exactly_once():
    """Condition 2 asks for it in the module docstring, and once. A rule
    written in two places is a rule that can disagree with itself."""
    source = Path(closeout.__file__).read_text(encoding="utf-8")

    assert source.count("Two full checklists") == 1
    assert "Two full checklists" in (closeout.__doc__ or "")


# --------------------------------------------------------------------------
# PPA-1534 - the Slack notice on the held outcome
#
# The ticket's named tests, as amended by comment 29460 on 22-SEP-2026: the
# held routing sends one message carrying the key, hash, pull request and the
# conditions that held it; Done sends none; Client Validation sends none; and
# a raising Slack call leaves the routing alone and the run green.
# --------------------------------------------------------------------------

CHANNEL = "C0DELIVERYOPS"
TOKEN = "test-bot-token"

#: A Definition of Done that cannot reach Done, so its close-out routes to
#: Client Validation however many conditions it reports met.
NEEDS_CONDUCTOR = dod("[machine] pytest counts for scripts/ are quoted.",
                      "[conductor] The voice is consistent.")
CONDUCTOR_ALL_MET = [close_out("Definition of Done, condition by condition.",
                               "1. pytest counts. Met.",
                               "2. The voice is consistent. Met.")]


@pytest.fixture()
def notices(monkeypatch):
    """Capture what post_notice would send, and name a channel to send it to.

    The HTTP call itself is asserted through a stubbed urlopen in the
    PPA-1601 tests below.
    """
    sent = []
    monkeypatch.setenv(closeout.CHANNEL_VAR, CHANNEL)
    monkeypatch.setenv(closeout.TOKEN_VAR, TOKEN)
    monkeypatch.setattr(closeout, "post_notice",
                        lambda token, channel, text: sent.append((channel, text)))
    return sent


def test_a_held_key_sends_one_notice_carrying_what_a_reader_needs(
    never_shell_out, notices
):
    """Named test 1. Key, hash, pull request and every condition that held it -
    enough to act on without opening the ticket."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)

    assert outcomes[0].verdict == "HELD"
    assert len(notices) == 1, "a held key sent something other than one notice"
    channel, said = notices[0]
    assert channel == CHANNEL
    assert "PPA-1" in said
    assert SHA[:12] in said
    assert "pull request #90" in said
    assert "No file outside this repository is edited" in said
    assert "pytest counts for scripts/ are quoted" not in said, (
        "a met condition was named as having held the ticket")


def test_a_routing_to_done_sends_no_notice(never_shell_out, notices):
    """Named test 2. Done is not a rejection, so nobody is told."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE, comments=ALL_MET)

    run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)

    assert never_shell_out[0][-1] == "Done"
    assert notices == []


def test_a_routing_to_client_validation_sends_no_notice(
    never_shell_out, notices
):
    """Named test 3. Client Validation is a hand-off, not a rejection."""
    stub = StubJira(status="In Progress", dod=NEEDS_CONDUCTOR,
                    comments=CONDUCTOR_ALL_MET)

    run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)

    assert never_shell_out[0][-1] == "Client Validation"
    assert notices == []


def test_every_outcome_the_module_produces_is_covered(never_shell_out, notices):
    """Named test 2, the other half: one case per outcome, in one place, so a
    fourth outcome added later has an obviously missing row here."""
    cases = {
        "held": (ALL_MACHINE, MACHINE_ONE_UNMET),
        "Done": (ALL_MACHINE, ALL_MET),
        "Client Validation": (NEEDS_CONDUCTOR, CONDUCTOR_ALL_MET),
    }
    sent = {}
    for name, (dod_field, comments) in cases.items():
        del notices[:]
        stub = StubJira(status="In Progress", dod=dod_field, comments=comments)
        run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)
        sent[name] = len(notices)

    assert sent == {"held": 1, "Done": 0, "Client Validation": 0}


class FakeSlack:
    """Stands in for urllib.request.urlopen: records each request, answers ok."""

    def __init__(self, reply=b'{"ok": true}'):
        self.reply = reply
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        reply = self.reply

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return reply

        return Response()


def test_a_held_key_posts_one_chat_post_message_carrying_notice_text(
    never_shell_out, monkeypatch
):
    """PPA-1601. The notice goes out through chat.postMessage with urllib, and
    its text is notice_text() unchanged."""
    monkeypatch.setenv(closeout.CHANNEL_VAR, CHANNEL)
    monkeypatch.setenv(closeout.TOKEN_VAR, TOKEN)
    slack = FakeSlack()
    monkeypatch.setattr(closeout.urllib.request, "urlopen", slack)
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)

    assert len(slack.requests) == 1
    req, = slack.requests
    assert req.full_url == "https://slack.com/api/chat.postMessage"
    assert req.get_method() == "POST"
    assert req.get_header("Authorization") == f"Bearer {TOKEN}"
    table = closeout.build_table(ALL_MACHINE, MACHINE_ONE_UNMET)
    failures = [(r[0], r[1]) for r in table.unmet]
    assert json.loads(req.data) == {
        "channel": CHANNEL,
        "text": closeout.notice_text("PPA-1", failures, SHA, "90")}
    assert f"notice sent to {CHANNEL}" in outcomes[0].detail


@pytest.mark.parametrize("failure", ["raises", "ok false"])
def test_a_raising_slack_call_leaves_the_outcome_and_the_exit_code_alone(
    never_shell_out, monkeypatch, failure
):
    """Named test 4. Where a merged ticket goes is this workflow's decision and
    a Slack outage may not change it - so the verdict, the exit code and the
    held comment all have to survive the raise. Slack's own refusal, HTTP 200
    carrying "ok": false, is the same case."""
    monkeypatch.setenv(closeout.CHANNEL_VAR, CHANNEL)
    monkeypatch.setenv(closeout.TOKEN_VAR, TOKEN)

    def explode(req, timeout=None):
        raise closeout.urllib.error.URLError("slack.com unreachable")

    monkeypatch.setattr(closeout.urllib.request, "urlopen", explode if (
        failure == "raises") else FakeSlack(b'{"ok": false, "error": "channel_not_found"}'))
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)

    assert never_shell_out == [], "the routing changed"
    assert outcomes[0].verdict == "HELD"
    assert exit_code(outcomes) == PARTIAL_EXIT
    assert held_posted(stub) is not None, "the held comment was lost to Slack"
    assert "notice not sent:" in outcomes[0].detail


def test_an_unset_token_skips_the_notice_without_failing(
    never_shell_out, monkeypatch
):
    monkeypatch.setenv(closeout.CHANNEL_VAR, CHANNEL)
    monkeypatch.delenv(closeout.TOKEN_VAR, raising=False)
    monkeypatch.setattr(closeout.urllib.request, "urlopen", lambda *a, **k: (
        pytest.fail("posted with no token")))
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)

    assert outcomes[0].verdict == "HELD"
    assert f"no notice sent: {closeout.TOKEN_VAR} is not set" in outcomes[0].detail


def test_the_notice_is_sent_after_the_held_comment(never_shell_out, monkeypatch):
    """The notice is the last thing the held path does. Asserted by ordering,
    because "after" is the property that keeps a Slack failure harmless."""
    order = []
    monkeypatch.setenv(closeout.CHANNEL_VAR, CHANNEL)
    monkeypatch.setenv(closeout.TOKEN_VAR, TOKEN)
    monkeypatch.setattr(closeout, "post_notice",
                        lambda token, channel, text: order.append("notice"))
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)
    real_post = stub.post

    def watched(path, payload):
        if closeout.HELD_MARK in closeout.adf_text(payload["body"]):
            order.append("held comment")
        return real_post(path, payload)

    run(stub.get, watched, ["PPA-1"], SHA, "90", DATE)

    assert order == ["held comment", "notice"]


def test_the_channel_is_read_from_the_environment_and_not_the_source():
    """Condition 4. The id is configuration: this file names the variable and
    never a channel. A literal would ship one repository's channel into the
    two siblings that carry a registered copy of this script."""
    source = (Path(closeout.__file__)).read_text(encoding="utf-8")

    assert closeout.CHANNEL_VAR == "SLACK_CHANNEL_DELIVERY_OPS"
    assert not re.search(r'"C0[A-Z0-9]{6,}"', source), (
        "a Slack channel id is written into the source")


def test_an_unset_channel_variable_skips_the_notice_without_failing(
    never_shell_out, monkeypatch
):
    """An unconfigured repository is a skip rather than an error - the same
    call registry_reconcile makes about its own channel variable."""
    monkeypatch.delenv(closeout.CHANNEL_VAR, raising=False)
    monkeypatch.setattr(closeout, "post_notice", lambda token, channel, text: (
        pytest.fail("posted with no channel configured")))
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE)

    assert outcomes[0].verdict == "HELD"
    assert f"no notice sent: {closeout.CHANNEL_VAR} is not set" in outcomes[0].detail


def test_a_re_run_of_the_same_merge_does_not_notify_twice(
    never_shell_out, notices
):
    """The same guard the held comment uses: a merge already announced stays
    silent, so a workflow_dispatch re-run is not a second ping."""
    first = StubJira(status="In Progress", dod=ALL_MACHINE,
                     comments=MACHINE_ONE_UNMET)
    run(first.get, first.post, ["PPA-1"], SHA, "90", DATE)
    posted = [{"body": payload["body"]} for _, payload in first.posts]
    assert len(notices) == 1

    again = StubJira(status="In Progress", dod=ALL_MACHINE,
                     comments=[*MACHINE_ONE_UNMET, *posted])
    outcomes = run(again.get, again.post, ["PPA-1"], SHA, "90", DATE)

    assert len(notices) == 1, "the same merge was announced twice"
    assert "notice already sent for this merge" in outcomes[0].detail


def test_a_dry_run_sends_no_notice(never_shell_out, notices):
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    outcomes = run(stub.get, stub.post, ["PPA-1"], SHA, "90", DATE, dry_run=True)

    assert notices == []
    assert f"would notify {CHANNEL}" in outcomes[0].detail


def test_the_notice_survives_a_missing_pull_request_number(
    never_shell_out, notices
):
    """A merge whose subject carries no (#N) still names the key and the hash."""
    stub = StubJira(status="In Progress", dod=ALL_MACHINE,
                    comments=MACHINE_ONE_UNMET)

    run(stub.get, stub.post, ["PPA-1"], SHA, None, DATE)

    _channel, said = notices[0]
    assert "pull request" not in said
    assert "PPA-1" in said and SHA[:12] in said


def test_the_regrade_sweep_sends_no_notice(never_shell_out, notices):
    """A grade that still fails posts nothing on the sweep path - the held
    comment naming the conditions is already on the ticket, and the notice for
    that merge was already sent. One rejection, one ping."""
    jira = StubJira(status="In Progress", dod=dod(*MACHINE), comments=[
        held_comment(),
        close_out("1. The hook is wired. MET.",
                  "2. pytest counts are quoted. NOT MET."),
    ])

    outcome, = closeout.regrade_run(jira.get, jira.post, ["PPA-1"])

    assert outcome.verdict == "HELD"
    assert notices == []


def test_the_workflow_passes_the_channel_input_and_the_token():
    """Condition 4's other half, as changed by PPA-1601: the channel comes from
    the caller's optional slack_channel input, the token from an optional
    secret, and neither is a literal in the file."""
    import yaml

    root = Path(closeout.__file__).resolve().parents[1]
    text = (root / ".github/workflows/merge-close-out.yml").read_text()
    workflow = yaml.safe_load(text)
    call = workflow[True]["workflow_call"]  # PyYAML reads the key `on` as True
    step, = [s for s in workflow["jobs"]["close-out"]["steps"]
             if "pr_merge_close_out.py" in (s.get("run") or "")]

    assert call["inputs"]["slack_channel"]["required"] is False
    assert call["inputs"]["slack_channel"]["type"] == "string"
    assert call["secrets"]["SLACK_BOT_TOKEN"]["required"] is False
    assert step["env"][closeout.CHANNEL_VAR] == "${{ inputs.slack_channel }}"
    assert step["env"][closeout.TOKEN_VAR] == "${{ secrets.SLACK_BOT_TOKEN }}"
    assert not re.search(r"xox[abprs]-", text), "a Slack token is in the file"
    assert not re.search(r"\bC0[A-Z0-9]{6,}\b", text), "a channel id is in the file"
