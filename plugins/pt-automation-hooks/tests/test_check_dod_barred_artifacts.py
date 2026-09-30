"""check_dod_barred_artifacts.py — the four measured instances, before and after.

PPA-1472. Every fixture below is a real condition, not an invented one. The
pre-amendment strings were recovered from each ticket's own
``customfield_10767`` field history over the Jira changelog API on
17-SEP-2026 - the ``fromString`` of the entry that applied ruling 8A - rather
than reconstructed from the amendments that describe them. PPA-1453 is the
exception and needs no recovery: its condition 7 was amended in a comment and
never in the field, so the string below is what Jira stores today.

The pairs are the whole test. Flagging the four demands is easy and a
substring test would do it; not flagging the four amendments that describe the
demands they remove is the part that needs the sentence rule.
"""

import check_dod_barred_artifacts as chk
import pytest


# --------------------------------------------------------------------------
# The four measured instances, pre-amendment. Each must flag.
# --------------------------------------------------------------------------

BEFORE = {
    "PPA-1428": (
        8,
        "The SKILL.md version and the tests.md version are bumped per "
        "pt-skill-governance, and the change-log rows are quoted."
    ),
    "PPA-1429": (
        9,
        "The pt-backlog SKILL.md version is bumped per pt-skill-governance "
        "and its change-log row is quoted."
    ),
    "PPA-1451": (
        11,
        "The version header of pt-backlog SKILL.md and tests.md is bumped, "
        "the level named and justified, and a revision-history entry names "
        "this ticket."
    ),
    "PPA-1453": (
        7,
        "Each edited skill's version and change log are updated per "
        "pt-skill-governance, and the version of each is quoted before and "
        "after."
    ),
}

# --------------------------------------------------------------------------
# The same four, post-amendment under ruling 8A. None may flag. Each still
# names the artifact, because each says which demand it removes - which is
# exactly why a substring test cannot be the rule.
# --------------------------------------------------------------------------

AFTER = {
    "PPA-1428": (
        8,
        "AMENDED 16-SEP-2026, conductor, ruling 8A. The SKILL.md version and "
        "the tests.md version are bumped per pt-skill-governance, and the "
        "level is named and justified. No change-log row is required and none "
        "is quoted. The original condition demanded a quoted change-log row, "
        "which pt-documentation-standards SKILL.md line 178 bars in any file "
        "in a Peech repository, making it unsatisfiable without breaking the "
        "rule that skill carries. The ticket is recorded in the commit "
        "message instead. This ticket's own close-out named the collision and "
        "was correct to; this amendment records that outcome and adds no new "
        "requirement."
    ),
    "PPA-1429": (
        9,
        "AMENDED 16-SEP-2026, conductor, ruling 8A. The pt-backlog SKILL.md "
        "version is bumped per pt-skill-governance and the level is named and "
        "justified. No change-log row is required and none is quoted. The "
        "original condition demanded a quoted change-log row, which "
        "pt-documentation-standards SKILL.md line 178 bars in any file in a "
        "Peech repository, making it unsatisfiable without breaking the rule "
        "that skill carries. The ticket is recorded in the commit message "
        "instead. This amendment adds no new requirement."
    ),
    "PPA-1451": (
        11,
        "AMENDED 16-SEP-2026, conductor, ruling 8A. This supersedes the "
        "earlier amendment of the same day, which was wrong. The version "
        "header of pt-backlog SKILL.md and tests.md is bumped and the level "
        "is named and justified. No revision-history entry is required in any "
        "file, and the ticket is recorded in the commit message instead. The "
        "original condition demanded a revision-history entry in SKILL.md; "
        "the first amendment moved it to tests.md on the reasoning that the "
        "file already carries such a section. That was wrong on the same "
        "rule: pt-documentation-standards SKILL.md line 178 bars a change log "
        "in any file in a Peech repository, so tests.md is barred too and the "
        "first amendment relocated the defect rather than removing it. The "
        "session refused the original condition correctly. This amendment "
        "adds no new requirement."
    ),
    "PPA-1453": (
        7,
        "AMENDED 16-SEP-2026, conductor, ruling 8A. Each edited skill's "
        "version is bumped per pt-skill-governance, the level named and "
        "justified, and the version of each quoted before and after. No "
        "change log is required and none is quoted: pt-documentation-"
        "standards SKILL.md line 178 bars a change log in any file in a Peech "
        "repository. The ticket is recorded in the commit message instead. "
        "This amendment adds no requirement."
    ),
}


