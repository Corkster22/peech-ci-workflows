#!/usr/bin/env python3
"""Report a Definition of Done condition demanding an artifact a governed rule bars.

PPA-1472. A condition can require something the rules forbid, and then no
compliant session can satisfy it. Four shipped that way and every one was
found by a person reading the ticket afterwards:

* **PPA-1428 condition 8** - "the change-log rows are quoted"
* **PPA-1429 condition 9** - "its change-log row is quoted"
* **PPA-1451 condition 11** - "a revision-history entry names this ticket"
* **PPA-1453 condition 7** - "version and change log are updated"

All four are one rule: ``pt-documentation-standards/SKILL.md`` line 178, _"Files
in a Peech repository do not carry a change log - this governs
peech-pmo-automation, peech-skills, and peech-org-skills alike, not this repo
alone."_ All four were amended under ruling 8A on 16-SEP-2026.

pt-backlog's Story Creation Checklist already tells an author to check a
condition against the rule that governs it. Four tickets carried the defect
anyway, so the deliverable is a mechanism rather than more text.

The list is hand-maintained, and that was measured
--------------------------------------------------
The first question PPA-1472 asks is whether the barred set can be enumerated
from the governed rules mechanically. It cannot. Measured 17-SEP-2026 against
the peech-skills skill corpus - 117 Markdown files, 19,330 lines::

    $ grep -rn --include='*.md' -E "do(es)? not carry|never carr(y|ies)|carries no " skills | wc -l
    39

Thirty-nine hits on the tightest pattern the change-log bar itself matches, and
almost none of them bar an artifact from a deliverable: an epic that carries no
estimate, a SOW that carries no rate, an ambiguous filename that carries no
coupling, a GO that does not carry across gates. Widening to the shapes a bar
might take is worse - ``never`` 301, ``does not`` 397, ``do not`` 121,
``must not`` 17. A bar is a sentence of ordinary English, and no syntactic
pattern separates "this artifact may not exist" from the several hundred other
negative sentences in the corpus.

So ``BARS`` below is a hand-maintained list. It carries one entry today,
because one bar is what has been measured; a second is added by writing it
down, not by the check discovering it.

**What tells someone it has gone stale.** Nothing here can. The rules live in
``peech-skills`` and this check lives in ``peech-pmo-automation``, so a bar
added there lands with nothing pointing at this file. The signal is the one
that produced this ticket: a condition graded by hand after the fact, found
unsatisfiable, and traced to a rule this list does not carry. That is a person
noticing, and naming it plainly is more use than a freshness test that would
only ever check the one bar already listed. ``rule_quote`` is stored with each
entry for exactly this reason - a bar whose quoted sentence no longer appears
at its stated file and line has moved or been rewritten, and ``--verify-rules``
reports that much where the sibling checkout is present.

Where it runs, and what that cannot catch
-----------------------------------------
Ticket-authoring time, against Jira. The other placement PPA-1472 leaves open
is the existing CI checks, and it is not merely the weaker of the two - it is
blind. A Definition of Done is ``customfield_10767`` on a Jira issue. CI checks
out a repository, where no condition text exists at all, so a CI-sited check
would have nothing to read. The choice is forced rather than judged, which is
worth saying plainly because the ticket presents it as open.

What the chosen placement catches: any condition readable off Jira, on any
ticket, at any point in its life - while it is being authored, at dispatch, or
in a sweep of tickets already closed. What it cannot catch: a requirement that
never reaches ``customfield_10767``. A demand made in the description, in an
amendment comment, or in the dispatch prose is invisible here. PPA-1453 is the
live case in the other direction - its condition 7 was amended in a comment and
the stored field still carries the original wording, so this check reports it
today and is right to.

It reports. It does not block
-----------------------------
``main()`` returns 0 whatever it finds, including on a Jira read failure.
Blocking is a conductor decision and PPA-1472 leaves it out on purpose.

**What making it block would require.** Three things, none of them in this
file. A caller that can refuse - the UserPromptSubmit hook is the only one in
the estate, and it already reads ``customfield_10767`` for the Ticket Quality
Bar, so the read is free and the wiring is one ``BAR_ITEMS`` entry. An opt-out,
because a bar can be wrong and a dispatch cannot be held hostage to this list;
the hook's existing opt-out - naming the key again in prose - would serve. And
a decision about precision: a report may be over-inclusive at no cost, while a
gate that refuses a good ticket costs a dispatch. The detection below is
deliberately tuned for the first of those.

How a demand is told from a mention
-----------------------------------
The four amended conditions all still name the barred artifact - they have to,
because each one says which demand it removes. So a substring test flags every
one of them and the check would be useless.

A condition is split into sentences and each is judged alone. A sentence flags
when it names the artifact and nothing in it withdraws the demand. Two things
withdraw one: a negation binding the artifact ("No change-log row is required
and none is quoted"), and a report of a demand that no longer stands ("The
original condition demanded a quoted change-log row, which ... bars").

A third thing is not a mention at all. ``changelog`` as one word is Jira's
per-issue history, a different object that happens to share a name, and
delegated conditions cite it constantly - PPA-1459 condition 9 has the
conductor read a verdict "off the Jira changelog". The document artifact is
written ``change log`` or ``change-log``, which is how
pt-documentation-standards writes it, so the patterns in ``BARS`` require the
separator. One word is Jira's; two is the artifact.

That is a heuristic over English and it is not stated as anything else. It is
sized for the reporting placement above: over-inclusive is cheap here, and a
sentence it reads wrongly costs a line of output a person dismisses.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Where a sibling checkout sits, for --verify-rules. Absent is a normal state.
SIBLING_ROOT = REPO.parent

#: Seconds to allow a Jira read. This runs ahead of a person, not a workflow.
JIRA_TIMEOUT = 20


@dataclass(frozen=True)
class Bar:
    """One artifact a governed rule forbids, and how a demand for it reads.

    ``artifact`` names the thing for the output. ``rule_repo``, ``rule_file``
    and ``rule_line`` locate the rule so a flag can be checked without knowing
    the corpus, and ``rule_quote`` is the sentence itself - stored so
    --verify-rules can say whether the rule is still where this entry claims.
    """

    artifact: str
    rule_repo: str
    rule_file: str
    rule_line: int
    rule_quote: str
    #: What naming this artifact looks like. Matched per sentence.
    names: tuple[str, ...]


#: The hand-maintained register. One entry, because one bar has been measured.
#: See "The list is hand-maintained, and that was measured" above before adding
#: a second - the shape of the evidence matters more than the count.
BARS: tuple[Bar, ...] = (
    Bar(
        artifact="a change log or revision-history entry",
        rule_repo="peech-skills",
        rule_file="skills/pt-documentation-standards/SKILL.md",
        rule_line=178,
        rule_quote=(
            "Files in a Peech repository do not carry a change log"
        ),
        names=(
            r"change[ -]logs?",
            r"change[ -]log rows?",
            r"revision[ -]histor(y|ies)",
            r"revision[ -]history entr(y|ies)",
        ),
    ),
)

#: A sentence carrying one of these withdraws the demand rather than making it.
#:
#: Three shapes, all of them measured on a 42-ticket sweep rather than
#: imagined. **The amendment** still names the artifact, because it says which
#: demand it removes - without this, every amendment flags as its own defect.
#: **The removal** names it as the thing being taken out: PPA-1468 shipped the
#: check that bars a change log from a skill file and six of its conditions
#: name one. **The governed object** names it as a rule or a section rather
#: than as an artifact a deliverable must carry.
WITHDRAWALS = (
    # The amendment, withdrawing a demand it restates.
    r"\bno\s+(?:\w+[ -]){0,3}(?:change[ -]log|revision[ -]histor)",
    r"\bnone\s+is\s+(?:quoted|required|added)",
    r"\bnot\s+required\b",
    r"\boriginal\s+condition\b",
    r"\bfirst\s+amendment\b",
    r"\bthis\s+amendment\b",
    r"\bunsatisfiable\b",
    r"\bsuperseded?\b",
    # The removal: the artifact is what is being taken out, not required.
    r"\b(?:removed?|removal|deleted?|retired?|stripped?)\b",
    r"\bwithout\s+(?:a\s+)?(?:change[ -]log|revision[ -]histor)",
    # The governed object: a rule, a section name, or a check over it.
    r"\bis\s+barred\b|\bbars\b|\bbarred\b",
    r"\bChange Log Rules\b",
    r"\bcontaining\b",
    r"\bflags?\b|\bflagged\b",
)

_WITHDRAWAL_RE = re.compile("|".join(WITHDRAWALS), re.I)

#: Sentence split. Deliberately crude: a condition is one or two sentences of
#: plain prose, and a parser would be more machinery than the input deserves.
_SENTENCE_RE = re.compile(r"(?<=[.;])\s+")


@dataclass(frozen=True)
class Flag:
    """One condition reported against one bar."""

    key: str
    number: int
    condition: str
    sentence: str
    bar: Bar

    def render(self) -> str:
        """The finding, naming the condition, the artifact and the rule."""
        return (
            f"  {self.key} condition {self.number} demands {self.bar.artifact}\n"
            f"    condition: {self.condition}\n"
            f"    the demand: {self.sentence}\n"
            f"    barred by:  {self.bar.rule_repo}/{self.bar.rule_file}"
            f" line {self.bar.rule_line}\n"
            f"                \"{self.bar.rule_quote}\""
        )


def sentences(condition: str) -> list[str]:
    """The condition's sentences, each judged on its own."""
    return [s.strip() for s in _SENTENCE_RE.split(condition.strip()) if s.strip()]


