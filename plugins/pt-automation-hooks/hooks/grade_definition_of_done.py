#!/usr/bin/env python3
"""Stop hook (PPA-1519) — grade the Definition of Done before the stop lands.

A close-out that leaves a condition unstated, or states one not met, is not a
close-out the session may end on. Three close-outs on 17-SEP-2026 also wrote
"reported, not fixed" and "reported, not acted on" where the standing findings
condition allows three outcome words and only three, and each was graded met.
This reads the turn's own output at the Stop event, pairs every verdict it
states against the conditions ``customfield_10767`` carries, and refuses the
stop when a condition has no verdict, reads not met, or a finding names an
outcome that is none of the three.

What it shares and what it does not
-----------------------------------
The pairing is ``pr_merge_close_out.pair_rows``, imported rather than rewritten
— PPA-1517 ships it and there is one definition of it in the estate. The
extractor is this file's own only in the sense of where it reads from: the
close-out here is plain text that never passed through ADF, so the rows come
from ``section_rows(text.splitlines(), key)`` where the merge passes
``adf_lines(body)``. Two adapters, one pairing function, exactly as PPA-1517's
own docstring describes. ``section_rows`` is ``stated_rows`` narrowed to one
key's section (PPA-1656), and each key is graded against its own rows only
(PPA-1619).

Key resolution is ``transition_on_prompt.dispatched_keys``, imported the same
way. The keys this session is working are the keys its dispatch prompt named,
and the dispatch prompt is the latest user message in the transcript that is a
well-formed dispatch (PPA-1720).

The platform constraints this is written against
------------------------------------------------
Read from Anthropic's hooks reference, 17-SEP-2026, with the first item read
from community sources the reference section did not cover.

* ``stop_hook_active`` is checked first and the hook exits 0 when it is true,
  before any Jira read. Without that guard a condition the session cannot
  satisfy holds the session until it times out. There is no prose opt-out,
  because the guard **is** the release valve: the first stop is refused, the
  session is handed the list, and the stop after it passes whatever the session
  did with the list. A gate that cannot be escaped is a gate that has to be
  uninstalled.
* The verdict is JSON on stdout — ``{"decision": "block", "reason": ...}`` —
  rather than an exit code alone, because the unmet conditions have to reach
  the session as text it can work from. The list **is** the value of the gate;
  a bare exit code carries none of it.
* The reason is written against the 10,000-character cap. It states condition
  numbers and verdicts, never the evidence behind them, and is clipped at
  ``REASON_CAP`` below that cap in any case.
* The Jira read carries ``JIRA_TIMEOUT`` seconds, shorter than the 60-second
  hook timeout declared in ``.claude/settings.json``. A stalled hook renders no
  decision, and a grader that hangs is a gate that silently passes.
* Hooks on one event run in parallel, so this runs beside the pytest gate and
  the CLAUDE.md gate rather than after them, and shares no state with either.
* A session whose keys cannot be resolved refuses the stop, and so does one
  whose Jira read fails. A gate that passes when it cannot tell what to grade
  is the failure this closes.

Resolved is not the same as dispatched
--------------------------------------
A session whose transcript reads cleanly and carries no dispatch line has
resolved the question — nothing was dispatched, so there is no Definition of
Done to grade — and it passes. A session whose transcript cannot be read, and a
session whose first line carries keys but is not a dispatch, have not resolved
it and are refused, unless a well-formed dispatch was sent as well. The
distinction is ``transition_on_prompt``'s own, drawn
between a prompt that dispatches nothing and one that is a malformed dispatch,
and it is drawn here for the same reason: refusing every ordinary session in
the repository would make the gate the first thing anyone removed.
"""

import base64
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

# Path resolution for the pt-automation-hooks plugin copy (PPA-1586). The
# docstring above still describes the peech-pmo-automation layout. PPA-1600
# then extended this copy alone, so it is the one to edit from here.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from refresh_ci_workflows import CLONE_SCRIPTS  # noqa: E402

# pr_merge_close_out.py (PPA-1605, Decision 3A) and pt_transition.py (PPA-1581,
# PPA-1662) each have one copy, in peech-ci-workflows, read from the local clone
# CLAUDE.md imports delegation.md from.
CLOSE_OUT = CLONE_SCRIPTS / "pr_merge_close_out.py"
if not CLOSE_OUT.is_file():
    # A missing clone warns and passes, as the dispatch hook does for its own
    # missing file. It never blocks a stop: nothing the session can do inside
    # the turn puts the clone there.
    print(json.dumps({"systemMessage": (
        f"pt-automation-hooks: {CLOSE_OUT} is missing, so the Definition of "
        "Done gate did not run. Clone peech-ci-workflows to that path.")}))
    sys.exit(0)