@pytest.mark.parametrize("key", sorted(BEFORE))
def test_the_pre_amendment_condition_is_flagged(key):
    """Each of the four as it shipped. All four demand a barred artifact."""
    number, text = BEFORE[key]
    conditions = [""] * (number - 1) + [text]

    flags = chk.flags_for(key, conditions)

    assert len(flags) == 1, f"{key} produced {len(flags)} flags"
    assert flags[0].number == number


@pytest.mark.parametrize("key", sorted(AFTER))
def test_the_post_amendment_condition_is_not_flagged(key):
    """A version bump with no change log is not a demand for one.

    Every string here still contains "change-log row" or "revision-history
    entry", because each amendment states which demand it removes.
    """
    number, text = AFTER[key]
    conditions = [""] * (number - 1) + [text]

    assert chk.flags_for(key, conditions) == []


def test_all_four_flag_together_and_none_of_the_amendments_do():
    """The population as one run: four flags before, zero after."""
    before = sum(len(chk.flags_for(k, [t])) for k, (_n, t) in BEFORE.items())
    after = sum(len(chk.flags_for(k, [t])) for k, (_n, t) in AFTER.items())

    assert (before, after) == (4, 0)


# --------------------------------------------------------------------------
# What a flag says
# --------------------------------------------------------------------------

def test_a_flag_names_the_condition_the_artifact_and_the_rule():
    """PPA-1472 condition 4: each flag carries all three, with file and line."""
    number, text = BEFORE["PPA-1428"]
    flag = chk.flags_for("PPA-1428", [""] * (number - 1) + [text])[0]

    rendered = flag.render()

    assert "PPA-1428 condition 8" in rendered
    assert "change log" in rendered
    assert "skills/pt-documentation-standards/SKILL.md line 178" in rendered
    assert "Files in a Peech repository do not carry a change log" in rendered
    assert "the change-log rows are quoted" in rendered


def test_the_flag_quotes_the_sentence_that_demanded_it():
    """Not the whole condition: a long condition would bury the demand.

    All four measured instances are one sentence, so the pair is built here
    rather than quoted - PPA-1451's wording with a second sentence after it.
    """
    condition = (BEFORE["PPA-1451"][1]
                 + " The line count is quoted before and after.")

    flag = chk.flags_for("PPA-1451", [condition])[0]

    assert flag.sentence.endswith("a revision-history entry names this ticket.")
    assert "line count" not in flag.sentence
    assert flag.condition == condition


# --------------------------------------------------------------------------
# The sentence rule, on its own
# --------------------------------------------------------------------------

BAR = chk.BARS[0]


def test_a_sentence_naming_the_artifact_plainly_is_a_demand():
    assert chk.demands("Its change-log row is quoted.", BAR)


def test_a_negated_sentence_is_not_a_demand():
    assert not chk.demands("No change-log row is required and none is quoted.", BAR)


def test_a_sentence_reporting_a_removed_demand_is_not_a_demand():
    assert not chk.demands(
        "The original condition demanded a quoted change-log row.", BAR)


def test_a_sentence_naming_the_rule_that_bars_it_is_not_a_demand():
    assert not chk.demands(
        "pt-documentation-standards SKILL.md line 178 bars a change log in "
        "any file in a Peech repository.", BAR)


def test_a_sentence_naming_no_barred_artifact_is_not_a_demand():
    assert not chk.demands(
        "The pt-backlog SKILL.md version is bumped per pt-skill-governance.",
        BAR)


def test_a_condition_is_judged_sentence_by_sentence():
    """A demand in one sentence is not withdrawn by a later unrelated one."""
    condition = ("Its change-log row is quoted. The original condition "
                 "demanded nothing else.")

    assert chk.flags_for("PPA-1", [condition])


# --------------------------------------------------------------------------
# Reading the field
# --------------------------------------------------------------------------

def test_conditions_are_read_one_per_list_item():
    """The condition is the unit reported on, so the boundaries must survive."""
    adf = {"type": "doc", "content": [{"type": "bulletList", "content": [
        {"type": "listItem", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "First."}]}]},
        {"type": "listItem", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "Its change-log row is quoted."}]}]},
    ]}]}

    conditions = chk.conditions_from_adf(adf)

    assert conditions == ["First.", "Its change-log row is quoted."]
    assert chk.flags_for("PPA-1", conditions)[0].number == 2


def test_an_absent_definition_of_done_reads_as_no_conditions():
    assert chk.conditions_from_adf(None) == []


# --------------------------------------------------------------------------
# It reports; it does not block
# --------------------------------------------------------------------------

def test_a_jira_read_failure_still_returns_zero(monkeypatch, capsys):
    """PPA-1472 condition 6. Nothing here refuses anything."""
    def boom(_keys):
        raise RuntimeError("Jira is down")

    monkeypatch.setattr(chk, "definitions_of", boom)

    assert chk.main(["--keys", "PPA-1428"]) == 0
    assert "Jira is down" in capsys.readouterr().err