def demands(sentence: str, bar: Bar) -> bool:
    """True where this sentence demands the bar's artifact.

    Naming the artifact is necessary and not sufficient: a sentence that names
    it while withdrawing the demand is what every amended condition looks like.
    """
    if not any(re.search(name, sentence, re.I) for name in bar.names):
        return False
    return not _WITHDRAWAL_RE.search(sentence)


def flags_for(key: str, conditions: list[str]) -> list[Flag]:
    """Every condition in this ticket demanding a barred artifact."""
    found = []
    for number, condition in enumerate(conditions, 1):
        for bar in BARS:
            hit = next((s for s in sentences(condition) if demands(s, bar)), None)
            if hit:
                found.append(Flag(key, number, condition, hit, bar))
    return found


def barred_demands(key: str, dod) -> list[Flag]:
    """Every barred-artifact demand in one ticket's Definition of Done field.

    The entry point a caller outside this module needs, added by PPA-1520. It
    takes the Atlassian Document Format value ``customfield_10767`` returns and
    hands back the flags, composing the two functions either side of it and
    adding no rule of its own - what is detected, and what ``BARS`` holds, are
    untouched by its existence.

    The caller is the one "What making it block would require" names above: the
    ``UserPromptSubmit`` hook already reads this field for the Ticket Quality
    Bar, so the read costs nothing, the refusal costs one ``BAR_ITEMS`` entry,
    and the opt-out is the one that hook already has.
    """
    return flags_for(key, conditions_from_adf(dod))


