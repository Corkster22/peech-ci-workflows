"""pt_transition.py — the six tests named in PPA-1021.

Each test maps to one bullet under the ticket's "Named tests" heading, in the
order the ticket lists them.
"""

import re
from pathlib import Path

import pt_transition
import pytest
from pt_transition import build_parser, exit_code, run

from .conftest import StubJira, transition

SOURCE = Path(__file__).resolve().parent.parent / "pt_transition.py"


def test_key_already_at_target_is_noop_and_fires_nothing(ppa_plan):
    """Named test 1 — a key already at the target returns NOOP and fires
    nothing. This is what makes the script safe to run after a session has
    already applied its own transition."""
    stub = StubJira("Done", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done")

    assert [r.verdict for r in results] == ["NOOP"]
    assert results[0].hops == 0
    assert stub.posts == []
    assert stub.transition_reads == 0, (
        "a NOOP must not even read the transition set")


def test_to_do_walks_the_ladder_to_client_validation(ppa_plan):
    """Named test 2 — a key at To Do walks the ladder, two hops, against
    stubbed transition sets.

    PPA-1021 wrote this with Done as the target and PPA-1264 restored it to a
    no-flag run. PPA-1433 then refused that destination from any source but
    Client Validation, so the multi-hop ladder walk this test exists to pin
    now ends one rung lower. The refusal itself is
    test_done_from_to_do_halts below; what is asserted here is the walk.
    """
    stub = StubJira("To Do", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Client Validation")

    assert results[0].verdict == "PASS"
    assert results[0].start == "To Do"
    assert results[0].end == "Client Validation"
    assert results[0].hops == 2
    assert stub.status == "Client Validation"
    fired = [payload["transition"]["id"] for _, payload in stub.posts]
    assert fired == ["10", "21"], (
        "expected both ladder hops; the stub rejects any ID it did not offer")


def test_target_unreachable_within_three_hops_halts():
    """Named test 3 — a target unreachable within three hops halts and
    reports that key.

    The live PPA ladder is four rungs, so Done is always reachable from To Do
    inside the cap; the cap is exercised against a longer injected ladder,
    which is the only way to reach the code path with a stub.
    """
    ladder = {f"s{i}": i for i in range(5)}
    plan = {f"s{i}": [transition(str(90 + i), f"step {i}", f"s{i + 1}")]
            for i in range(4)}
    stub = StubJira("s0", plan)

    results = run(stub.get, stub.post, ["PPA-1"], "s4", ladder=ladder)

    assert results[0].verdict == "HALT"
    assert results[0].key == "PPA-1"
    assert results[0].hops == pt_transition.HOP_CAP
    assert "not reached within 3 hops" in results[0].detail
    assert len(stub.posts) == pt_transition.HOP_CAP, (
        "it should stop at the cap, not keep firing")


def test_hop_with_no_status_change_halts_without_retrying(ppa_plan):
    """Named test 4 — a hop that produces no status change halts rather than
    retrying. The stub accepts the write and refuses to move, which is how a
    workflow condition rejects a transition: success response, no change."""
    stub = StubJira("To Do", ppa_plan, stuck=["To Do"])

    results = run(stub.get, stub.post, ["PPA-1"], "Done")

    assert results[0].verdict == "HALT"
    assert results[0].end == "To Do"
    assert "produced no status change" in results[0].detail
    assert len(stub.posts) == 1, "halting means one attempt, not a retry loop"


def test_no_transition_id_literal_in_source():
    """Named test 5 — no transition ID appears as a literal in the source,
    asserted by a grep over the file."""
    source = SOURCE.read_text(encoding="utf-8")

    literal_id = re.compile(r"""["']id["']\s*:\s*["']?\d""")
    assert not literal_id.search(source), (
        "a numeric id is assigned in a dict literal; every transition ID must "
        "come from a live read")

    assert re.search(r"""\{"transition":\s*\{"id":\s*[A-Za-z_]""", source), (
        "the transition payload must be built from a variable read live, not "
        "from a hardcoded value")


def test_exit_code_is_non_zero_only_when_a_key_halts(ppa_plan):
    """Named test 6 — exit code is non-zero when any key halts and zero when
    all pass."""
    # Client Validation rather than Done: PPA-1433 refuses Done from To Do, and
    # this case is about the exit code rather than about the destination.
    passing = StubJira("To Do", ppa_plan)
    results = run(passing.get, passing.post, ["PPA-1"], "Client Validation")
    assert [r.verdict for r in results] == ["PASS"]
    assert exit_code(results) == 0

    halting = StubJira("To Do", ppa_plan, stuck=["To Do"])
    mixed = run(halting.get, halting.post, ["PPA-1"], "Done")
    mixed += run(StubJira("Done", ppa_plan).get, None, ["PPA-2"], "Done")
    assert sorted(r.verdict for r in mixed) == ["HALT", "NOOP"]
    assert exit_code(mixed) == 1


# --------------------------------------------------------------------------
# PPA-1039 item 2 — norm() folds dash variants.
# --------------------------------------------------------------------------
#
# The live PPA workflow renders the status as "Closed – Not Needed" with an
# en dash (read 14-AUG-2026). Every hand-typed form — an operator's --to
# argument, this suite's own ppa_plan fixture, the LIFECYCLE comment in the
# script — uses a hyphen. Before this fix norm() collapsed whitespace and case
# but not dash variants, so the two forms never matched and the status was
# unreachable by name from either direction.

_EN_DASH_NOT_NEEDED = "Closed – Not Needed"
_HYPHEN_NOT_NEEDED = "Closed - Not Needed"


def _not_needed_plan(rendered_name):
    """A To Do transition set whose only off-ladder exit renders
    `rendered_name`, alongside the on-ladder Start transition."""
    return {
        "To Do": [
            transition("27", "Exit – Close as Not Needed", rendered_name),
            transition("10", "Start – Move to In Progress", "In Progress"),
        ],
    }


def test_hyphen_and_en_dash_forms_resolve_to_the_same_transition():
    """A status name carrying an en dash and the same name carrying a hyphen
    resolve to one transition, whichever side each form sits on."""
    for rendered, typed in ((_EN_DASH_NOT_NEEDED, _HYPHEN_NOT_NEEDED),
                            (_HYPHEN_NOT_NEEDED, _EN_DASH_NOT_NEEDED)):
        stub = StubJira("To Do", _not_needed_plan(rendered))

        results = run(stub.get, stub.post, ["PPA-1"], typed)

        assert [r.verdict for r in results] == ["PASS"], (
            f"target {typed!r} did not reach the transition rendered "
            f"{rendered!r}: {results[0].detail}")
        assert results[0].end == rendered
        assert [payload["transition"]["id"] for _, payload in stub.posts] == ["27"]


def test_norm_folds_every_dash_variant_to_one_key():
    """Each dash character the translation table covers normalizes to the
    hyphen form, so no single variant can silently fall through."""
    for dash in ("‐", "‑", "‒", "–", "—", "―",
                 "−", "-"):
        assert pt_transition.norm(f"Closed {dash} Not Needed") == \
            pt_transition.norm(_HYPHEN_NOT_NEEDED), (
                f"dash variant {dash!r} (U+{ord(dash):04X}) does not fold")


# --------------------------------------------------------------------------
# PPA-1126 — the hook asks for In Progress on every key it sees
# --------------------------------------------------------------------------

def test_key_already_past_the_target_is_noop_and_fires_nothing(ppa_plan):
    """A prompt routinely names a ticket already at Client Validation or Done.
    Halting on those would warn on every prompt about nothing, and a workflow
    offering a direct backward transition would see it fired."""
    stub = StubJira("Client Validation", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "In Progress")

    assert [r.verdict for r in results] == ["NOOP"]
    assert "already past" in results[0].detail
    assert stub.posts == []
    assert stub.transition_reads == 0
    assert exit_code(results) == 0


# --------------------------------------------------------------------------
# PPA-1025 — the conductor-owned destination is gated behind --conductor
# --------------------------------------------------------------------------
#
# Each test below asserts the guard through run(), and several also assert
# requires_conductor() directly — that is the pure-helper half, exercised with
# no client constructed.
#
# The guard is declarative: one credential pair serves both actors, so nothing
# here proves who is calling. What it proves is that the inattention path is
# closed — a hop onto a gate verdict cannot fire without the caller saying so.
#
# PPA-1264 narrowed the set to Reopened alone, so the Done cases below now
# assert the opposite of what PPA-1025 wrote them to assert. The two tests
# whose only subject was the Done gate — the fire-then-halt route through an
# intermediate rung, and the with-flag firing of the direct close — are gone:
# Reopened is reached directly and only when a caller names it, so no
# multi-hop route to a gated destination exists to test.


def _no_direct_close(ppa_plan):
    """`ppa_plan` with the direct In Progress -> Done transition removed.

    The live set offers that shortcut, and choose_transition() prefers a direct
    match, so with it present a run from In Progress to Done resolves in one
    hop and never exercises an intermediate rung. Dropping it is a subset of
    the live set, not an invented transition, and it is the only way to reach
    the fire-then-halt path with a stub.
    """
    plan = {status: list(entries) for status, entries in ppa_plan.items()}
    plan["In Progress"] = [t for t in plan["In Progress"]
                           if t["to"]["name"] != "Done"]
    return plan


def test_done_from_in_progress_is_not_gated_by_the_conductor_flag(ppa_plan):
    """PPA-1264 named test 1, narrowed by PPA-1433.

    PPA-1264's guarantee still holds and is what this asserts: Done is not a
    conductor-owned destination, so --conductor neither unlocks nor blocks it.
    What changed is that the hop no longer fires — PPA-1433 refuses it on the
    source status instead. The flag is irrelevant in both directions, which is
    the point: a caller carrying it out of habit gets the same answer, and a
    reader must not mistake the halt below for a conductor halt.
    """
    assert pt_transition.requires_conductor("Done") is False
    assert "Done" not in pt_transition.CONDUCTOR_ONLY

    for conductor in (False, True):
        stub = StubJira("In Progress", ppa_plan)

        results = run(stub.get, stub.post, ["PPA-1"], "Done",
                      conductor=conductor)

        assert results[0].verdict == "HALT", f"conductor={conductor}"
        assert "CONDUCTOR_ONLY" not in results[0].detail
        assert "Client Validation" in results[0].detail
        assert stub.posts == [], "the guard must write nothing"


def test_start_transition_needs_no_conductor_flag(ppa_plan):
    """A hop to In Progress fires with or without the flag. This is the hop the
    UserPromptSubmit hook fires on every prompt, so gating it would break the
    hook on every turn."""
    assert pt_transition.requires_conductor("In Progress") is False

    for conductor in (False, True):
        stub = StubJira("To Do", ppa_plan)

        results = run(stub.get, stub.post, ["PPA-1"], "In Progress",
                      conductor=conductor)

        assert results[0].verdict == "PASS", f"conductor={conductor}"
        assert results[0].end == "In Progress"
        assert [payload["transition"]["id"]
                for _, payload in stub.posts] == ["10"]


def test_client_validation_needs_no_conductor_flag(ppa_plan):
    """A hop to Client Validation fires with or without the flag. Ruled
    26-AUG-2026: the delegated session applies this one itself, so it is not a
    gate verdict and is deliberately not in CONDUCTOR_ONLY."""
    assert pt_transition.requires_conductor("Client Validation") is False
    assert "Client Validation" not in pt_transition.CONDUCTOR_ONLY

    for conductor in (False, True):
        stub = StubJira("In Progress", ppa_plan)

        results = run(stub.get, stub.post, ["PPA-1"], "Client Validation",
                      conductor=conductor)

        assert results[0].verdict == "PASS", f"conductor={conductor}"
        assert results[0].end == "Client Validation"
        assert [payload["transition"]["id"]
                for _, payload in stub.posts] == ["21"]


def test_reject_to_reopened_is_gated_behind_the_conductor_flag(ppa_plan):
    """Client Validation -> Reopened is reachable by name with Reopened off the
    LIFECYCLE ladder, and is gated. Chat applies this hop and writes the reason
    comment; a delegated session must not issue the verdict."""
    assert pt_transition.requires_conductor("Reopened") is True
    assert pt_transition.norm("Reopened") not in pt_transition.LADDER, (
        "Reopened must stay off the lifecycle ladder")

    blocked = StubJira("Client Validation", ppa_plan)
    results = run(blocked.get, blocked.post, ["PPA-1"], "Reopened")
    assert results[0].verdict == "HALT"
    assert blocked.posts == []
    assert blocked.status == "Client Validation"
    assert "'Reopened'" in results[0].detail

    allowed = StubJira("Client Validation", ppa_plan)
    results = run(allowed.get, allowed.post, ["PPA-1"], "Reopened",
                  conductor=True)
    assert results[0].verdict == "PASS"
    assert results[0].end == "Reopened"
    assert [payload["transition"]["id"]
            for _, payload in allowed.posts] == ["17"]


def test_restart_from_reopened_to_in_progress_needs_no_flag(ppa_plan):
    """Reopened -> In Progress is reachable by name from a status the ladder
    does not carry, and needs no flag — Code owns the restart hop under the
    same rule that gives it To Do -> In Progress."""
    stub = StubJira("Reopened", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "In Progress")

    assert results[0].verdict == "PASS"
    assert results[0].start == "Reopened"
    assert results[0].end == "In Progress"
    assert [payload["transition"]["id"] for _, payload in stub.posts] == ["10"]


def test_dry_run_reports_the_block_not_the_plan(ppa_plan):
    """--dry-run surfaces the same refusal rather than a plan that would not
    run. A dry run reporting the hops it intends to fire, on a run that cannot
    fire them, is the misleading case this closes.

    Keyed on Reopened since PPA-1264. A dry run to Done no longer blocks at
    all, which is asserted separately by
    test_dry_run_to_done_from_in_progress_reports_the_hop_as_permitted.
    """
    stub = StubJira("Client Validation", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Reopened", dry_run=True)

    assert results[0].verdict == "HALT"
    assert "--conductor" in results[0].detail
    assert "dry run" not in results[0].detail, (
        "the block replaces the plan; it is not appended to it")
    assert stub.posts == []


def test_dry_run_of_the_merge_workflows_hop_reports_it_as_permitted(ppa_plan):
    """The hop the merge workflow fires, planned and not blocked.

    PPA-1264 wrote this as In Progress -> Done, which was that workflow's hop
    at the time. PPA-1382 made Client Validation its only outcome, so the hop
    it actually fires is the one asserted here. Pinned against the stub so a
    restored guard fails the suite rather than only the next merge.
    """
    stub = StubJira("In Progress", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Client Validation",
                  dry_run=True)

    assert results[0].verdict == "PASS"
    assert results[0].end == "Client Validation"
    assert "dry run, nothing fired" in results[0].detail
    assert "--conductor" not in results[0].detail
    assert stub.posts == [], "a dry run fires nothing"


def test_already_at_conductor_only_target_still_noops_without_the_flag(
        ppa_plan):
    """Idempotence outranks the guard. A NOOP attempts no write, so there is
    nothing to gate — and converting it into a HALT would make a second run of
    an already-rejected key report a failure.

    Keyed on Reopened since PPA-1264 narrowed CONDUCTOR_ONLY to it.
    """
    stub = StubJira("Reopened", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Reopened")

    assert [r.verdict for r in results] == ["NOOP"]
    assert results[0].hops == 0
    assert "already at target" in results[0].detail
    assert stub.posts == []
    assert stub.transition_reads == 0, (
        "a NOOP must not even read the transition set")
    assert exit_code(results) == 0, "a NOOP is not a failure"


# --------------------------------------------------------------------------
# PPA-1264 — --skip-validation is retired, and passing it is an error
# --------------------------------------------------------------------------
#
# PPA-1186 finding 4 added --skip-validation and four tests under this heading:
# the guard halted a hop landing on Done from short of Client Validation. Every
# one of those tests asserted a refusal that is now the ordinary path, so the
# section is replaced rather than adjusted.
#
# What replaces it is narrower on purpose. The guard is gone, so there is no
# behavior left to pin except the one thing a caller can still get wrong:
# passing the flag that used to release it.


def test_skip_validation_is_rejected_with_an_error_naming_the_ticket(capsys):
    """PPA-1264 named test 3 — --skip-validation errors, and the error names
    the ticket that retired it.

    A retired flag accepted and ignored is the failure this closes: a caller
    following the old procedure would see a clean exit and believe the bypass
    was granted. argparse's own "unrecognized arguments" line is an error but
    reads like a typo, which is why the flag stays registered and fails loudly.
    """
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--keys", "PPA-1", "--to", "Done",
                           "--skip-validation"])

    assert exc.value.code == 2
    message = capsys.readouterr().err
    assert "--skip-validation" in message
    assert "PPA-1264" in message, "the error must name the retiring ticket"
    assert "retired" in message


def test_the_retired_flag_is_the_only_thing_left_of_the_guard():
    """The guard's helper and its two constants are gone from the module.

    Asserted by attribute rather than by grep: a re-added helper would fail
    here even if it were spelled differently in the source.
    """
    for gone in ("skips_validation", "VALIDATION_GATE", "COMPLETION"):
        assert not hasattr(pt_transition, gone), (
            f"{gone} was retired by PPA-1264 and is back")


def test_a_run_needs_no_flag_to_advance_a_merged_ticket(ppa_plan):
    """The whole point, asserted end to end, with no flags.

    Under PPA-1025 and PPA-1186 together this run needed both, so the
    merge-triggered workflow would have halted twice over. PPA-1264 took both
    off; PPA-1382 then moved the workflow's destination down a rung, and
    PPA-1433 refuses the rung above from here. What PPA-1264 secured survives:
    the workflow's own hop needs no flag.
    """
    stub = StubJira("To Do", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Client Validation")

    assert results[0].verdict == "PASS"
    assert results[0].end == "Client Validation"
    assert exit_code(results) == 0


# --------------------------------------------------------------------------
# PPA-1433 — Done is reachable only from Client Validation
# --------------------------------------------------------------------------
#
# The guard PPA-1186 finding 4 installed was removed by PPA-1264 on the stated
# ground that In Progress -> Done was the merge workflow's ordinary path.
# PPA-1382 then made Client Validation that workflow's only outcome, so the
# actor the path was kept open for can no longer use it. The premise went; the
# removal did not. These five cases are the ticket's own named list, in order.
#
# It is a source-status rule, not a destination rule, so CONDUCTOR_ONLY is
# untouched and there is no override flag — see validation_skipped()'s
# docstring for why restoring one is barred rather than merely unnecessary.


def test_done_from_in_progress_halts_naming_the_skipped_status(ppa_plan):
    """The measured case. A hand-run --to "Done" from In Progress fired the
    live "Closed - No client approval required" transition and reached Done
    without passing Client Validation, asserting in the changelog that nobody
    needed to approve the work."""
    stub = StubJira("In Progress", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done")

    assert results[0].verdict == "HALT"
    assert results[0].start == "In Progress"
    assert results[0].end == "In Progress"
    assert "'In Progress'" in results[0].detail       # the source status
    assert "'Client Validation'" in results[0].detail  # the skipped rung
    assert stub.posts == []
    assert exit_code(results) == 1


def test_done_from_client_validation_fires_with_no_flag(ppa_plan):
    """The one legitimate route to Done, and it needs no flag. This is why the
    guard reads the source rather than the destination: putting Done back in
    CONDUCTOR_ONLY would gate this hop instead."""
    stub = StubJira("Client Validation", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done")

    assert results[0].verdict == "PASS"
    assert results[0].end == "Done"
    assert results[0].hops == 1
    assert stub.status == "Done"
    assert [payload["transition"]["id"] for _, payload in stub.posts] == ["31"]
    assert exit_code(results) == 0


def test_done_from_to_do_halts(ppa_plan):
    """The same guard, reached from further down the ladder. To Do offers no
    direct close, so the run walks to In Progress and halts on the hop that
    would have landed on Done — the guard reads each hop's destination, not
    the run's target."""
    stub = StubJira("To Do", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done")

    assert results[0].verdict == "HALT"
    assert "'Client Validation'" in results[0].detail
    assert stub.status == "In Progress", (
        "the ladder hop is legitimate on its own and stands; only the hop "
        "onto Done is refused")
    assert [payload["transition"]["id"] for _, payload in stub.posts] == ["10"]


def test_skip_validation_is_still_rejected():
    """The existing retirement case, confirmed unchanged. PPA-1186 made this
    an opt-in flag and PPA-1264 retired it; PPA-1433 restores the guard
    without restoring the override, so passing it is still an error."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["--keys", "PPA-1", "--to", "Done", "--skip-validation"])


def test_reopened_remains_the_only_member_of_conductor_only():
    """Item 4. The new guard is a source-status rule and the conductor gate is
    a destination rule; the two are independent and Done is not added back."""
    assert pt_transition.CONDUCTOR_ONLY == ("Reopened",)


# -- the pure helper, exercised with no client constructed -------------------

@pytest.mark.parametrize("source", ["To Do", "In Progress", "Reopened",
                                    "BLOCKED", "Info Provided"])
def test_every_source_but_client_validation_is_refused(source):
    assert pt_transition.validation_skipped(source, "Done") is not None


def test_client_validation_is_the_one_permitted_source():
    assert pt_transition.validation_skipped("Client Validation", "Done") is None


def test_the_guard_ignores_a_hop_that_does_not_land_on_done():
    for destination in ("In Progress", "Client Validation", "Reopened"):
        assert pt_transition.validation_skipped("To Do", destination) is None


def test_the_guard_folds_case_and_dash_variants_like_every_other_name():
    """norm() governs here as it governs --to and CONDUCTOR_ONLY; an operator
    types what they saw."""
    assert pt_transition.validation_skipped("CLIENT VALIDATION", "DONE") is None
    assert pt_transition.validation_skipped(" Client  Validation ", "Done") is None
    assert pt_transition.validation_skipped("In Progress", " done ") is not None


def test_no_override_flag_was_added():
    """Item 2. Restoring an override under any name would rebuild the thing
    that has now failed twice, so the parser gains no new store_true."""
    source = SOURCE.read_text()
    assert "skip_validation" not in source.replace("--skip-validation", "")
    flags = re.findall(r'add_argument\("(--[a-z-]+)"', source)
    assert flags == ["--keys", "--to", "--dry-run", "--conductor",
                     "--skip-validation"]


def test_a_dry_run_surfaces_the_refusal_rather_than_a_plan(ppa_plan):
    """The guard sits before the dry-run return, so --dry-run reports the halt
    instead of printing hops that would not run."""
    stub = StubJira("In Progress", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done", dry_run=True)

    assert results[0].verdict == "HALT"
    assert "'Client Validation'" in results[0].detail
    assert stub.posts == []


def test_the_docstring_records_ppa_1382_superseding_ppa_1264():
    """Item 3. The next reader must not re-derive the retired rule from the
    file that executes."""
    doc = pt_transition.__doc__
    assert "PPA-1382" in doc and "PPA-1264" in doc
    assert "supersedes" in doc.lower()


# --------------------------------------------------------------------------
# PPA-1459 — the merge close-out workflow's own In Progress -> Done hop
# --------------------------------------------------------------------------
#
# Auto-Done shipped as 91645d0d2f65 and was refused here twice, on runs
# 35257775366 and 35277277762, each after grading a ticket's Definition of Done
# and finding every condition [machine] and every one met. The guard above is
# narrowed for that one caller and for no other.
#
# The discriminator is the runner environment, not a flag. Every case below
# builds the environment as a plain dict and passes it in; nothing here touches
# os.environ, and test_no_override_flag_was_added above is unchanged and still
# asserts the parser gained nothing.

#: What GitHub writes into the merge close-out workflow's runner. The
#: GITHUB_WORKFLOW_REF form is GitHub's documented one, checked 17-SEP-2026:
#: owner/repo/.github/workflows/name.yml@refs/heads/branch.
CLOSE_OUT_ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_WORKFLOW_REF": (
        "peech-tech/peech-pmo-automation"
        "/.github/workflows/merge-close-out.yml@refs/heads/main"),
}


def test_a_hand_run_presents_none_of_the_four_and_is_refused():
    """The laptop case, which is every run this guard was written about. An
    empty environment is what a shell on a machine has."""
    assert pt_transition.merge_close_out_run({}) is False
    assert pt_transition.validation_skipped("In Progress", "Done") is not None


def test_the_close_out_runner_is_recognised():
    assert pt_transition.merge_close_out_run(CLOSE_OUT_ENV) is True


@pytest.mark.parametrize("dropped", sorted(CLOSE_OUT_ENV))
def test_each_of_the_four_runner_facts_is_load_bearing(dropped):
    """One test per fact, each failing on its own. Remove any one and the
    process is no longer identifiably a merge close-out run."""
    environ = {k: v for k, v in CLOSE_OUT_ENV.items() if k != dropped}

    assert pt_transition.merge_close_out_run(environ) is False
    assert pt_transition.validation_skipped(
        "In Progress", "Done",
        pt_transition.merge_close_out_run(environ)) is not None


@pytest.mark.parametrize("key,wrong", [
    ("GITHUB_ACTIONS", "false"),
    ("GITHUB_EVENT_NAME", "workflow_dispatch"),
    ("GITHUB_REF", "refs/heads/ppa-1459-auto-done-guard"),
    ("GITHUB_WORKFLOW_REF",
     "peech-tech/peech-pmo-automation"
     "/.github/workflows/test-suites.yml@refs/heads/main"),
])
def test_a_different_value_for_any_one_fact_is_refused(key, wrong):
    """The same four facts, present but wrong. The last row is this
    repository's own pytest job, which is a GitHub Actions run on a push to
    main and must not inherit the exemption."""
    assert pt_transition.merge_close_out_run({**CLOSE_OUT_ENV, key: wrong}) is False


def test_the_workflow_path_is_matched_on_a_boundary_not_a_suffix():
    """A file whose name merely ends in the registered one is not it."""
    near = ("peech-tech/peech-pmo-automation"
            "/.github/workflows/not-merge-close-out.yml@refs/heads/main")
    assert pt_transition.merge_close_out_run(
        {**CLOSE_OUT_ENV, "GITHUB_WORKFLOW_REF": near}) is False


def test_the_branch_suffix_is_split_off_before_the_path_is_matched():
    """GITHUB_WORKFLOW_REF carries an @ref the path match must not see. The
    sibling repositories are recognised the same way - all three carry the
    workflow at the same path, checked 17-SEP-2026."""
    for repo in ("peech-pmo-automation", "peech-skills", "peech-org-skills"):
        ref = (f"peech-tech/{repo}/.github/workflows/merge-close-out.yml"
               f"@refs/heads/main")
        assert pt_transition.merge_close_out_run(
            {**CLOSE_OUT_ENV, "GITHUB_WORKFLOW_REF": ref}) is True


def test_in_progress_to_done_fires_inside_the_close_out_run(ppa_plan):
    """The hop the two refused runs asked for, end to end. It fires the live
    "Closed - No client approval required" transition, which is the one
    In Progress offers onto Done."""
    stub = StubJira("In Progress", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done",
                  merge_close_out=True)

    assert results[0].verdict == "PASS"
    assert results[0].start == "In Progress"
    assert results[0].end == "Done"
    assert results[0].hops == 1
    assert stub.status == "Done"
    assert [payload["transition"]["id"] for _, payload in stub.posts] == ["3"]
    assert exit_code(results) == 0


def test_the_same_run_without_the_exemption_still_halts(ppa_plan):
    """The control for the case above: one argument apart, and the difference
    is the whole guard."""
    stub = StubJira("In Progress", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done")

    assert results[0].verdict == "HALT"
    assert stub.posts == []
    assert exit_code(results) == 1


def test_the_exemption_covers_in_progress_and_no_other_rung():
    """Narrowed twice over, first half. plan_transition() asks for Done only
    from In Progress, so a close-out run reaching for it from anywhere else has
    lost track of the ticket rather than graded it, and is refused like any
    other caller."""
    assert pt_transition.validation_skipped("To Do", "Done", True) is not None
    assert pt_transition.validation_skipped("Reopened", "Done", True) is not None
    assert pt_transition.validation_skipped("BLOCKED", "Done", True) is not None


def test_the_exemption_is_not_picked_up_part_way_along_the_ladder(ppa_plan):
    """Narrowed twice over, second half, and the case that caught it. A --to
    "Done" run from To Do takes the legitimate ladder hop onto In Progress -
    and must not then inherit the exemption on the next pass, having arrived at
    the exempt rung rather than started there. advance() passes the exemption
    only on the run's first hop, so this halts exactly where a hand run does.
    """
    stub = StubJira("To Do", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done", merge_close_out=True)

    assert results[0].verdict == "HALT"
    assert "'Client Validation'" in results[0].detail
    assert stub.status == "In Progress", (
        "the ladder hop is legitimate on its own and stands; only the hop "
        "onto Done is refused")
    assert [payload["transition"]["id"] for _, payload in stub.posts] == ["10"]
    assert exit_code(results) == 1


def test_client_validation_stays_the_source_every_caller_may_use(ppa_plan):
    """What did not change. The exemption is additive: it grants In Progress to
    the close-out run and takes nothing from anyone."""
    for exempt in (False, True):
        assert pt_transition.validation_skipped(
            "Client Validation", "Done", exempt) is None


def test_the_exemption_reaches_nothing_but_done():
    """The guard still returns None for every hop that does not land on Done,
    exempt or not, so the exemption cannot widen a path it never governed."""
    for destination in ("In Progress", "Client Validation", "Reopened"):
        assert pt_transition.validation_skipped("To Do", destination, True) is None


def test_the_close_out_run_cannot_reach_reopened(ppa_plan):
    """Reopened is a rejection verdict and stays conductor-only. The exemption
    is a source-status waiver on one destination; it is not a role."""
    stub = StubJira("Client Validation", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Reopened",
                  merge_close_out=True)

    assert results[0].verdict == "HALT"
    assert "CONDUCTOR_ONLY" in results[0].detail
    assert stub.posts == []
    assert pt_transition.CONDUCTOR_ONLY == ("Reopened",)


def test_the_refusal_names_the_one_exempt_caller(ppa_plan):
    """Both refused runs printed this line and said nothing about why. A reader
    of the next one is told what the exemption is, so a silent refusal caused
    by a changed runner variable is readable rather than mysterious."""
    reason = pt_transition.validation_skipped("In Progress", "Done")

    assert "merge close-out" in reason
    assert "PPA-1459" in reason
    assert "PPA-1433" in reason


def test_a_dry_run_inside_the_close_out_reports_the_hop_it_would_fire(ppa_plan):
    stub = StubJira("In Progress", ppa_plan)

    results = run(stub.get, stub.post, ["PPA-1"], "Done", dry_run=True,
                  merge_close_out=True)

    assert results[0].verdict == "PASS"
    assert "dry run, nothing fired" in results[0].detail
    assert "'Done'" in results[0].detail
    assert stub.posts == []


def test_the_guard_does_not_reach_around_its_caller_for_the_environment(
        monkeypatch):
    """The exemption is threaded in as an argument, never read from inside the
    guard. Asserted by putting the close-out runner's own variables into the
    real os.environ and confirming nothing changes: a run that was not told it
    is the close-out is refused even while standing in its environment.

    This is why the suite can assert anything at all. A guard reading
    os.environ for itself would make every case above depend on where pytest
    happens to be running, and this suite runs inside GitHub Actions.
    """
    for name, value in CLOSE_OUT_ENV.items():
        monkeypatch.setenv(name, value)

    assert pt_transition.validation_skipped("In Progress", "Done") is not None
    assert pt_transition.merge_close_out_run({}) is False

    source = SOURCE.read_text()
    assert "merge_close_out=merge_close_out_run(os.environ)" in source


def test_the_docstring_records_the_narrowing_rather_than_replacing_the_history():
    """PPA-1459's rule is stated and PPA-1433's is not left standing beside it
    as though it were still whole."""
    doc = pt_transition.__doc__

    assert "PPA-1459" in doc
    assert "narrowed that guard rather than lifting it" in doc
    assert "except In Progress to Done inside a run of" in doc