def test_a_run_that_flags_four_conditions_still_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(chk, "definitions_of",
                        lambda keys: {k: [BEFORE[k][1]] for k in keys})

    assert chk.main(["--keys", "PPA-1428,PPA-1429,PPA-1451,PPA-1453"]) == 0

    out = capsys.readouterr().out
    assert "4 condition(s) demand an artifact a governed rule bars" in out
    assert "It does not block" in out


def test_a_clean_run_says_so_rather_than_printing_nothing(monkeypatch, capsys):
    monkeypatch.setattr(chk, "definitions_of",
                        lambda keys: {k: ["Tests pass."] for k in keys})

    chk.main(["--keys", "PPA-1"])

    assert "No condition demands a barred artifact." in capsys.readouterr().out


def test_a_key_jira_does_not_return_is_named_rather_than_dropped(monkeypatch,
                                                                capsys):
    monkeypatch.setattr(chk, "definitions_of", lambda keys: {"PPA-1": []})

    chk.main(["--keys", "PPA-1,PPA-2"])

    assert "not returned by Jira, so not checked: PPA-2" in capsys.readouterr().out


# --------------------------------------------------------------------------
# The register is hand-maintained, and says so
# --------------------------------------------------------------------------

def test_every_bar_locates_its_rule_by_repository_file_and_line():
    """A flag a reader cannot check is a flag they will learn to ignore."""
    for bar in chk.BARS:
        assert bar.rule_repo and bar.rule_file and bar.rule_line > 0
        assert bar.rule_quote


def test_verify_rules_reports_a_moved_rule_rather_than_a_clean_result(tmp_path,
                                                                     monkeypatch):
    """The one staleness signal available: the quoted sentence has moved."""
    root = tmp_path / "peech-skills"
    (root / "skills" / "pt-documentation-standards").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("stub\n")
    target = root / "skills" / "pt-documentation-standards" / "SKILL.md"
    target.write_text("filler\n" * 3 + chk.BARS[0].rule_quote + " etc\n")

    monkeypatch.setattr(chk, "SIBLING_ROOT", tmp_path)

    assert "has moved from line 178 to line 4" in " ".join(chk.verify_rules())


def test_verify_rules_skips_a_sibling_that_is_not_checked_out(tmp_path,
                                                             monkeypatch):
    monkeypatch.setattr(chk, "SIBLING_ROOT", tmp_path)

    assert "is not checked out" in " ".join(chk.verify_rules())


# --------------------------------------------------------------------------
# Precision, measured rather than assumed
#
# A sweep of PPA-1440 to PPA-1481 on 17-SEP-2026 produced seven flags. One was
# real - PPA-1453 condition 7, still unamended in the field. The other six are
# the three shapes below, quoted from the conditions that produced them. The
# sweep after the fix produces one flag, and it is PPA-1453's.
# --------------------------------------------------------------------------

def test_jiras_own_changelog_is_not_the_barred_artifact():
    """PPA-1459 condition 9. One word is Jira's per-issue history; the
    document artifact is two words or hyphenated."""
    assert not chk.flags_for("PPA-1459", [
        "The event that produces this evidence is the next merge of a ticket "
        "whose conditions are all [machine] and all reported met; the "
        "conductor reads it off the Jira changelog and the run log afterwards."
    ])


@pytest.mark.parametrize("condition", [
    # PPA-1468 condition 2
    "Every file whose revision-history section was removed is listed by path.",
    # PPA-1468 condition 3
    "Evidence: a diff of each changed file showing only the revision-history "
    "block removed, with the test count per file quoted before and after.",
])
def test_removing_the_artifact_is_not_demanding_it(condition):
    """PPA-1468 shipped the check that bars a change log from a skill file.
    Six of its conditions name one, and every mention is a removal."""
    assert chk.flags_for("PPA-1468", [condition]) == []


@pytest.mark.parametrize("condition", [
    # PPA-1468 condition 4
    "check_skill_conformance.py carries a new BLOCKING check that fails a "
    "file under skills/ containing a change-log or revision-history section.",
    # PPA-1468 condition 6
    "The finding text points at pt-documentation-standards section Change Log "
    "Rules and does not restate the rule.",
    # PPA-1472 condition 5 - this ticket's own
    "The check does not flag a condition that requires a version bump without "
    "a change log, proved against the post-amendment text of the same four "
    "conditions.",
])
def test_the_artifact_as_a_governed_object_is_not_a_demand(condition):
    """A rule, a section name or a check over the artifact is not a deliverable
    that must carry one."""
    assert chk.flags_for("PPA-1", [condition]) == []