def conditions_from_adf(node) -> list[str]:
    """One string per Definition of Done condition.

    A condition is a list item. The REST v3 API returns the field as an
    Atlassian Document Format tree, so the text runs are pulled out per item
    rather than from the document as a whole - the condition is the unit this
    check reports on and flattening the whole field would lose the boundaries.
    """
    out: list[str] = []
    _collect_items(node, out)
    return out


def _collect_items(node, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "listItem":
            out.append(" ".join(_text_runs(node)).strip())
            return
        for child in node.get("content") or []:
            _collect_items(child, out)
    elif isinstance(node, list):
        for child in node:
            _collect_items(child, out)


def _text_runs(node, out: list[str] | None = None) -> list[str]:
    runs: list[str] = [] if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            runs.append(node["text"])
        for child in node.get("content") or []:
            _text_runs(child, runs)
    elif isinstance(node, list):
        for child in node:
            _text_runs(child, runs)
    return runs


def _jira_get(path: str, timeout: int = JIRA_TIMEOUT):
    """One authenticated GET. Raises; the caller reports and returns 0.

    ``pt_transition.load_credentials`` supplies the credentials, so this file
    holds no credential path of its own and there is still one credential home.
    It is read from the peech-ci-workflows clone, its one home (PPA-1662).
    """
    sys.path.insert(0, str(Path.home() / "Documents" / "Claude-Projects"
                           / "peech-ci-workflows" / "scripts"))
    from pt_transition import BASE, load_credentials  # noqa: PLC0415

    creds = load_credentials()
    auth = base64.b64encode(
        f"{creds['JIRA_EMAIL']}:{creds['JIRA_API_TOKEN']}".encode()).decode()
    request = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read())