sys.path.append(str(CLOSE_OUT.parent))

# noqa: E402 below — the sys.path inserts above have to run first.
from pt_transition import BASE, load_credentials  # noqa: E402
from pr_merge_close_out import (  # noqa: E402
    conditions_in,
    pair_rows,
    section_rows,
    stated_rows,
)
from transition_on_prompt import (  # noqa: E402
    dispatched_keys,
    malformed_dispatch_warning,
)

#: Seconds allowed for one Jira read. Shorter than the 60-second hook timeout
#: in .claude/settings.json on purpose, and by enough that a read which is
#: merely slow still returns a verdict rather than being killed mid-flight.
JIRA_TIMEOUT = 15

#: Where the reason is clipped. The platform cap is 10,000 characters; this
#: sits below it so a clipped reason is still a whole reason, and it is reached
#: only by a ticket with far more conditions than any in the estate.
REASON_CAP = 9000

#: The Definition of Done field. Named once, here.
DOD_FIELD = "customfield_10767"


# ------------------------------------------------------------- the transcript

def transcript_records(path):
    """Every JSON record in the transcript. Raises OSError where it cannot be read.

    [] means one thing only: a transcript that was read and holds no record.
    An unreadable transcript raises instead, and the two are opposite verdicts
    — a refusal against a pass. They were the same value here until PPA-1519's
    own gate was read against its ticket: this swallowed the OSError and the
    caller tested ``Path.is_file()``, which a file with no read permission
    passes, so an unreadable transcript arrived at the caller as an empty list
    and was graded as a session that dispatched nothing. The open is the test.
    """
    if not path:
        raise OSError("the payload carried no transcript_path")
    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def message_text(record):
    """The text of one transcript record, whatever shape its content takes.

    A user record carries a string; an assistant record carries a list of
    blocks, of which only the ``text`` ones are the message. Thinking and tool
    calls are neither the dispatch nor the close-out and are dropped here.
    """
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text")
    return ""


def session_keys(records):
    """(keys, malformed) for this session's dispatch.

    PPA-1720. The latest user message stating a dispatch wins. The first one
    used to, and a malformed first prompt ended the search, so a keys-only
    dispatch sent after it was never read (PPA-1714, 29-SEP-2026: the gate
    refused twice as unresolvable and the work shipped ungraded). The same
    fixed-to-the-first shape graded PPA-1691's push against a superseded set.

    ``malformed`` is set only where no prompt in the session is a well-formed
    dispatch and a first line carries keys anyway - a prompt whose keys cannot
    be resolved, as against one that names none. It is the first such warning.
    A malformed prompt after a well-formed dispatch is a follow-up that opens
    on a key, not a re-dispatch, and does not undo the dispatch: refusing on it
    would stop every session whose user typed "PPA-1720 looks done, push it".
    """
    keys, malformed = [], None
    for record in records:
        if record.get("type") != "user" or record.get("isMeta"):
            continue
        text = message_text(record)
        found = dispatched_keys(text)
        if found:
            keys = found
        elif not malformed:
            malformed = malformed_dispatch_warning(text)
    return (keys, None) if keys else ([], malformed)


def last_assistant_message(records):
    """The last thing the session said, which is the close-out."""
    for record in reversed(records):
        if record.get("type") == "assistant":
            text = message_text(record).strip()
            if text:
                return text
    return ""


def close_out_text(payload, records):
    """(the turn's own output, where it came from).

    ``last_assistant_message`` on the payload is the carrier the ticket names
    and is preferred whenever it is populated. The transcript is read only when
    it is not, because the payload's field set is what this is confirming on
    its first live run and a gate that cannot see the close-out refuses every
    stop until someone removes it.
    """
    text = str(payload.get("last_assistant_message") or "").strip()
    if text:
        return text, "last_assistant_message"
    return last_assistant_message(records), "transcript"


# -------------------------------------------------------------------- Jira