def definitions_of(keys: list[str]) -> dict[str, list[str]]:
    """{key: [condition, ...]} read live. One search rather than a read per key."""
    query = urllib.parse.urlencode({
        "jql": f"key in ({', '.join(keys)})",
        "fields": "customfield_10767",
        "maxResults": 100,
    })
    data = _jira_get(f"/search/jql?{query}")
    return {
        issue["key"].upper():
            conditions_from_adf(issue["fields"].get("customfield_10767"))
        for issue in data.get("issues") or []
    }


def verify_rules() -> list[str]:
    """Notes on whether each bar's rule is still at its stated file and line.

    A sibling that is not checked out is skipped rather than reported: a
    machine holding one checkout is a normal state, not a stale register.
    """
    notes = []
    for bar in BARS:
        root = SIBLING_ROOT / bar.rule_repo
        source = root / bar.rule_file
        if not (root / "CLAUDE.md").is_file():
            notes.append(f"{bar.rule_repo} is not checked out beside this "
                         f"repository, so {bar.artifact} was not verified.")
            continue
        if not source.is_file():
            notes.append(f"{bar.rule_file}: absent from {bar.rule_repo}. The "
                         f"bar on {bar.artifact} names a file that is gone.")
            continue
        lines = source.read_text().splitlines()
        at_line = lines[bar.rule_line - 1] if len(lines) >= bar.rule_line else ""
        if bar.rule_quote in at_line:
            notes.append(f"{bar.rule_file} line {bar.rule_line}: the bar on "
                         f"{bar.artifact} is where this register says it is.")
        elif any(bar.rule_quote in line for line in lines):
            moved = next(n for n, line in enumerate(lines, 1)
                         if bar.rule_quote in line)
            notes.append(f"{bar.rule_file}: the bar on {bar.artifact} has moved "
                         f"from line {bar.rule_line} to line {moved}. The "
                         f"register's line number is stale.")
        else:
            notes.append(f"{bar.rule_file}: the quoted bar on {bar.artifact} is "
                         f"no longer in this file. Either it was rewritten or "
                         f"it was retired, and this register cannot tell which.")
    return notes


def report(flagged: dict[str, list[Flag]], read: list[str],
           unread: list[str], notes: list[str]) -> None:
    print("=== Definition of Done — barred artifacts (PPA-1472) ===")
    print(f"{len(read)} ticket(s) read, {len(BARS)} bar(s) in the register.")
    if unread:
        print(f"not returned by Jira, so not checked: {', '.join(unread)}")
    print()

    total = sum(len(v) for v in flagged.values())
    if not total:
        print("No condition demands a barred artifact.")
    else:
        print(f"{total} condition(s) demand an artifact a governed rule bars:\n")
        for key in sorted(flagged):
            for flag in flagged[key]:
                print(flag.render())
                print()

    for note in notes:
        print(f"note: {note}")
    print("\nThis reports. It does not block - see the module docstring for "
          "what making it block would require.")


def main(argv=None) -> int:
    """Always 0. See "It reports. It does not block" above."""
    parser = argparse.ArgumentParser(
        description="Report a Definition of Done condition demanding an "
                    "artifact a governed rule bars.")
    parser.add_argument("--keys", required=True,
                        help="comma-separated PPA keys to read")
    parser.add_argument("--verify-rules", action="store_true",
                        help="also report whether each bar's rule is still at "
                             "its stated file and line")
    args = parser.parse_args(argv)

    keys = [k.strip().upper() for k in args.keys.split(",") if k.strip()]
    if not keys:
        print("no keys given", file=sys.stderr)
        return 0

    try:
        definitions = definitions_of(keys)
    except Exception as exc:  # noqa: BLE001 - a read failure reports, never blocks
        print(f"Definition of Done not checked - {exc}", file=sys.stderr)
        return 0

    flagged = {key: flags for key, conditions in definitions.items()
               if (flags := flags_for(key, conditions))}
    notes = verify_rules() if args.verify_rules else []
    report(flagged, sorted(definitions), [k for k in keys if k not in definitions],
           notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