def jira_get(path, timeout=JIRA_TIMEOUT):
    """One authenticated GET, on a timeout. Raises; the caller refuses.

    ``pt_transition.load_credentials`` supplies the credentials, so this file
    holds no credential path of its own and there is still one credential home.
    """
    creds = load_credentials()
    auth = base64.b64encode(
        f"{creds['JIRA_EMAIL']}:{creds['JIRA_API_TOKEN']}".encode()).decode()
    request = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read())


def conditions_of(key, get=jira_get):
    """Every Definition of Done condition on this key, in the field's order."""
    issue = get(f"/issue/{key}?fields={DOD_FIELD}")
    return conditions_in((issue.get("fields") or {}).get(DOD_FIELD))


# ------------------------------------------------------------- the grading

def grade(conditions, rows):
    """(unmet, unstated, defects) for one ticket's conditions against one turn.

    ``unmet`` is [(condition number, the verdict written)] and ``unstated`` is
    [condition number]; both are the field's own numbering, which is what
    ``pair_rows`` files a row under whatever number the close-out typed.

    ``rows`` are this key's own section of the close-out, extracted by the
    caller, because whether any key's section yielded a row at all decides
    which refusal is written and that is asked once for the turn.
    """
    pairing = pair_rows(conditions, rows)
    unmet = []
    unstated = []
    for index in range(len(conditions)):
        verdict = pairing.verdicts.get(index + 1)
        if verdict is None:
            unstated.append(index + 1)
        elif verdict != "MET":
            unmet.append((index + 1, verdict))
    return unmet, unstated, pairing.defects


#: What opens a finding in a close-out, at the head of a line: the word itself,
#: through the list marker and the bold markers a Markdown close-out wraps it
#: in. Anchored, because "the finding" mid-sentence opens nothing.
_FINDING_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*|__)?\s*findings?\b", re.IGNORECASE)

#: What closes one: a Markdown heading, or the next finding.
_HEADING_RE = re.compile(r"^\s*#{1,6}\s")

#: A finding block that says there were none. It is the shape a clean close-out
#: writes - "Findings: none" - and it states no outcome because there is
#: nothing to state one about.
#:
#: Read off the finding's opening line, and only straight after the word
#: "findings". It searched the whole block for "none" or "nothing" until
#: PPA-1600, so a real finding that said "nothing reads that prose" or "the
#: gate prints nothing" was skipped as a clean close-out, outcome unread.
_NO_FINDINGS_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:\*\*|__)?\s*(?:findings?\W*(?:none|nothing)\b"
    r"|no\s+findings\b)", re.IGNORECASE)

#: The three outcomes the standing findings condition allows, each with the
#: spellings a close-out writes: the condition's own wording, CLAUDE.md's
#: numbered form, and the imperative the rule text uses. Nothing else counts -
#: "reported, not fixed" and "reported, not acted on" are what this closes, and
#: widening these to admit them would retire the check.
OUTCOMES = {
    "fixed here": re.compile(
        r"\bfix(?:ed)?\s+(?:it\s+)?here\b|\boutcome\s*1\b", re.IGNORECASE),
    "dropped": re.compile(
        r"\bdropped\b|\bcomment\s+and\s+drop\b|\boutcome\s*2\b", re.IGNORECASE),
    "ticketed": re.compile(
        r"\bticketed\b|\bticket\s+it\b|\boutcome\s*3\b", re.IGNORECASE),
}

#: A negation immediately before an outcome word, which turns a statement of
#: the outcome into a denial of it. "not fixed here" names no outcome.
_NEGATED_RE = re.compile(r"\b(?:not|never|no)\s+$", re.IGNORECASE)


def states_outcome(pattern, text):
    """True when this outcome is stated somewhere in the block, not denied."""
    return any(
        not _NEGATED_RE.search(text[max(0, m.start() - 12):m.start()])
        for m in pattern.finditer(text))


#: What a dropped finding must carry (PPA-1600): the question the drop answers,
#: stated, with an answer after it. The answer is not judged - "nothing
#: observable, the CLI mode alone reads it" passes - because whether the named
#: consequence is small is the conductor's read, not this hook's.
_BREAKS_RE = re.compile(
    r"\bwhat\s+(?:breaks|would\s+break)\s+if\s+(?:it\s+is\s+)?(?:not|never)"
    r"\s+fixed\b\W*?[:\-\u2013\u2014]\s*\S", re.IGNORECASE)


def finding_blocks(text):
    """(the finding's opening line, its whole block) for each finding stated.

    A finding runs from its own opening line to the next finding, the next
    Markdown heading, or the end of the text - whichever comes first. That is a
    blunt boundary and it is chosen for being predictable rather than clever: a
    close-out that buries a finding's outcome under an unrelated heading has
    written a report the reader cannot pair either. A block that says there
    were no findings is not one.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _FINDING_RE.match(line)]
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        for i in range(start + 1, end):
            if _HEADING_RE.match(lines[i]):
                end = i
                break
        block = "\n".join(lines[start:end])
        if not _NO_FINDINGS_RE.match(lines[start]):
            yield " ".join(lines[start].split())[:110], block


def findings_without_outcome(text):
    """Each finding this close-out states whose outcome is none of the three."""
    return [head for head, block in finding_blocks(text)
            if not any(states_outcome(p, block) for p in OUTCOMES.values())]


def drops_without_breakage(text):
    """Each finding marked dropped that does not name what breaks (PPA-1600).

    Fixed-here and ticketed findings are not read here, and a finding naming no
    outcome is findings_without_outcome's to report.
    """
    return [head for head, block in finding_blocks(text)
            if states_outcome(OUTCOMES["dropped"], block)
            and not _BREAKS_RE.search(block)]


# ------------------------------------------------------------ the verdict

#: One JSON record per firing, appended. Outside every repository, the same
#: place and for the same reason as transition_on_prompt.py's own log: what the
#: Stop payload carries cannot be read from inside the turn that writes the
#: close-out, because the payload reaches the hook after that turn is composed.
#: The record is the field set and nothing from inside it, so no close-out text
#: and no ticket content leaves the process.
LOG = Path.home() / ".claude" / "dod-gate-hook.log"


def log(payload, outcome):
    """Record the payload's shape and this firing's outcome. Never raises."""
    try:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": datetime.datetime.now().isoformat(timespec="seconds"),
                "keys": sorted(payload),
                "stop_hook_active": payload.get("stop_hook_active"),
                "has_last_assistant_message":
                    bool(str(payload.get("last_assistant_message") or "").strip()),
                "outcome": outcome,
            }) + "\n")
    except OSError:
        pass


def block(reason):
    """Refuse the stop, handing the session the list it has to work from."""
    print(json.dumps({"decision": "block", "reason": reason[:REASON_CAP]}))
    return 0


def did_not_run(why):
    return block(
        f"Definition of Done gate: the gate did not run — {why}. The stop is "
        "refused rather than passed, because a gate that cannot tell what to "
        "grade must not report a pass. Fix the cause or stop again; the second "
        "stop carries stop_hook_active and is not graded.")


#: What the shared extractor reads, stated as the two shapes a close-out can
#: be written in. Named here rather than derived from the regexes: a session
#: reading this has to write a close-out, not match a pattern, and the example
#: is the useful half. The authority is ``stated_rows`` either way - this text
#: describes that function and does not decide anything.
SHAPES = (
    '  * a line opening with a condition number and carrying a verdict at a\n'
    '    sentence boundary:  1. <the condition text, quoted> - MET\n'
    '  * a pipe table row whose first non-empty cell is a condition number and\n'
    '    whose later cell is a verdict alone:\n'
    '      | 1 | <the condition text, quoted> | MET |'
)


def no_rows(keys):
    """Refuse a close-out nothing can read as a checklist, and say which it is.

    The distinction this draws is the whole point. A close-out stating no
    verdicts and a close-out stating every verdict in prose both extract zero
    rows, so both used to arrive as one "no verdict in this turn" line per
    condition - and a session reading that restates the same prose, because it
    is being told its verdicts are missing when they are present and unreadable.

    Said once, and the per-condition list is suppressed. Enumerating conditions
    here would bury the one fact that changes what the session does next.
    """
    return block(
        "Definition of Done gate: this stop is refused. No checklist row was "
        "found in this turn's output, so nothing could be paired against the "
        f"Definition of Done of {', '.join(keys)}.\n"
        "This is the close-out's shape, not a missing verdict: a close-out "
        "written as prose states no row even when it states every condition "
        "met.\n"
        "The shared extractor reads two shapes and no others:\n"
        + SHAPES + "\n"
        "A verdict is MET, NOT MET or NOT YET MET. Rewrite the close-out as a "
        "numbered list or a table in one of those shapes, quoting each "
        "condition's own text, then stop again - the second stop carries "
        "stop_hook_active and is not graded.")


def reason_lines(reports, unworded, unbroken=()):
    """One line per thing that refuses the stop. Verdicts and numbers only."""
    lines = []
    for key, unmet, unstated, defects in reports:
        lines.extend(f"{key} condition {n}: no verdict in this turn."
                     for n in unstated)
        lines.extend(f"{key} condition {n}: {verdict}." for n, verdict in unmet)
        lines.extend(f"{key}: {defect}." for defect in defects)
    lines.extend(
        f'finding states no allowed outcome — one of "fixed here", "dropped" '
        f'or "ticketed" is required: {finding}'
        for finding in unworded)
    lines.extend(
        f'finding is dropped but does not name what breaks if it is never fixed '
        f'- add a line "What breaks if not fixed: <the consequence>" to it: '
        f'{finding}'
        for finding in unbroken)
    return lines


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        payload = {}
    try:
        code, outcome = _grade(payload)
    except Exception as exc:  # noqa: BLE001 — a gate that raises must not pass
        code, outcome = did_not_run(f"the gate itself raised {exc!r}"), "raised"
    log(payload, outcome)
    return code


def _grade(payload):
    """(exit code, what this firing did). Every return names its own outcome."""
    # First, and before any Jira read. See the platform constraints above.
    if payload.get("stop_hook_active"):
        return 0, "re-entry"

    path = payload.get("transcript_path")
    try:
        records = transcript_records(path)
    except OSError as exc:
        return did_not_run(
            "this session's transcript could not be read "
            f"({exc.__class__.__name__}), so the PPA keys it is working could "
            "not be resolved"), "unreadable-transcript"
    keys, malformed = session_keys(records)
    if malformed:
        return (did_not_run(f"the dispatch could not be resolved — {malformed}"),
                "malformed-dispatch")
    if not keys:
        # Resolved, and the answer is that nothing was dispatched. There is no
        # Definition of Done to grade and nothing to refuse.
        return 0, "nothing-dispatched"

    text, source = close_out_text(payload, records)
    if not text:
        return did_not_run(
            "this turn produced no output, so there are no verdicts to pair "
            f"against the Definition of Done of {', '.join(keys)}"), "no-output"

    # Each key's rows come from its own section of the close-out, through the
    # function scripts/pr_merge_close_out.py grades a merge with (PPA-1619). A
    # multi-ticket close-out opens each ticket's rows with a line naming its
    # key, and a row filed against every key was PR #129's 14-rows-against-7
    # refusal. With no such line every row belongs to every key, so a
    # single-ticket close-out reads exactly as stated_rows reads it.
    lines = text.splitlines()
    any_rows = False

    reports = []
    for key in keys:
        rows = section_rows(lines, key)
        any_rows = any_rows or bool(rows)
        try:
            conditions = conditions_of(key)
        except Exception as exc:  # noqa: BLE001 — every read failure refuses
            return did_not_run(
                f"reading the Definition of Done of {key} from Jira failed "
                f"({exc.__class__.__name__})"), "jira-unreachable"
        if not conditions:
            return did_not_run(
                f"{key} carries no Definition of Done condition this gate "
                f"could read from {DOD_FIELD}"), "no-conditions"
        reports.append((key, *grade(conditions, rows)))

    # Zero rows for a dispatched key is a shape the extractor cannot read, and
    # it is said once. Reached after the loop above so a key carrying no
    # Definition of Done at all still refuses on that, which is the fact its
    # session can act on. Where some rows paired and others did not, nothing
    # changes: the session did write a checklist and the missing rows are
    # genuinely missing, so the per-condition report below is correct.
    if not any_rows:
        return no_rows(keys), f"refused-shape:{source}"

    lines = reason_lines(reports, findings_without_outcome(text),
                         drops_without_breakage(text))
    if not lines:
        return 0, f"permitted:{source}"
    return block(
        "Definition of Done gate: this stop is refused. Every condition below "
        "is unstated, not met, states an outcome that is not one of the "
        "three allowed, or drops a finding without naming what breaks.\n" + "\n".join(lines)
        + "\nState a verdict for each, or say plainly that it is not met and "
        "why, then stop again — the second stop carries stop_hook_active and "
        "is not graded."), f"refused:{source}"


if __name__ == "__main__":
    sys.exit(main())
