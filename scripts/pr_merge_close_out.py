#!/usr/bin/env python3
"""Close out every PPA key a squash-merge carried: comment the hash, transition.

PPA-1261. pt-backlog section Close-Out's Graduation Gate requires the commit
hash recorded as a Jira comment before a story reaches Done. Under auto-merge
nothing wrote it: the delegated session arms auto-merge and exits, so the merge
has not happened and the hash does not exist when the session closes out.
PPA-1252 and PPA-1254 both sat at Client Validation with their hashes living
only in a chat thread. This is the mechanism that writes them.

Ruled 07-SEP-2026, decision 2A: the session arms auto-merge and exits; a
separate mechanism records the hash and completes the close-out.

Which status a merged key reaches
---------------------------------
Amended 16-SEP-2026 under PPA-1459, which replaces PPA-1382's rule that Done
was not a value this script could produce, and again 17-SEP-2026 under
PPA-1518, which gives a failed grade an outcome of its own.

* **To Do** -> **In Progress** first, then on exactly as a key found at In
  Progress: Done, Client Validation or held. PPA-1601. The outcome line says
  the key started at To Do, so the missed hop stays visible.
* **Any other status but In Progress** -> comment, no transition, and report
  the skip naming the status found. Client Validation, Reopened and Done are
  left as they are.
* **In Progress** -> **Done**, but only when all three hold together: the
  Definition of Done carries at least one condition, every condition opens with
  the class token ``[machine]``, and the verdict table reports every one MET.
* **In Progress** -> **Client Validation** when some condition is not
  ``[machine]``: a ``[conductor]`` condition, an outstanding ``[observer]``
  condition, or an unclassified one. The Definition of Done is not evidenced by
  a merge, so it goes to the gate that reads it.
* **In Progress** -> **nothing**, when every condition is ``[machine]`` and the
  close-out reports one of them unmet, or states no verdict this parser could
  read. The key stays where it is and a comment names every condition that held
  it. See "The third outcome is the absence of a status" below.

The ruling, recorded 12-SEP-2026 and implemented here: the conductor gate is a
scheduling step, not a judgement step. A ticket whose every condition a machine
can settle does not need a person to agree that the machine was right. PPA-1418
is the case that paid for it - 13 conditions, every one machine-checkable and
met with evidence, and the hop was ceremony. The rule is pt-backlog section
Auto-Done; this is where it is enforced.

A condition carrying no class token is not a ``[machine]`` condition. Classes
are forward-only from 12-SEP-2026, so most open tickets carry none and hold at
Client Validation, which is the safe direction and needs no retrofit.

The asymmetry is deliberate and load-bearing. Every failure path this file owns
- an unreadable Definition of Done, a read failure, a timeout, a verdict table
that will not build - warns and routes to Client Validation. No failure path
may produce Done. Holding a finished ticket costs a conductor hop; closing an
unfinished one costs a false record, which is the failure the next section was
written from.

A merged key at To Do is walked forward
---------------------------------------
PPA-1601. This file used to skip a key at To Do, on the ground that it was the
signal the UserPromptSubmit hook had not fired and had to stay visible. As a
called workflow it serves repositories where no such hook runs, so the skip
fired on ordinary merges and a conductor moved the ticket by hand every time.
Two dated incidents: peech-pmo-automation run 35804893081 (PR #104,
22-SEP-2026) skipped PPA-997 and PPA-1563 with "status is 'To Do', not 'In
Progress'", and PPA-1547 comment 29447 records the same skip on 18-SEP-2026 in
peech-org-skills merge 22b4026.

A merge is itself evidence the work started, so the To Do to In Progress hop is
applied here and the key is then graded as if it had been found at In
Progress. It stays visible on the outcome line rather than in a skip. A hop
that fails is FAILED, and the key is not graded.

The third outcome is the absence of a status
---------------------------------------------
PPA-1518, as amended 17-SEP-2026. A ticket whose own close-out reports a
condition unmet is not finished, so **Client Validation would assert something
false** - that map entry reads "Built and deployed; live validation pending".
Reopened is the status that says what is true, and this workflow cannot reach
it.

Read live from the PPA workflow on 17-SEP-2026, against a real ticket at In
Progress: seven transitions are offered, to Info Provided, Need More Info -
Client, BLOCKED, Closed - Not Needed, Done, Client Validation and To Do. **None
reaches Reopened.** It is offered only from Client Validation, by the
transition labelled "Client Rejected - Restart Work", and ``pt_transition.py``
records the same rule independently as ``CONDUCTOR_ONLY = ("Reopened",)`` with
Reopened deliberately off its ``LIFECYCLE`` ladder. A rejection is a judgement
no workflow observes; it belongs to the conductor.

So the third outcome applies no transition at all. The key stays at In
Progress, a comment names every condition that held it, and the run exits
PARTIAL_EXIT like any other key it found and did not move. What happens next is
the conductor's to decide, and the board read picks the ticket up where it sits.

The earlier draft of PPA-1518 routed this case to Reopened. That was an
authoring error rather than a design choice, and it is recorded here because
the obvious repair - have this script pass ``--conductor`` - is the wrong one
twice over: the hop does not exist from this rung, and the flag is a claim
about who is acting that a workflow cannot honestly make.

Who learns that a ticket was held
---------------------------------
PPA-1534, as amended 22-SEP-2026. The held comment above lands on the ticket,
and nothing reads a ticket nobody opens - so the one outcome that rejects work
was the one outcome with no reader. Every held key now also sends a single
Slack notice to the channel the caller passes as merge-close-out.yml's
``slack_channel`` input, carrying the key, the merge hash, the pull request and
every condition the verdict table reported unmet or unstated.

Nothing is sent for a routing to Done or to Client Validation, because neither
is a rejection, and nothing is sent by the re-grade sweep, which already
declines to post a second copy of anything on a grade that still fails. The
notice is the last thing the held path does - after the routing is decided and
after the held comment is posted - and it raises nothing, because a Slack
outage may not change where a ticket goes.

This ticket was authored against the superseded Reopened routing and amended
onto this one; quoting comment 29460, it "does not add a Reopened hop to any
module and does not change what any outcome routes to. It adds a notice on an
outcome that already exists."

Why Done was wrong
------------------
pt-backlog section Close-Out's status map is explicit: "Built and deployed;
live validation pending" is CLIENT VALIDATION, and "Complete / Graduated" is
DONE. Defaulting to Done inverted it. Done came to mean merged, and the
documented meaning had nothing enforcing it.

Merging is not deployment either. An Apps Script or Sheets change in this
repository is live only after a manual deploy that no merge performs, so a
green merge cannot even evidence the weaker claim.

Four tickets reached Done this way on 11-SEP-2026 carrying a Definition of Done
condition their own close-out reported as not met: PPA-1373, PPA-1374,
PPA-1377 and PPA-1380. PPA-1379 is the sharpest case - merged as c9c1dcd at
roughly 18:10 ET, transitioned to Done with a resolution set, three of its ten
conditions unmet at that moment and two still unmet afterwards.

The Definition of Done is readable and still not judgeable
----------------------------------------------------------
Measured 11-SEP-2026 through this script's own credential path
(pt_transition.load_credentials plus make_client, against the secrets/.env the
workflow materialises): ``GET /issue/{key}?fields=customfield_10767`` returns
the full Definition of Done as an ADF document - 2,005 bytes and nine list
items on PPA-1382, 2,297 bytes and ten on PPA-1379. The field is readable here.

That is the reason the routing is Client Validation rather than something
cleverer. Reading the conditions is not the hard part; deciding whether each
one is met is, and nothing in a merge event carries that. So the workflow
records what it can evidence - the code landed - and hands the judgement to the
gate that owns it. Client Validation to Done stays with the conductor, per
pt-backlog's transition-ownership table.

``needs-live-validation`` is retired. It existed to select the ticket whose
effect a green merge could not evidence; with Client Validation as the only
outcome it selects nothing.

Which keys a merge closes out
-----------------------------
**Three sources, and a commit body is not one of them.** The branch name, the
squash subject, and the commit subjects the squash body carries as bullets.
Their union is the set, and ``key_sources()`` reports which source produced
each key.

*What is barred, and stays barred.* PPA-1375 scanned the whole squash message
until 11-SEP-2026, so every key cited in a commit **body** as provenance was
closed out too. Run 34637111426 proved it live - the merge of PPA-1376's pull
request picked PPA-1375 out of the squash body and commented a merge hash on a
ticket that shipped nothing in it. Only the In Progress precondition stopped a
transition, and a cited key sitting at In Progress would have been moved to
Done. Body paragraphs are still never read for keys.

*What widened, and why the bar survives it.* A commit **subject** is not a
commit body. GitHub writes one ``* <subject>`` bullet per branch commit into
the squash body and lays that commit's body beneath it as plain paragraphs, so
the two are distinguishable on the line - see SUBJECT_BULLET_RE, which requires
both the bullet and the ``type: description`` form pt-git-routing mandates.
A provenance citation is prose in a paragraph: it is neither.

*What each source was bought by.* PPA-1375 narrowed to one key on the
reasoning that a branch is named for exactly one ticket. That stopped being
true: one branch legitimately carries two tickets when they share a file - the
conductor hands over a set and the session makes one pass - and the branch can
only be named for one of them. PPA-1456 read every key in the subject after PR
#59 carried PPA-1427 and PPA-1434 on ``ppa-1427-...``; PPA-1427 moved to Client
Validation with its hash comment and PPA-1434 sat at In Progress with neither,
until a hand read caught it. PPA-1464 added the other two after PR #207 carried
four tickets on ``ppa-1451-1453-1457-1460``, named PPA-1451 in its subject, and
left PPA-1453, PPA-1457 and PPA-1460 at In Progress - with the run concluding
success.

*Why the commit subjects carry production and the branch name does not.*
``--head-ref`` is rarely supplied: merge-close-out.yml runs on ``push`` to
main, where the head branch is not in the event, not in the squash commit
(which has one parent) and not reachable without a GitHub token the job is not
given. So on a real run the branch name is absent and the subject names one
ticket - the pull request title, which pr-open.yml derives from the branch
name, so a second key in it was put there deliberately. The commit subjects are
the only source that reaches the rest, and they are also what carries a
**stacked branch**, where a pull request cut from another ticket's branch puts
two tickets' commits under one squash.

A partial close-out is not a success
------------------------------------
PPA-1464, and the half that outlives the derivation above. The step is named
"Close out every PPA key the merge carried". It carried one of four, and
concluded success: nothing in the output said three keys were never looked
for, and the green result is what stopped anyone looking.

So the run reports every key it found with the source that produced it, before
it attempts anything, and reports every key it found and did not transition
with the reason. A key found and not transitioned exits PARTIAL_EXIT rather
than 0 - see those constants for why a skip is kept distinct from a failure.

This costs a red step on an ordinary skip, such as a key already past In
Progress on a re-run. That is the trade taken deliberately: a mechanism that
can silently do part of its job is a mechanism nobody audits.

Idempotent on the comment
-------------------------
A re-run must not double-comment, so a key already carrying a comment naming
this merge SHA is left alone. The SHA is a 40-character hex string, so its
presence in an existing comment is unambiguous. The transition is idempotent
already - pt_transition.py reports NOOP without writing when a key is at or
past the target.

The verdict table — PPA-1416
----------------------------
A merge posted the hash and nothing else, so a condition the session itself
reported as not met arrived at the conductor's gate with nothing marking it.
Seven tickets were adjudicated by changelog on 12-SEP-2026 without the
Definition of Done being opened once.

The founding case is PPA-1412, whose close-out opens: "Ten of eleven conditions
are met. Condition 4 is not, and it is not met because this session cannot
produce it without crossing a rule." The session did the right thing and said
so first. The merge routed the ticket to Client Validation carrying no trace of
that sentence.

So this posts a second comment: one row per Definition of Done condition,
carrying the verdict the close-out stated for it.

**This adjudicates nothing, and the paragraph above still holds.** Reading the
conditions is not the hard part; deciding whether each one is met is, and
nothing in a merge event carries that. What changed is not the script's ability
to judge - it is that the judgement already exists in writing.
pt-terminal-formatting requires every Delegated close-out to report each
condition explicitly as met or not met, as a checklist ahead of the narrative.
The verdicts are on the ticket. Nothing read them.

Every cell is either quoted from the close-out or UNSTATED. Nothing is computed
from the ticket, the diff or the pull request, and no row is omitted: a
condition the close-out gives no verdict for reads UNSTATED rather than
vanishing or being assumed met. Where any row is not met or unstated, the
comment's first line says so.

Which comments count as the close-out
--------------------------------------
Every comment carrying at least one parseable verdict row, not the most recent
one. Defined by content rather than by position, because the close-out is rarely
the last comment: PPA-1412 carries a one-line correction after it and the
merge-hash comment after that, and this script's own hash comment lands before
the table is built.

Recency was the selector until 13-SEP-2026 and it shadowed the checklist it was
meant to read - PPA-1416's own gate rejection, on two instances this script
produced itself:

* **PPA-1418.** A correction posted at 22:21:05 EDT carried exactly one numbered
  row, condition 9. The table posted at 22:21:57 reported condition 9 NOT MET
  and the other twelve UNSTATED, while the narrative close-out at 22:20:12 had
  reported twelve of thirteen MET. The table's single stated row was the
  correction's single row.
* **PPA-1407.** The table posted at 22:18:46 EDT reported 9 of 9 UNSTATED
  because the close-out did not exist yet - it landed 86 seconds later. An
  absent close-out was reported as nine unstated verdicts rather than as an
  absent close-out.

So the rule has two halves. **The base is the most complete checklist**, the
verdict-bearing comment stating the most rows, with the later winning a tie -
which is how a consolidation supersedes the checklist it restates. **Every
verdict-bearing comment after the base then overrides only the rows it names**,
so a correction changes its own rows and leaves the rest standing. A correction
or consolidation carrying a subset of rows can never replace the checklist it
corrects, because it cannot be more complete than one it is a subset of.

And an absent checklist is reported as absent. A table of UNSTATED rows says the
close-out declined to state them; no table at all says the close-out was not
there to read. Those are different facts and the comment now distinguishes them.

**Two full checklists on one ticket resolve to the later one, row by row.**
PPA-1535. The two halves above already decide this and it was never asserted,
so it is stated here rather than left to be re-derived. A session refused by
the Stop gate answers with a whole checklist rather than a correction naming a
few rows, so capability A made the shape ordinary the day it shipped: PPA-1519
and PPA-1506 each carry two on 18-SEP-2026.

It holds twice over, which is why it does not depend on the tie-break. An
equal-length later checklist wins the tie and becomes the base outright. A
later checklist that is not the base is applied over it and overrides every row
it carries. Either way the later statement stands.

**A row the later checklist does not name keeps the base's verdict.** That
covers the row it simply omits and the row it states but misquotes, since a row
quoting no condition pairs to nothing and names nothing. The consequence worth
knowing: a later checklist that fumbles one quote does not restate that
condition, and the earlier verdict stands there while every row it did quote is
updated. Live instance, PPA-1506: its first checklist stated 11 rows and paired
only 1, so the second checklist - 11 stated, 11 paired - became the base and
carried the ticket on its own.

What the parse reads, and what it cannot
----------------------------------------
A row is a line opening with a condition number - ``4.``, ``4)``, ``- 4.``,
``**4.**`` or ``Condition 4`` - somewhere in which a verdict word appears at a
sentence boundary. The boundary requirement is what keeps the restated
condition text from being read as its own verdict: a condition whose wording
contains "reported as not met" does not match, because "as" is not a boundary.

A close-out written as a Markdown table is read too, since PPA-1489. A row
counts when its first non-empty cell is a condition number on its own and some
later cell is a verdict and nothing else. That whole-cell rule is the
pipe-delimited form of the sentence boundary above and carries the same reason,
so a condition cell reading "the condition is reported not met" yields nothing,
and so does a hedged verdict such as "NOT MET in part" - the rule refuses to
guess which verdict that is, and the row falls to UNSTATED, which is not MET.
The header and separator rows need no special case: ``#`` and ``---`` are not
condition numbers. Jira stores such a table as an ADF ``table`` node rather
than as the pipes the author typed, so ``adf_row`` re-emits them and one rule
covers both that and a table typed as literal text.

It follows that a close-out written in some other shape yields UNSTATED rows
rather than wrong ones. That is the intended failure: this is the 80% version
by design, and an UNSTATED row sends the conductor to the close-out, which is
where they were going anyway.

Pairing a verdict to its condition — PPA-1517
---------------------------------------------
A verdict is filed under the condition the close-out **quoted**, not under the
number it **typed**. Until 17-SEP-2026 the number was the key, and nothing
compared that numbering against what ``customfield_10767`` holds, so one
off-by-one mis-filed every verdict after it - and the error direction favours
closing, because a row lands on a condition whose evidence it is not.

PPA-1479's amendment close-out is the measured case. It numbered its two
conditions 14 and 15 where the field carries them at 13 and 14. The table filed
both one row late: the repo-wide-rules evidence landed on condition 14, the
no-literal evidence on condition 15, condition 13 read UNSTATED with its own
evidence two comments above it, and the standing findings condition was marked
met on evidence written for something else. Recorded in
PeechTech-Framework-CommitToDoneAutomation v0-0003, capability B.

**The parse is two halves and they stay separate.** ``stated_rows`` extracts
rows from lines; ``pair_rows`` pairs rows against conditions. The separation is
load-bearing rather than tidy: this file reads its verdicts out of ADF on a
Jira comment, and the Stop grader reads the same verdicts out of a turn's own
output, which is plain text and never passes through ADF. Two source shapes,
two adapters, **one pairing function** - folding the pairing into the
extraction would force the grader to synthesise ADF it never had.

**The match is a heuristic over English and is not dressed as anything else.**
A close-out abbreviates: PPA-1481's row 1 reads "PNIIG-74 and PNIIG-177 each
carry six Phase children; a live JQL read quoted" against a longer condition.
An exact-quote rule would report every real close-out as a defect and file
nothing, so the measure is what share of the row's distinctive words the
condition accounts for - see ``MATCH_FLOOR`` for why half, and why the measure
is one-directional. What it replaces was exact and wrong.

Where one checklist ends and the next begins — PPA-1555
--------------------------------------------------------
**A new checklist begins at a row numbered 1 that follows a row numbered
higher than 1; everything between two such rows is one checklist, and a row
number de-duplicates inside it rather than across the whole text.**

Why it needed deciding. First-statement-per-number held across the entire text,
which is right for one ticket - a close-out restating a condition later in its
narrative must not displace the row it wrote in its own checklist - and wrong
for a dispatch carrying several. Each ticket's checklist numbers from 1, so the
second ticket's rows were eaten before ``pair_rows`` ever ran and its conditions
read UNSTATED with their evidence sitting in the same comment. Observed
18-SEP-2026: the session working PPA-1541, PPA-1546, PPA-1549 and PPA-1551
numbered its checklist 1 to 38 globally and said plainly that it did so because
of this. A session should not have to work around the parser to be read.

The comment boundary was the other candidate and it is already in use -
``checklist_comments`` calls ``stated_rows`` once per comment, so two checklists
in two comments never collided in the first place. It cannot reach the case that
matters, which is several checklists inside one text: one comment carrying a
batch, and the Stop grader, which reads a whole turn's output as one string.

What this rule costs, stated rather than discovered later: a close-out that
restates **condition 1** further down its narrative, after some higher-numbered
row, reads as a second checklist and the restatement is kept instead of dropped.
Both rows then quote the same condition, one of them claims it and the other is
reported as a row matching no condition - visible on the comment, not silent.
Restating any other number is unaffected, because only a 1 opens a checklist.

**A row that will not pair is reported, not filed.** Three defects ride out on
the comment: a row quoting text that matches no condition, which files no
verdict so its condition reads UNSTATED; a row count that differs from the
field's; and a row numbered differently from the condition it paired to, which
still files, because the pairing decides and the number was only ever a label.

**The required close-out shape is stated in delegation.md**, which CLAUDE.md
imports, so a session reads it before writing its close-out. Widening the parser alone leaves the next shape to be found by a
failure instead of by a rule.

One ticket's rows in a multi-ticket close-out — PPA-1656
--------------------------------------------------------
**A line that is not a checklist row and names exactly one PPA key opens that
key's section, and the section runs to the next such line. A ticket is graded
against the rows in its own sections and the rows before the first one.**

Why it needed deciding. The PPA-1555 boundary above splits one text into
checklists but says nothing about whose each one is, so every row in a comment
was paired against every ticket that comment sat on. PR #129 in
peech-pmo-automation carried PPA-1612 and PPA-1613 under one close-out, seven
conditions each; the merge read it as no close-out checklist and left both
tickets at In Progress. ``section_rows`` supplies the owner: the heading above
a row, which PPA-1619's amendment makes the required shape for a close-out
covering more than one ticket.

Rows before the first key heading belong to every key. A comment with no key
heading is therefore one section belonging to every key and reads exactly as it
did before, and a single-ticket close-out that names another key only after its
checklist - "this unblocks PPA-1619" - keeps its rows.

What this rule costs, stated rather than discovered later: a prose line naming
one other key *before* the checklist - "blocked by PPA-1619, now merged" - opens
that key's section, so the rows under it are filed against PPA-1619 and the
ticket being graded reads as having no checklist. It is held at In Progress
with the held notice, which a person reads; it is not closed on another
ticket's rows. A line naming two keys or more opens nothing.

A held ticket gets a second reader — PPA-1556
----------------------------------------------
The merge run reads a ticket's comments once, on the merge event, and nothing
re-read them. A close-out landing after that was invisible to it: the ticket sat
at In Progress carrying a checklist reporting every condition met, and only a
person noticed. Two instances, both 18-SEP-2026. PPA-1505 merged as 0a2daca at
11:51 and its verdict table was posted at 12:09, eighteen minutes later.
PPA-1541 merged as 4d41d5b at 17:48 and its close-out at 17:55, seven minutes
later. Both were recorded as absent and both were closed by hand.

``--regrade`` is that second reader. It finds every ticket still at In Progress
carrying this file's own ``HELD_MARK`` comment, re-reads the comments as they
stand, and applies the transition the merge run would have applied. The grade
is not re-implemented: ``plan_transition`` decides, against the same conditions
and the same rule, later.

**What fires it: a cron on ``merge-close-out.yml``, hourly.** That workflow's
own header used to say it was not scheduled and not manually dispatchable,
because "the trigger is the fact the close-out records - a merge - so a run
detached from one has nothing to report on". The premise was wrong in exactly
one case, which is this one: a ticket this workflow held *is* something to
report on, and the event that resolves it - a comment arriving - raises no
webhook anything here receives. A schedule is the only trigger available, and
it is a real one rather than prose.

**What learns of a re-grade.** The ticket does: a transition posts a comment
naming the re-grade and the status it reached, signed ``REGRADE_MARK``, so a
status that changed hours after the merge has a reason on the ticket rather
than appearing to have moved by itself. The workflow run is the other record.
Nothing else is notified, and no Slack or mail path is added here.

**What it deliberately will not do.** A ticket no longer at In Progress is left
alone - something moved it and this has no view of what. A ticket carrying no
held comment is left alone - it was never graded here. A grade that still fails
leaves the ticket where it is and posts nothing, because the held comment
naming those conditions is already on the ticket and one copy per sweep is
noise.

It never blocks, fails or delays a merge
-----------------------------------------
Every failure in this half is caught and reported as a note on the outcome
line. The table is an addition to the close-out, and a merge whose ticket
cannot be summarised still gets its hash. Nothing here reaches ``exit_code``.

Credentials come from pt_transition.py
--------------------------------------
This script imports load_credentials() and make_client() rather than repeating
the Basic-auth urllib path, which also keeps one credential home. That home is
an absolute path (see pt_transition.CREDENTIALS), so the workflow materialises
it from the repository secrets before calling either. pt_transition.py itself is
called and imported, never changed.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# noqa: E402 below - the sys.path insert above has to run first.
from pt_transition import load_credentials, make_client, norm  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "pt_transition.py"

#: The only status this script transitions out of. Every other status is
#: commented and skipped - see "Which status a merged key reaches" above.
MERGED_FROM = "In Progress"

#: The one other status a merged key is moved out of, and only onto
#: MERGED_FROM - see "A merged key at To Do is walked forward" above.
STARTED_FROM = "To Do"

#: Where a merged key goes unless Auto-Done's four conditions all hold. Every
#: failure path this file owns routes here, and none may produce Done.
MERGED_TO = "Client Validation"

#: Auto-Done's destination, PPA-1459. Reached only from MERGED_FROM, and only
#: when every condition is [machine] and every one is reported MET - see
#: "Which status a merged key reaches" above and pt-backlog section Auto-Done.
MERGED_TO_DONE = "Done"

#: A Definition of Done condition's declared class, at the head of its text:
#: one lower-case token in square brackets before any other word, per
#: pt-backlog section Definition of Done Condition Classes. Anchored, because a
#: "[machine]" appearing later in a condition's prose declares nothing.
CLASS_RE = re.compile(r"^\s*\[(machine|conductor|observer)\]", re.IGNORECASE)

#: A PPA key in a commit message, and not one of the three things that look like
#: one. The lookbehind rejects a path or URL segment (``/PPA-1264``) and a word
#: prefix (``XPPA-1264``); the first lookahead rejects a longer token
#: (``PPA-1155-findings``); the second rejects a file extension
#: (``PPA-1155.md``) while still allowing a key that ends a sentence
#: (``see PPA-1264.``). Case-insensitive, and uppercased on the way out.
#:
#: A commit message is the only string this is calibrated for. A branch slug
#: (``ppa-1264-short-slug``) has the same shape as the filename the trailing
#: lookahead exists to reject, so it does not match here and a caller wanting
#: keys out of a branch name needs its own prefix match. PPA-1260's review
#: workflow does exactly that rather than widening this rule, because widening
#: it would let every mention of ``docs/spikes/PPA-1155-findings.md`` in a
#: commit body transition PPA-1155.
KEY_RE = re.compile(r"(?<![\w/.-])(PPA-\d+)(?![\w-])(?!\.\w)", re.IGNORECASE)

#: GitHub's squash-merge subject ends with the pull request number.
PR_RE = re.compile(r"\(#(\d+)\)")

#: The PPA keys at the head of a branch name (``ppa-1264-short-slug``). KEY_RE
#: is calibrated for commit messages and deliberately rejects this shape - the
#: trailing ``-short-slug`` looks exactly like the longer token it exists to
#: reject - so a branch name needs its own anchored prefix match, as its own
#: note says.
#:
#: Every key in the leading run, since PPA-1464: a branch carrying four tickets
#: is named for all four (``ppa-1451-1453-1457-1460``) and matching one number
#: found one of them. Only the leading run of numeric segments is read, so the
#: match stops at the first word - ``ppa-1264-short-slug`` is still one key, and
#: a slug's own digits are never reachable because a word always precedes them.
BRANCH_KEYS_RE = re.compile(r"^ppa-(\d+(?:-\d+)*)", re.IGNORECASE)

#: A commit subject as GitHub writes it into a squash body: one ``* `` bullet
#: per commit on the branch, in the ``type: description (PPA-###)`` form
#: pt-git-routing requires of every commit in the estate.
#:
#: This is the line that makes a commit subject readable without reading the
#: body around it, which is what PPA-1375 barred and what stays barred. A body
#: paragraph citing a ticket as provenance is not a bullet and does not open
#: with a commit type, so it matches nothing here. The type list is the
#: discriminator rather than the bullet alone: a body may legitimately carry a
#: markdown list, and a bullet test on its own would read one as a subject.
SUBJECT_BULLET_RE = re.compile(
    r"^\* (?:feat|fix|refactor|docs|chore|test|adjacent):\s", re.IGNORECASE)

#: A parenthesised group carrying at least one PPA key. A commit subject names
#: its own ticket in a trailing ``(PPA-###)``, and pt-git-routing requires that
#: form of every commit in the estate, so the last such group is the commit's
#: own work and the rest of the line is description.
#:
#: The description is not read, and PR #207 is why: its fifth commit subject is
#: ``fix: correct the third site of the stale PPA-1347 citation (PPA-1451)``.
#: PPA-1347 closed Done a week earlier and shipped nothing in that merge - it
#: is the thing being corrected, cited exactly as PPA-1375's provenance
#: citations are. Reading every key on the line would reintroduce that defect
#: one level down, on a real message already in the estate's history.
#:
#: The group is a group rather than a single key because a commit legitimately
#: carries two: ``fix: Bar check at dispatch; malformed line warns
#: (PPA-1427, PPA-1434)`` is main's own e4b7dce.
OWN_KEYS_RE = re.compile(r"\(([^()]*PPA-\d+[^()]*)\)", re.IGNORECASE)


# ------------------------------------------------------------------- parsing

def keys_in(text):
    """Every PPA key in a line of commit text, uppercased, first-appearance order.

    Zero is a normal answer: not every commit on main comes from a ticketed
    pull request. Since PPA-1375 this is only ever handed a subject line - see
    key_from_subject() and the module docstring for why the body is not read.
    """
    return list(dict.fromkeys(
        m.group(1).upper() for m in KEY_RE.finditer(text)))


def keys_from_branch(head_ref):
    """Every PPA key a ``ppa-*`` branch name carries, in order.

    ``ppa-1451-1453-1457-1460`` is four tickets and was read as one until
    PPA-1464. See BRANCH_KEYS_RE for why only the leading run is read.
    """
    match = BRANCH_KEYS_RE.match((head_ref or "").strip())
    return [f"PPA-{n}" for n in match.group(1).split("-")] if match else []


def key_from_branch(head_ref):
    """The first PPA key a ``ppa-*`` branch name carries, or None."""
    keys = keys_from_branch(head_ref)
    return keys[0] if keys else None


def keys_from_subject(message):
    """Every PPA key in the squash-merge subject line, first-appearance order.

    Only the first line is read. The body below it carries the branch's commit
    subjects, and a commit body citing a ticket as provenance is
    indistinguishable from one naming its own work - PPA-1375, unchanged.

    Every key, not the first one, since PPA-1456. A subject naming two tickets
    is naming both as its own work: pr-open.yml derives the title from the
    branch, and a conductor who edits it to carry a second key has said the
    merge carries that ticket too.
    """
    lines = (message or "").splitlines()
    return keys_in(lines[0]) if lines else []


def key_from_subject(message):
    """The first PPA key in the squash-merge subject line, or None."""
    keys = keys_from_subject(message)
    return keys[0] if keys else None


def keys_from_commit_subjects(message):
    """Every PPA key on a commit-subject bullet in the squash body, in order.

    GitHub writes one ``* <subject>`` bullet per commit on the branch, with that
    commit's body as plain paragraphs beneath it. The bullets are the branch's
    own commit subjects; the paragraphs are where PPA-1375's provenance
    citations live. Reading the first and not the second is the distinction
    this rests on - see SUBJECT_BULLET_RE for how the two are told apart, and
    the module docstring for why the paragraphs stay unread.

    This is the source that carries a stacked branch, where one squash holds
    two tickets' commits, and the source that carries PR #207 in production:
    the workflow supplies no head ref, so the branch name is not available and
    the subject named one of its four tickets.
    """
    keys = []
    for line in (message or "").splitlines()[1:]:
        if not SUBJECT_BULLET_RE.match(line):
            continue
        for key in own_keys_in(line):
            if key not in keys:
                keys.append(key)
    return keys


def own_keys_in(subject):
    """The keys a commit subject names as its own work, or an empty list.

    The last parenthesised group carrying a key, never the description around
    it - see OWN_KEYS_RE for the real subject that bought the distinction.
    """
    groups = OWN_KEYS_RE.findall(subject)
    return keys_in(groups[-1]) if groups else []


#: Where a key was found, in the order the sources are read. Reported per key
#: so a close-out can be audited without re-deriving it - PPA-1464 condition 1.
BRANCH_SOURCE = "branch name"
SUBJECT_SOURCE = "squash subject"
COMMIT_SOURCE = "commit subject"


def key_sources(head_ref, message):
    """{key: [source, ...]} for every key this merge carried, in found order.

    Three signals, and each one was bought by a merge that lost a ticket:

    * **The branch name** - every key in it since PPA-1464, one key before.
    * **The squash subject** - every key in it since PPA-1456, the first key
      before. PR #59 carried PPA-1427 and PPA-1434 on ``ppa-1427-...`` and only
      PPA-1427 moved.
    * **The branch's commit subjects** - PPA-1464. PR #207 carried four tickets
      and its subject named one, so three were stranded at In Progress by a run
      that reported success.

    A head ref that was supplied still cannot be overruled into silence: if no
    source carries a key, nothing is closed out. But a head ref has not been a
    reason to stop reading the message since PPA-1456.

    The sources ride out with the keys because a partial close-out has to be
    readable: a key found only in a commit subject is a different claim from
    one the branch is named for, and an operator reading the run needs to see
    which was which.
    """
    found = {}
    for source, keys in ((BRANCH_SOURCE, keys_from_branch(head_ref)),
                         (SUBJECT_SOURCE, keys_from_subject(message)),
                         (COMMIT_SOURCE, keys_from_commit_subjects(message))):
        for key in keys:
            found.setdefault(key, [])
            if source not in found[key]:
                found[key].append(source)
    return found


def close_out_keys(head_ref, message):
    """Every key this merge closes out, in order, or an empty list."""
    return list(key_sources(head_ref, message))


def pr_number_in(message):
    """The pull request number from a squash-merge subject, or None."""
    match = PR_RE.search(message)
    return match.group(1) if match else None


def adf_text(node):
    """Every text node under an ADF value, joined. Shape-agnostic on purpose."""
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text", ""))
        return " ".join(adf_text(v) for v in node.values())
    if isinstance(node, list):
        return " ".join(adf_text(v) for v in node)
    return ""


#: ADF nodes that end a line. adf_text() above joins everything with spaces,
#: which is right for a substring search and useless for a line-oriented parse -
#: a checklist flattened to one line has no rows left in it.
_LINE_NODES = ("paragraph", "heading", "codeBlock")


def adf_inline(node):
    """The text of one block node, with hard breaks kept as newlines."""
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text", ""))
        if node.get("type") == "hardBreak":
            return "\n"
        return "".join(adf_inline(c) for c in node.get("content") or [])
    if isinstance(node, list):
        return "".join(adf_inline(c) for c in node)
    return ""


def adf_row(node):
    """One ``tableRow`` as a pipe-delimited line: ``| 1 | text | MET |``.

    Jira stores a Markdown table as an ADF ``table`` node, so the pipes the
    author typed do not survive into the stored body. Without this a row's
    cells reach ``adf_lines`` as separate paragraphs - "1", the condition text,
    "MET" - and the number cell carries no delimiter, so ``_ROW_RE`` cannot
    match it and the whole checklist reads as absent (PPA-1489).

    Re-emitting the pipes is what lets one rule in ``verdicts_in`` cover both
    this and a table typed as literal text, rather than two parsers that can
    disagree. A cell's own newlines are folded to spaces so one row stays one
    line, and a cell containing a pipe is not escaped - a verdict cell is a
    bare word, so the only cell that could carry one is prose, where an extra
    split yields another non-verdict cell and changes no answer.
    """
    cells = [" ".join(adf_inline(cell).split())
             for cell in node.get("content") or []]
    return "| " + " | ".join(cells) + " |"


def adf_lines(node, out=None):
    """One line per block-level node, in document order.

    A list item's text arrives through the paragraph inside it, so bullets and
    numbered paragraphs both land as their own line without this needing to
    know which shape a close-out used.

    Two shapes are exceptions, and both are exceptions for the same reason -
    recursing plainly would strip the structure that says which condition a
    verdict belongs to.

    A table row is emitted whole, by ``adf_row``, instead of one line per cell.

    An ordered list has its ordinal restored. This is the one that bit:
    Markdown's "1." does not survive the round trip, because ADF carries the
    number as list structure rather than as text, so every condition in a
    numbered close-out arrived here with nothing at the head of the line for
    ``_ROW_RE`` to match. Eight tickets merged on 18-SEP-2026 against a
    close-out written that way and seven were reported to have none at all -
    PPA-1531. The ordinal is read from ``attrs.order`` rather than counted from
    one, because Jira splits a list at every code block and restarts the next
    ``orderedList`` at the number it left off, so counting from one restarts
    with it. Only the first line an item produces is numbered; a code block
    inside the item keeps its own line unprefixed.
    """
    if out is None:
        out = []
    if isinstance(node, dict):
        if node.get("type") in _LINE_NODES:
            out.extend(adf_inline(node).splitlines() or [""])
            return out
        if node.get("type") == "tableRow":
            out.append(adf_row(node))
            return out
        if node.get("type") == "orderedList":
            number = (node.get("attrs") or {}).get("order")
            number = number if isinstance(number, int) else 1
            for item in node.get("content") or []:
                mark = len(out)
                adf_lines(item, out)
                if len(out) > mark:
                    out[mark] = f"{number}. {out[mark]}"
                number += 1
            return out
        for child in node.get("content") or []:
            adf_lines(child, out)
    elif isinstance(node, list):
        for child in node:
            adf_lines(child, out)
    return out


# ------------------------------------------------------- the verdict table

#: A condition number at the head of a line: "4.", "4)", "- 4.", "**4.**",
#: "Condition 4", "4 -". Anything after it is the restated condition and the
#: verdict.
_ROW_RE = re.compile(
    r"^\s*(?:[-*•]\s*)?(?:condition\s+)?(\d{1,2})\s*[.):—–-]\s+",
    re.IGNORECASE)

#: Bold markers, stripped before a row is matched. A checklist written
#: "**4.** ..." puts the closing marker after the delimiter, so folding the
#: markers into the row pattern costs more than removing them first.
_BOLD_RE = re.compile(r"\*\*")

#: A verdict word standing at a sentence boundary. The boundary is the whole
#: guard against reading a restated condition as its own verdict - see "What
#: the parse reads" in the module docstring.
#:
#: It is also what keeps the MET inside NOT MET from matching: the characters
#: before that MET are "NOT ", and a letter is not a boundary. The longest
#: alternative is listed first as well, but measured 12-SEP-2026 by reordering
#: the alternation, that ordering changes no verdict while the boundary holds.
#: Both are kept; only one is currently load-bearing.
_VERDICT_RE = re.compile(
    r"(?:^|(?<=[.:;!?])\s|(?<=[—–])\s|(?<=\s[-])\s)"
    r"(NOT\s+MET|NOT\s+YET\s+MET|MET)\b",
    re.IGNORECASE)

#: A condition number occupying a whole cell - "digits and nothing else".
_NUMBER_CELL_RE = re.compile(r"^(\d{1,2})$")

#: Emphasis markers stripped from a cell before it is tested as a verdict, so
#: "**MET**" and "`MET`" read the same as "MET".
_EMPHASIS_RE = re.compile(r"[*_`]")

#: A verdict occupying a whole cell. Anchored at both ends, which is the
#: pipe-delimited equivalent of the sentence boundary ``_VERDICT_RE`` applies
#: and carries the same reason: it is what stops a restated condition being
#: read as its own verdict. A cell reading "the condition is reported not met"
#: is prose, not a verdict, and yields nothing.
#:
#: The anchoring is also what keeps NOT MET from reading as MET, and it is a
#: stronger guard than the lookbehind it mirrors: "NOT MET" cannot match
#: ``^MET$`` at all, so the result does not depend on the alternation order.
_CELL_VERDICT_RE = re.compile(
    r"^(NOT\s+MET|NOT\s+YET\s+MET|MET)$", re.IGNORECASE)

UNSTATED = "UNSTATED"


class StatedRow:
    """One row of a close-out checklist, as the close-out wrote it.

    Three things, and the middle one is what PPA-1517 added. ``number`` is the
    number the close-out typed, which is no longer what the row is filed under.
    ``quoted`` is the condition text the close-out quoted, which is. ``verdict``
    is MET, NOT MET or NOT YET MET, quoted the same way.

    A row is data read off a comment, so nothing here is derived or corrected -
    a misnumbered row keeps its wrong number, and ``pair_rows`` reports the
    mismatch rather than the row hiding it.
    """

    __slots__ = ("number", "quoted", "verdict")

    def __init__(self, number, quoted, verdict):
        self.number = number
        self.quoted = quoted
        self.verdict = verdict

    def __eq__(self, other):
        return (isinstance(other, StatedRow)
                and (self.number, self.quoted, self.verdict)
                == (other.number, other.quoted, other.verdict))

    def __repr__(self):
        return (f"StatedRow({self.number!r}, {self.quoted!r}, "
                f"{self.verdict!r})")


def table_cells(line):
    """The cells of a pipe-delimited row, or None where the line is not one.

    Reaches both shapes a close-out can carry a table in: an ADF ``table``,
    which ``adf_row`` re-emits with its pipes, and a table typed as literal
    text in a paragraph or code block, where the pipes were never lost.
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    body = stripped[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def row_verdict(cells):
    """One ``StatedRow`` for a table row, or None where it states no verdict.

    The three conditions a row has to meet, per PPA-1489: its first non-empty
    cell is a condition number on its own; some later cell is a verdict and
    nothing else; and it is neither a separator row nor the header, both of
    which fall out of the first condition without being named - "---" and "#"
    are not numbers.

    The quoted condition text is every cell between those two, since PPA-1517.
    It is what the row is paired on, so the cells are joined rather than the
    first one taken: a close-out that splits its condition over two columns has
    still quoted it.
    """
    rest = list(cells)
    while rest and not rest[0]:
        rest.pop(0)
    if not rest:
        return None
    number = _NUMBER_CELL_RE.match(rest[0])
    if not number:
        return None
    for index, cell in enumerate(rest[1:], 1):
        verdict = _CELL_VERDICT_RE.match(_EMPHASIS_RE.sub("", cell).strip())
        if verdict:
            return StatedRow(
                int(number.group(1)),
                " ".join(" ".join(rest[1:index]).split()),
                " ".join(verdict.group(1).split()).upper())
    return None


def conditions_in(dod):
    """Every Definition of Done condition, in order, as text.

    Takes the ADF the field returns. A field that is absent, empty or some
    other shape yields no conditions, and the caller reports that rather than
    inventing rows.
    """
    if not isinstance(dod, dict):
        return []
    return [" ".join(adf_inline(item).split())
            for item in _list_items(dod)]


def _list_items(node, out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        if node.get("type") == "listItem":
            out.append(node)
            return out
        for child in node.get("content") or []:
            _list_items(child, out)
    elif isinstance(node, list):
        for child in node:
            _list_items(child, out)
    return out


def stated_rows(lines):
    """Every checklist row these lines state, in the order they were written.

    This is the extractor half of the parse, and it is deliberately separate
    from the pairing half below - see "Pairing a verdict to its condition" in
    the module docstring. It takes lines, so a caller with a Jira comment
    passes ``adf_lines(body)`` and a caller with plain text passes
    ``text.splitlines()``. Those are the two source shapes, and they need two
    adapters rather than two parsers.

    First statement per number wins **within a checklist** - see "Where one
    checklist ends and the next begins" in the module docstring. A close-out
    that restates a condition later in its narrative must not displace the row
    it wrote in its own checklist, and a dispatch carrying four tickets must
    not lose three of them to the first one's numbering. The number is still
    what de-duplicates, because it is the only thing available before the field
    is read; what changed under PPA-1555 is the span it de-duplicates over.
    """
    found = []
    seen = set()
    previous = None
    for raw in lines:
        row = _row_in(raw)
        if not row:
            continue
        if row.number == 1 and previous is not None and previous > 1:
            seen = set()
        # The previous row is the previous row read, not the previous row kept:
        # a restatement that was dropped still moved the numbering past it, and
        # a boundary measured against the last kept row would miss a checklist
        # opening straight after one.
        previous = row.number
        if row.number not in seen:
            seen.add(row.number)
            found.append(row)
    return found


def _row_in(raw):
    """The ``StatedRow`` one line states, or None where it is not a row."""
    cells = table_cells(raw)
    if cells is not None:
        return row_verdict(cells)
    line = _BOLD_RE.sub("", raw)
    head = _ROW_RE.match(line)
    if not head:
        return None
    rest = line[head.end():]
    verdict = _VERDICT_RE.search(rest)
    return verdict and StatedRow(
        int(head.group(1)),
        " ".join(rest[:verdict.start()].split()).strip(" .:;—–-"),
        " ".join(verdict.group(1).split()).upper())


def section_rows(lines, key):
    """The rows in one PPA key's section of a close-out, in written order.

    See "One ticket's rows in a multi-ticket close-out" in the module
    docstring. A line that is not a checklist row and names exactly one PPA key
    opens that key's section, which runs to the next such line. Rows before the
    first such line belong to every key, so a comment with none reads exactly
    as ``stated_rows`` reads it.

    Takes lines for the same reason ``stated_rows`` does: the merge passes
    ``adf_lines(body)`` and the Stop grader passes ``text.splitlines()``.
    """
    key = key.upper()
    kept = []
    owner = None
    for raw in lines:
        if _row_in(raw) is None:
            named = keys_in(raw)
            if len(named) == 1:
                owner = named[0]
                continue
        if owner is None or owner == key:
            kept.append(raw)
    return stated_rows(kept)


#: A word that discriminates between two conditions not at all, dropped before
#: two texts are compared. Articles, conjunctions, prepositions and auxiliaries
#: - the words every condition in the estate carries.
_STOPWORDS = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "both", "by",
    "each", "every", "for", "from", "has", "have", "in", "is", "it", "its",
    "of", "on", "one", "or", "so", "that", "the", "their", "them", "then",
    "there", "these", "this", "those", "to", "two", "was", "were", "what",
    "when", "where", "which", "while", "who", "with",
))

#: What a word is, for the comparison. Digits, dots and hyphens stay inside a
#: token so ``PPA-1517``, ``customfield_10767`` and ``0-0003`` each compare as
#: one word rather than as several fragments that match anything.
_WORD_RE = re.compile(r"[A-Za-z0-9][\w./-]*")

#: How much of a row's quoted text a condition must account for before the two
#: are the same condition. A close-out abbreviates - PPA-1481's condition 1
#: reads "PNIIG-74 and PNIIG-177 each carry six Phase children; a live JQL read
#: quoted" against a longer field condition - so an exact-quote rule would
#: report every real close-out as a defect and file nothing.
#:
#: Half is where it sits because the measure is one-directional: it asks what
#: share of the *row's* words the condition carries, so dropping words from a
#: quote costs nothing and inventing them costs everything. A row sharing half
#: its distinctive vocabulary with a condition and more with no other is that
#: condition; the greedy assignment below is what enforces the "no other".
MATCH_FLOOR = 0.5


def _words(text):
    """The distinctive words of a condition or a quote of one.

    The class token goes first: ``[machine]`` opens most conditions and none of
    the rows quoting them, so leaving it in would penalise every real quote.
    """
    stripped = CLASS_RE.sub("", text or "").lower()
    return {w for w in _WORD_RE.findall(stripped) if w not in _STOPWORDS}


def match_score(quoted, condition):
    """What share of the quoted text's words this condition accounts for.

    0.0 to 1.0, and one-directional on purpose - see MATCH_FLOOR. A quote with
    no distinctive words at all scores 0.0 against everything, which is the
    right answer: a row quoting nothing cannot be paired by what it quoted.

    This is a heuristic over English and is not presented as anything more. It
    replaces a rule that was exact and wrong: a row's written number, which
    PPA-1479's close-out got wrong by one and which filed every verdict after
    it against the wrong condition.
    """
    words = _words(quoted)
    if not words:
        return 0.0
    return len(words & _words(condition)) / len(words)


class Pairing:
    """Which condition each stated row belongs to, and what would not pair."""

    def __init__(self, verdicts, defects):
        #: {the field's own 1-based condition number: the quoted verdict}. A
        #: condition no row paired to is absent rather than assumed met.
        self.verdicts = verdicts
        #: Every defect found, each a sentence naming what could not be paired
        #: or what did not add up. Reported; never filed as a verdict.
        self.defects = defects


def pair_rows(conditions, rows):
    """Pair every stated row to the condition it quotes. Returns a ``Pairing``.

    The pairing half of the parse, shared by every caller that has a checklist
    and a Definition of Done - the merge here, and the Stop grader, which reads
    its rows out of plain text and hands them to this same function.

    Highest score first, one condition to one row. Greedy rather than optimal
    because the two are indistinguishable on real input and greedy is readable:
    the strongest pairing claims its condition, and a row whose best candidate
    was taken falls to its next. What the ordering buys is the off-by-one case
    - two adjacent conditions both plausible for one row - where the row that
    quotes a condition best gets it and the other row is pushed off rather than
    both filing one row late.

    Three defects are reported, and only the first withholds a verdict:

    * A row whose quoted text matches no condition. It files nothing, so that
      condition reads UNSTATED, which is not MET.
    * A row count that differs from the field's condition count.
    * A row numbered differently from the condition it paired to. The verdict
      still files - the pairing is what decides, and the number was only ever
      a label - but a close-out numbering its rows wrongly is worth saying.
    """
    scored = sorted(
        ((score, r, c)
         for r, row in enumerate(rows)
         for c, condition in enumerate(conditions)
         if (score := match_score(row.quoted, condition)) >= MATCH_FLOOR),
        key=lambda s: (-s[0], s[1], s[2]))

    paired = {}
    claimed = set()
    for _score, r, c in scored:
        if r not in paired and c not in claimed:
            paired[r] = c
            claimed.add(c)

    verdicts = {paired[r] + 1: row.verdict
                for r, row in enumerate(rows) if r in paired}

    defects = []
    for r, row in enumerate(rows):
        if r not in paired:
            defects.append(
                f"the row numbered {row.number} quotes text matching no "
                f"condition, so it files no verdict: "
                f"{_clip(row.quoted, 70) or '(nothing quoted)'}")
    if rows and len(rows) != len(conditions):
        defects.append(
            f"the close-out states {len(rows)} row(s); the Definition of Done "
            f"carries {len(conditions)} condition(s)")
    misnumbered = [(row.number, paired[r] + 1)
                   for r, row in enumerate(rows)
                   if r in paired and row.number != paired[r] + 1]
    if misnumbered:
        defects.append(
            "the close-out numbers rows differently from the field: "
            + ", ".join(f"row {written} is condition {actual}"
                        for written, actual in misnumbered))
    return Pairing(verdicts, defects)


def checklist_comments(comments, key=None):
    """[(comment, rows)] for every comment stating at least one row, oldest
    first. A comment stating none is not part of the close-out at all.

    With a key, only the rows in that key's section count - see
    ``section_rows``. Without one, every row in the comment does.
    """
    found = []
    for comment in comments or []:
        lines = adf_lines(comment.get("body"))
        rows = stated_rows(lines) if key is None else section_rows(lines, key)
        if rows:
            found.append((comment, rows))
    return found


def merged_verdicts(comments, conditions, key=None):
    """(verdicts, the comments used, the defects found) across every checklist.

    ``key`` is the ticket being graded. Each comment is read for the rows in
    that key's section only, since PPA-1656, so a multi-ticket close-out files
    no row against a ticket it does not name. With no key, every row counts.

    Recency is not the selector - see "Which comments count as the close-out"
    in the module docstring. The base is the most complete checklist, later
    winning a tie, and every verdict-bearing comment after it overrides only
    the rows it names.

    Each comment is paired against the field separately and the *paired* maps
    are merged, since PPA-1517. Merging the rows first and pairing once would
    make two checklists that number their rows differently collide on a number
    neither of them meant, which is the failure the pairing change exists to
    close. Pairing first means a correction overrides the condition it quotes,
    whatever number it typed.

    What this does when one ticket carries two full checklists, and what
    happens to a row the later one does not name, is stated in the module
    docstring under "Which comments count as the close-out" (PPA-1535). It is
    not restated here: a rule written in two places is a rule that can
    disagree with itself, and this one already did.

    Returns ({}, [], []) when no comment states a row at all, which the caller
    reports as an absent checklist rather than as a table of UNSTATED rows.
    """
    found = [(comment, pair_rows(conditions, rows))
             for comment, rows in checklist_comments(comments, key)]
    if not found:
        return {}, [], []

    # max() keeps the first maximum, so the index makes a later checklist of
    # equal length the base. Measured 13-SEP-2026 by inverting it: that choice
    # changes which comment is reported as the base and never changes a
    # verdict, because a later equal-length checklist that is not the base is
    # applied as an override over every row it carries and reaches the same
    # answer. It is kept so `used` names the most recent complete statement.
    base = max(range(len(found)), key=lambda i: (len(found[i][1].verdicts), i))

    verdicts = dict(found[base][1].verdicts)
    used = [found[base][0]]
    defects = list(found[base][1].defects)
    for comment, pairing in found[base + 1:]:
        verdicts.update(pairing.verdicts)
        used.append(comment)
        defects.extend(pairing.defects)
    return verdicts, used, defects


class VerdictTable:
    """One row per condition, each carrying what the close-out said about it."""

    def __init__(self, rows, note="", conditions=(), absent=False, defects=()):
        #: (number, condition text, verdict) - verdict is quoted or UNSTATED.
        #: The number is the field's own position, not what the close-out
        #: typed: since PPA-1517 a verdict is filed under the condition it
        #: quotes.
        self.rows = rows
        #: Why the table is empty or partial, when it is. Never a failure.
        self.note = note
        #: Every condition the Definition of Done carries, in the field's own
        #: order. Held rather than counted since PPA-1518: where there is no
        #: checklist, every condition is what held the ticket, and the comment
        #: has to name them rather than say how many there were.
        self.conditions = list(conditions)
        #: True when no comment stated a verdict row. Distinct from every row
        #: reading UNSTATED, which means the close-out was read and declined.
        self.absent = absent
        #: What the pairing could not do - a row quoting no condition, a row
        #: count that does not match the field's, a row numbered wrongly. Each
        #: is reported on the comment; none of them files a verdict.
        self.defects = list(defects)

    @property
    def unmet(self):
        return [r for r in self.rows if r[2] != "MET"]

    def headline(self):
        total = len(self.rows)
        if not self.unmet:
            return (f"All {total} Definition of Done conditions are reported "
                    f"met by the close-out.")
        numbers = ", ".join(str(r[0]) for r in self.unmet)
        return (f"{len(self.unmet)} of {total} Definition of Done conditions "
                f"are not reported met: condition {numbers}. "
                f"This ticket is not ready for Done on the close-out's own "
                f"account.")


def build_table(dod, comments, key=None):
    """Pair every condition against the verdict the close-out stated for it."""
    conditions = conditions_in(dod)
    if not conditions:
        return VerdictTable([], "no Definition of Done to pair against")

    stated, used, defects = merged_verdicts(comments, conditions, key)
    if not used:
        return VerdictTable([], "no close-out checklist on the ticket",
                            conditions=conditions, absent=True)

    return VerdictTable([(i, text, stated.get(i, UNSTATED))
                         for i, text in enumerate(conditions, 1)],
                        conditions=conditions, defects=defects)


def table_body(table, sha):
    """The ADF comment carrying the table.

    The rows go in a fenced block: pt-backlog records that Jira's
    markdown-to-ADF conversion silently drops a blockquote opening with a
    heading, and a fenced block survives whatever it holds.
    """
    width = max((len(r[2]) for r in table.rows), default=len(UNSTATED))
    rows = "\n".join(
        f"{number:>3}  {verdict:<{width}}  {_clip(text)}"
        for number, text, verdict in table.rows)
    trailer = (
        "Each verdict above is filed under the condition the close-out quoted, "
        "not under the number it typed (PPA-1517), and is quoted from that "
        "close-out or reads UNSTATED. Nothing here is computed from the ticket, "
        f"the diff or the pull request, and no condition is omitted. Recorded "
        f"on merge {sha[:12]} by the close-out workflow (PPA-1416).")
    content = [
        _para(table.headline()),
        {"type": "codeBlock", "content": [{"type": "text", "text": rows}]},
    ]
    if table.defects:
        content.append(_para(
            "The close-out's checklist did not pair cleanly against the "
            "Definition of Done: " + "; ".join(table.defects) + "."))
    content.append(_para(trailer))
    return {"content": content, "type": "doc", "version": 1}


def absent_body(table, sha):
    """The comment posted when the ticket carries no close-out checklist.

    Deliberately not a table of UNSTATED rows. That shape says the close-out
    was read and stated nothing; this one says there was no close-out to read,
    which is a different thing for a conductor to act on - PPA-1407's table of
    9 of 9 UNSTATED was produced 86 seconds before its close-out was written.
    """
    text = (
        f"No close-out checklist was on this ticket when the merge landed, so "
        f"no verdict table could be built. Its Definition of Done carries "
        f"{len(table.conditions)} condition(s), none of them paired against a stated "
        f"verdict.\n\n"
        f"This is not a table of UNSTATED rows and should not be read as one: "
        f"the close-out was absent rather than silent. If one was posted after "
        f"the merge, it is on the ticket above this comment and has not been "
        f"read by anything. Recorded on merge {sha[:12]} by the close-out "
        f"workflow (PPA-1416).")
    return {"content": [_para(text)], "type": "doc", "version": 1}


def _para(text):
    return {"content": [{"text": text, "type": "text"}], "type": "paragraph"}


def _clip(text, limit=110):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


#: What a posted table signs itself with, so a re-run can recognise its own
#: work. The hash comment's guard cannot serve here - it looks for the full
#: SHA, which the table carries only in its short form.
TABLE_MARK = "by the close-out workflow (PPA-1416)"


def table_already_posted(comments, sha):
    """True when a table for this merge is already on the ticket."""
    return any(TABLE_MARK in adf_text(c.get("body"))
               and sha[:12] in adf_text(c.get("body"))
               for c in comments or [])


def safe_table(dod, comments, key=None):
    """The verdict table, or None when it cannot be built. Never raises.

    PPA-1459 made this reading load-bearing for routing as well as reporting,
    so it is built once in close_out() and handed to both. None is a failure
    path: plan_transition() routes it to Client Validation, never to Done.
    """
    try:
        return build_table(dod, comments, key)
    except Exception:            # noqa: BLE001 - never fail a merge over it
        return None


def post_table(post, key, table, comments, sha, dry_run=False):
    """Post the verdict table. Returns a note for the outcome line.

    Nothing raised here reaches the caller's verdict: the table is an addition
    to the close-out and a merge whose ticket cannot be summarised still gets
    its hash. See "It never blocks, fails or delays a merge" above.
    """
    try:
        if table_already_posted(comments, sha):
            return "verdict table already posted for this merge"
        if table is None:
            return "verdict table not built"
        if table.absent:
            if dry_run:
                return "would report an absent close-out checklist"
            post(f"/issue/{key}/comment", {"body": absent_body(table, sha)})
            return (f"no close-out checklist; reported as absent rather than "
                    f"as {len(table.conditions)} UNSTATED row(s)")
        if not table.rows:
            return f"no verdict table - {table.note}"
        if dry_run:
            return f"would post a verdict table, {len(table.unmet)} row(s) not met"
        post(f"/issue/{key}/comment", {"body": table_body(table, sha)})
    except Exception as exc:  # noqa: BLE001 - never fail a merge over the table
        return f"verdict table not posted: {exc}"
    return (f"verdict table posted, {len(table.unmet)} of {len(table.rows)} "
            f"row(s) not met")


# -------------------------------------------------------------------- policy

def condition_class(text):
    """The class a condition declares, or None when it declares none."""
    match = CLASS_RE.match(text or "")
    return match.group(1).lower() if match else None


def plan_transition(status, table=None):
    """Return (target, reason, failures) - the merge's three outcomes, stated once.

    ``target`` is the status to move the key to, or None when it is not moved.
    ``failures`` is the (number, condition text) list that held it, empty unless
    the grade failed - so ``target is None and failures`` is the third outcome
    and ``target is None and not failures`` is the ordinary wrong-status skip.

    Pure by design, like pt_transition.requires_conductor(): no client, no
    credentials, no network, so the rule is testable on its own. The verdict
    table is passed in for the same reason - PPA-1416 already reads
    customfield_10767 and pairs it against the close-out, and PPA-1459 routes
    on that reading rather than repeating it.

    The three outcomes, PPA-1518 as amended 17-SEP-2026:

    * Every condition ``[machine]`` and every one MET -> **Done**. Auto-Done,
      per pt-backlog; PPA-1459 shipped the guard that lets this actor fire the
      In Progress to Done hop.
    * Any ``[conductor]`` condition, any ``[observer]`` condition outstanding,
      or any unclassified condition -> **Client Validation**. Classes are
      forward-only from 12-SEP-2026, so every older ticket lands here rather
      than being treated as carrying a defect.
    * Any condition unmet, or stated by no close-out the parser could read ->
      **no transition**. The key stays at In Progress and a comment names every
      condition that held it.

    **Why the third outcome is the absence of a status.** A ticket with an unmet
    condition is not finished, so Client Validation would assert something
    false. Reopened would be the honest status and it is not reachable: read
    live from the PPA workflow on 17-SEP-2026, a ticket at In Progress is
    offered seven transitions and none of them reaches Reopened - it is offered
    only from Client Validation, by "Client Rejected - Restart Work", and
    pt_transition.CONDUCTOR_ONLY records the same rule. Reopened is the
    conductor's hop. Leaving the key where it is, with the failures named, is
    the only honest outcome the workflow offers.

    The class check runs before the unmet check, and that order is the rule
    rather than an accident: an outstanding ``[observer]`` condition is unmet by
    construction, and it belongs at Client Validation rather than held.

    Takes no labels. It used to: a ``needs-live-validation`` label selected
    Client Validation and everything else went to Done. The label selected
    nothing once Client Validation became the only outcome, and Auto-Done is
    decided by the conditions rather than by a label, so it has not come back.

    ``table`` None means the table could not be built at all. That is a failure
    path and routes to Client Validation like every other one - a machine that
    could not read the grade has not found a failed condition, so it holds
    nothing and hands the ticket to the gate that reads for itself.
    """
    if norm(status) != norm(MERGED_FROM):
        return None, f"status is {status!r}, not {MERGED_FROM!r}", []
    if table is None:
        return MERGED_TO, "merged; the verdict table could not be built", []
    if table.absent:
        return None, ("merged; no close-out checklist to grade against, so no "
                      "condition is evidenced and nothing is transitioned"), [
            (i, text) for i, text in enumerate(table.conditions, 1)]
    if not table.rows:
        return MERGED_TO, f"merged; {table.note or 'no verdict table'}", []

    classes = [condition_class(text) for _number, text, _verdict in table.rows]
    if any(cls != "machine" for cls in classes):
        named = sorted({cls or "unclassified" for cls in classes
                        if cls != "machine"})
        return MERGED_TO, (f"merged; {', '.join(named)} condition(s) need a "
                           f"conductor, so the Definition of Done is not "
                           f"evidenced by a merge"), []
    if table.unmet:
        return None, (f"merged; {len(table.unmet)} of {len(table.rows)} "
                      f"conditions are not reported met, so nothing is "
                      f"transitioned and the key stays at "
                      f"{MERGED_FROM!r}"), [(r[0], r[1]) for r in table.unmet]
    return MERGED_TO_DONE, (f"merged; all {len(table.rows)} conditions are "
                            f"[machine] and all reported met (Auto-Done)"), []


def comment_body(sha, pr_number, date):
    """The ADF comment. Hyphens, never em dashes - see pt-backlog."""
    where = f" via pull request #{pr_number}" if pr_number else ""
    text = (f"Merged to main as {sha}{where} on {date}. "
            f"Recorded by the merge-triggered close-out workflow (PPA-1261).")
    return {"content": [{"content": [{"text": text, "type": "text"}],
                         "type": "paragraph"}],
            "type": "doc",
            "version": 1}


def already_commented(comments, sha):
    """True when some existing comment already names this merge SHA."""
    return any(sha in adf_text(c.get("body")) for c in comments)


#: What the held comment signs itself with, so a re-run recognises its own work.
HELD_MARK = "held at In Progress by the close-out workflow (PPA-1518)"


def held_body(failures, sha):
    """The comment posted when a merge applies no transition.

    Names every condition that held the key, because the conductor's next act
    is to decide what happens to this ticket and a count does not support that.
    The conditions go in a fenced block for the same reason the verdict table's
    rows do - see ``table_body``.
    """
    rows = "\n".join(f"{number:>3}  {_clip(text)}" for number, text in failures)
    return {"content": [
        _para(f"No transition was applied. {len(failures)} Definition of Done "
              f"condition(s) are not reported met by the close-out, so this "
              f"ticket is not finished and stays at {MERGED_FROM}."),
        {"type": "codeBlock", "content": [{"type": "text", "text": rows}]},
        _para(f"Client Validation would assert the work is finished and "
              f"awaiting sign-off, which the close-out's own verdicts "
              f"contradict, and Reopened is not offered from {MERGED_FROM} and "
              f"is the conductor's hop. Leaving the ticket here is the only "
              f"outcome this workflow can honestly apply - what happens next "
              f"is the conductor's call. Recorded on merge {sha[:12]}, "
              f"{HELD_MARK}."),
    ], "type": "doc", "version": 1}


def held_already_posted(comments, sha):
    """True when a held comment for this merge is already on the ticket."""
    return any(HELD_MARK in adf_text(c.get("body"))
               and sha[:12] in adf_text(c.get("body"))
               for c in comments or [])


def post_held(post, key, failures, comments, sha, dry_run=False):
    """Post the held comment. Returns a note for the outcome line.

    Nothing raised here reaches the caller's verdict, exactly as ``post_table``
    does not: a merge whose ticket cannot be commented still gets its hash, and
    the routing decision stands whether or not the comment landed.
    """
    try:
        if held_already_posted(comments, sha):
            return "held comment already posted for this merge"
        if dry_run:
            return (f"would report {len(failures)} condition(s) holding this "
                    f"ticket at {MERGED_FROM}")
        post(f"/issue/{key}/comment", {"body": held_body(failures, sha)})
    except Exception as exc:  # noqa: BLE001 - never fail a merge over a comment
        return f"held comment not posted: {exc}"
    return (f"held comment posted, naming {len(failures)} condition(s)")


# ----------------------------------------------------- the held Slack notice

#: The environment variable naming the channel a held notice goes to, set by
#: merge-close-out.yml from its slack_channel input (PPA-1601). Read from the
#: environment and never written into this file: the id is
#: configuration, it differs per repository, and this file is one of three
#: registered copies (scripts/cross_repo_copies.py), so a literal here would
#: ship one repository's channel into the other two.
CHANNEL_VAR = "SLACK_CHANNEL_DELIVERY_OPS"

#: The bot token the notice posts with. The caller passes it as a secret; with
#: no token the notice is a reported skip, like an unset channel.
TOKEN_VAR = "SLACK_BOT_TOKEN"

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"

#: Who the notice tells a reader to tag, per pt-slack-message-design section
#: Footer: the Space Lead, and Sean where none is defined. The close-out
#: workflow has no Space Lead.
NOTICE_TAG = "U087TAMCALR"


def notice_text(key, failures, sha, pr_number):
    """The Slack notice for one held key.

    Bullet List rather than a Code Block Table, per pt-slack-message-design's
    format gate: every row carries one value - a condition - rather than two or
    more columns to compare. Section headers and the footer are italic; the
    hour-total line and the CC line do not apply to a Bullet List.

    It carries what a reader needs in order to act without opening the ticket:
    the key, the merge hash, the pull request, and every condition the verdict
    table reported unmet or unstated.
    """
    where = f" via pull request #{pr_number}" if pr_number else ""
    rows = "\n".join(f"\u2022 {number}. {_clip(text)}" for number, text in failures)
    return (f"\U0001f4cb _Close-out held - {key}_\n"
            f"\n"
            f"_Merged as `{sha[:12]}`{where}_\n"
            f"\u2022 No transition was applied, so {key} stays at {MERGED_FROM}\n"
            f"\n"
            f"_{len(failures)} condition(s) not reported met or not stated_\n"
            f"{rows}\n"
            f"\n"
            f"_Questions about this notice? Reply in thread and tag "
            f"<@{NOTICE_TAG}> \u2014 I'll look into it._")


def post_notice(token, channel_id, text):
    """Post one notice through Slack's chat.postMessage.

    PPA-1601. Plain urllib, like pt_transition.make_client, because a called
    workflow's runner has no peech_shared: the earlier import of
    peech_shared.slack failed on every run, so no notice was ever sent from
    here. Slack reports a refused post as HTTP 200 carrying ``"ok": false``,
    so that is raised too, not read as success.
    """
    req = urllib.request.Request(
        SLACK_POST_URL,
        data=json.dumps({"channel": channel_id, "text": text}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read() or b"{}")
    if not body.get("ok"):
        raise RuntimeError(f"chat.postMessage refused: {body.get('error')}")


def notify_held(key, failures, sha, pr_number, comments=(), dry_run=False):
    """Tell the delivery-ops channel that this key was graded, failed and held.

    PPA-1534, as amended by comment 29460 on 22-SEP-2026. Returns a note for
    the outcome line and raises nothing, for the same reason post_held and
    post_table raise nothing: where a merged ticket goes is this workflow's
    decision, and a Slack outage may not change it.

    Three guards before the send. An unset channel or token is a skip rather
    than an error, which is how registry_reconcile treats its own; and a merge whose
    held comment was already posted has already been announced, so a re-run of
    the same merge stays silent. That is the guard post_held uses, read against
    the comments as they were before this run wrote anything.
    """
    try:
        channel = os.environ.get(CHANNEL_VAR, "").strip()
        if not channel:
            return f"no notice sent: {CHANNEL_VAR} is not set"
        token = os.environ.get(TOKEN_VAR, "").strip()
        if not token:
            return f"no notice sent: {TOKEN_VAR} is not set"
        if held_already_posted(comments, sha):
            return "notice already sent for this merge"
        if dry_run:
            return f"would notify {channel}, naming {len(failures)} condition(s)"
        post_notice(token, channel, notice_text(key, failures, sha, pr_number))
    except Exception as exc:  # noqa: BLE001 - never fail a merge over a notice
        return f"notice not sent: {exc}"
    return f"notice sent to {channel}, naming {len(failures)} condition(s)"


# ------------------------------------------------------------------ the work

class Outcome:
    """One key's result.

    verdict is COMMENTED, SKIPPED, HELD, MOVED or FAILED. HELD is PPA-1518's
    third outcome - the key was graded, the grade failed, and no transition was
    applied. It is kept apart from SKIPPED, which means the key was never at
    In Progress and so was never graded, and apart from FAILED, which means
    this run could not do its job. Neither of the first two is a failure of the
    run; only one of them is a statement about the ticket.
    """

    def __init__(self, key, verdict, detail=""):
        self.key = key
        self.verdict = verdict
        self.detail = detail

    def line(self):
        return f"{self.key:<10} {self.verdict:<10} {self.detail}"


def close_out(get, post, key, sha, pr_number, date, dry_run=False):
    """Comment the hash on one key, then transition it if the rule allows."""
    try:
        issue = get(f"/issue/{key}?fields=status,comment,customfield_10767")
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        return Outcome(key, "FAILED", f"read failed: {exc}")

    fields = issue["fields"]
    status = fields["status"]["name"]
    comments = (fields.get("comment") or {}).get("comments") or []
    dod = fields.get("customfield_10767")

    if already_commented(comments, sha):
        note = f"already carries a comment naming {sha[:12]}; not re-commented"
    elif dry_run:
        note = f"would comment {sha[:12]}"
    else:
        try:
            post(f"/issue/{key}/comment", {"body": comment_body(sha, pr_number, date)})
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            return Outcome(key, "FAILED", f"comment failed: {exc}")
        note = f"commented {sha[:12]}"

    # The table is built from the comments as they were read, so this script's
    # own hash comment above is not in the set it searches. That is incidental
    # rather than load-bearing - the selector reads verdict rows and
    # would skip it anyway.
    #
    # Built once and read twice, since PPA-1459: the same table reports the
    # close-out and decides the destination. The hash comment is already posted
    # by this point, so a key reaching Done satisfies the graduation gate's
    # second requirement at the moment its status changes.
    table = safe_table(dod, comments, key)
    note = f"{note}; {post_table(post, key, table, comments, sha, dry_run)}"

    # PPA-1601: a key at To Do is moved to In Progress, then graded as if it
    # had been found there. A failed hop leaves it at To Do, ungraded.
    if norm(status) == norm(STARTED_FROM):
        hop = f"{STARTED_FROM!r} to {MERGED_FROM!r} first"
        if dry_run:
            note = f"{note}; would move {hop}"
        else:
            moved, said = fire(key, MERGED_FROM)
            if not moved:
                return Outcome(key, "FAILED", f"{note}; {hop} failed - {said}")
            note = f"{note}; moved {hop}"
        status = MERGED_FROM

    target, reason, failures = plan_transition(status, table)
    if failures:
        # The third outcome, PPA-1518: graded, failed, and deliberately left
        # where it is. Distinct from SKIPPED, which means the key was never at
        # In Progress and was never graded at all.
        note = f"{note}; {post_held(post, key, failures, comments, sha, dry_run)}"
        # Last, and after the routing is settled: PPA-1534's notice may not
        # change where this ticket goes, so nothing below it decides anything.
        note = f"{note}; {notify_held(key, failures, sha, pr_number, comments, dry_run)}"
        return Outcome(key, "HELD", f"{note}; not transitioned - {reason}")
    if target is None:
        return Outcome(key, "SKIPPED", f"{note}; not transitioned - {reason}")

    if dry_run:
        return Outcome(key, "COMMENTED",
                       f"{note}; would move to {target!r} - {reason}")

    moved, said = fire(key, target)
    return Outcome(key, "MOVED" if moved else "FAILED",
                   f"{note}; {target!r} - {said}")


def fire(key, target):
    """Move one key to ``target`` through pt_transition.py.

    Returns (moved, what the script said)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--keys", key, "--to", target],
        capture_output=True, text=True)
    said = (proc.stdout.strip() or proc.stderr.strip() or "no output")
    return proc.returncode == 0, said


def run(get, post, keys, sha, pr_number, date, dry_run=False):
    return [close_out(get, post, k, sha, pr_number, date, dry_run) for k in keys]


def held_by_workflow(comments):
    """True when some comment on this ticket is a held comment this file wrote.

    The mark, not the status: a ticket can be at In Progress for a dozen
    reasons, and only one of them is a grade this workflow ran and failed.
    """
    return any(HELD_MARK in adf_text(c.get("body")) for c in comments or [])


#: Every ticket this script may re-grade: held at In Progress, carrying a held
#: comment. The comment clause is a text-index match and is confirmed against
#: the comment bodies afterwards, because ``~`` is word-based and will return a
#: ticket that merely quotes the phrase.
HELD_JQL = (f'project = PPA AND status = "{MERGED_FROM}" '
            f'AND comment ~ "{HELD_MARK}" ORDER BY updated ASC')


def held_keys(get, jql=HELD_JQL, max_results=100):
    """Every key the held sweep should look at. A read failure raises."""
    query = urllib.parse.urlencode({"jql": jql, "maxResults": str(max_results),
                                    "fields": "status"})
    data = get(f"/search/jql?{query}")
    return [issue["key"] for issue in data.get("issues") or []]


#: What a re-grade comment signs itself with, so a re-run recognises its own
#: work and a reader can find every ticket this path closed.
REGRADE_MARK = "re-graded by the close-out sweep (PPA-1556)"


def regrade_body(target, table):
    """The comment posted when a later checklist clears a held ticket."""
    return {"content": [
        _para(f"A close-out checklist posted after the merge reports every "
              f"Definition of Done condition met, so the transition the merge "
              f"run would have applied is applied now: {MERGED_FROM} to "
              f"{target}."),
        _para(f"{table.headline()} Nothing about the grade changed - the same "
              f"conditions were read against the same rule, later. Recorded "
              f"as {REGRADE_MARK}."),
    ], "type": "doc", "version": 1}


def regrade(get, post, key, dry_run=False):
    """Re-grade one ticket the merge close-out left held. Returns an Outcome.

    PPA-1556. ``merge-close-out.yml`` reads a ticket's comments once, on the
    merge event, and nothing re-reads. A close-out that lands after that is
    invisible to it, so the ticket sits at In Progress carrying a checklist
    reporting every condition met and only a person notices. Two instances,
    both 18-SEP-2026: PPA-1505 merged as 0a2daca at 11:51 and its verdict table
    was posted at 12:09; PPA-1541 merged as 4d41d5b at 17:48 and its close-out
    at 17:55. Both were recorded as absent and both were closed by hand.

    This is the same grade, read later. It applies ``plan_transition`` to the
    comments as they stand now, and it can only ever reach the status that
    run would have reached: the rule is not re-implemented here and no verdict
    is re-decided.

    Three things it declines to do, each because the merge run already owns it:

    * A ticket no longer at ``In Progress`` is not touched. Something moved it
      - the merge run, a conductor, a second sweep - and re-applying a
      transition on top of that would overwrite a decision this has no view of.
    * A ticket carrying no held comment is not touched. It was never held by
      this workflow, so the checklist on it has never been graded by anything
      here and a sweep is not the place to grade one for the first time.
    * A grade that still fails leaves the ticket exactly where it is, and posts
      nothing. The held comment naming the conditions is already on the ticket
      and a second copy per sweep is noise.

    The hash comment is not re-posted either: the merge run wrote it, which is
    what satisfies the graduation gate, and this path runs only on a ticket
    that run already reached.
    """
    try:
        issue = get(f"/issue/{key}?fields=status,comment,customfield_10767")
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        return Outcome(key, "FAILED", f"read failed: {exc}")

    fields = issue["fields"]
    status = fields["status"]["name"]
    comments = (fields.get("comment") or {}).get("comments") or []

    if norm(status) != norm(MERGED_FROM):
        return Outcome(key, "SKIPPED",
                       f"status is {status!r}, not {MERGED_FROM!r}; "
                       f"already transitioned, not transitioned again")
    if not held_by_workflow(comments):
        return Outcome(key, "SKIPPED",
                       "carries no held comment; never held by this workflow")

    table = safe_table(fields.get("customfield_10767"), comments, key)
    target, reason, failures = plan_transition(status, table)
    if target is None:
        return Outcome(key, "HELD", f"still held - {reason}")

    if dry_run:
        return Outcome(key, "COMMENTED", f"would move to {target!r} - {reason}")

    try:
        post(f"/issue/{key}/comment", {"body": regrade_body(target, table)})
        note = "re-grade comment posted"
    except Exception as exc:  # noqa: BLE001 - never lose a transition to a comment
        note = f"re-grade comment not posted: {exc}"

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--keys", key, "--to", target],
        capture_output=True, text=True)
    verdict = "MOVED" if proc.returncode == 0 else "FAILED"
    said = (proc.stdout.strip() or proc.stderr.strip() or "no output")
    return Outcome(key, verdict, f"{note}; {target!r} - {said}")


def regrade_run(get, post, keys, dry_run=False):
    return [regrade(get, post, k, dry_run) for k in keys]


#: A run that did every part of its job.
OK = 0
#: A key this run could not process: a read, a comment or a transition failed.
FAILED_EXIT = 1
#: A key this run found and did not transition, with nothing having failed.
#: Distinct from both, since PPA-1464: the step is named for closing out every
#: key the merge carried, and a run that carried one of four concluded plain
#: success. Green is what stops anyone looking, so a partial close-out is not
#: green. It is separated from FAILED_EXIT because the two ask for different
#: things - a failure is investigated, a skip is usually read once and
#: accepted.
PARTIAL_EXIT = 2


def transitioned(outcome):
    """Whether this key actually moved. A dry run moves nothing and says so."""
    return outcome.verdict in ("MOVED", "COMMENTED")


def exit_code(outcomes):
    """OK, FAILED_EXIT or PARTIAL_EXIT - see each for what it claims."""
    if any(o.verdict == "FAILED" for o in outcomes):
        return FAILED_EXIT
    if any(not transitioned(o) for o in outcomes):
        return PARTIAL_EXIT
    return OK


# ------------------------------------------------------------------------ cli

def merge_message():
    """The merge commit's full message, read from git rather than interpolated.

    Reading it here keeps an untrusted commit message out of the workflow's
    shell entirely: nothing expands it, so nothing in it can be executed.
    """
    return subprocess.run(["git", "log", "-1", "--pretty=%B", "HEAD"],
                          capture_output=True, text=True, check=True).stdout


def build_parser():
    parser = argparse.ArgumentParser(
        description="Comment the merge hash on every PPA key a squash-merge "
                    "carried, and transition each one.")
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"),
                        help="merge commit SHA (default: $GITHUB_SHA)")
    parser.add_argument("--message", default=None,
                        help="commit message (default: read from git)")
    parser.add_argument("--head-ref", default=os.environ.get("GITHUB_HEAD_REF"),
                        help="the merged pull request's head branch, which names "
                             "the one ticket to close out (default: "
                             "$GITHUB_HEAD_REF, which a push event does not set)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would happen and write nothing")
    parser.add_argument("--regrade", action="store_true",
                        help="re-grade the tickets a merge run left held at "
                             f"{MERGED_FROM!r}, instead of closing out a merge")
    parser.add_argument("--keys", default=None,
                        help="with --regrade, the comma-separated keys to "
                             "re-grade instead of searching for them")
    return parser


def regrade_main(args):
    """The ``--regrade`` half. Returns the same three exit codes ``main`` does.

    PPA-1556. The sweep is the second reader: it finds every ticket left at
    In Progress by a merge run's held comment, re-reads the comments as they
    stand now, and applies the transition that run would have applied if the
    checklist had arrived in time.

    A run finding nothing to do is OK rather than PARTIAL. There is no partial
    close-out here - an empty held set is the state this sweep exists to
    produce, and reporting it as not-green would make the ordinary case the
    noisy one.
    """
    get, post = make_client(load_credentials())
    if args.keys:
        keys = [k.strip().upper() for k in args.keys.split(",") if k.strip()]
    else:
        try:
            keys = held_keys(get)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"held search failed: {exc}", file=sys.stderr)
            return FAILED_EXIT
    if not keys:
        print(f"no ticket is held at {MERGED_FROM!r} by this workflow")
        return OK

    print(f"re-grading {len(keys)} held key(s): {', '.join(keys)}")
    outcomes = regrade_run(get, post, keys, args.dry_run)
    for outcome in outcomes:
        print(outcome.line())
    failed = [o.key for o in outcomes if o.verdict == "FAILED"]
    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
        return FAILED_EXIT
    return OK


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.regrade:
        return regrade_main(args)
    message = args.message if args.message is not None else merge_message()
    sha = args.sha or subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        check=True).stdout.strip()

    sources = key_sources(args.head_ref, message)
    keys = list(sources)
    if not keys:
        where = ("branch {!r}, the merge commit subject or its commit subjects"
                 .format(args.head_ref) if args.head_ref
                 else "the merge commit subject or its commit subjects")
        print(f"no PPA key in {where}; nothing to close out")
        return OK

    pr_number = pr_number_in(message)
    date = datetime.date.today().strftime("%d-%b-%Y").upper()
    print(f"merge {sha} pull request "
          f"{('#' + pr_number) if pr_number else '(none found)'}: "
          f"found {len(keys)} key(s)")
    # Every key and the source that produced it, before anything is attempted.
    # A run that dies part way through has still said what it was working from.
    for key, found_in in sources.items():
        print(f"  {key:<10} found in {', '.join(found_in)}")

    get, post = make_client(load_credentials())
    outcomes = run(get, post, keys, sha, pr_number, date, args.dry_run)
    for outcome in outcomes:
        print(outcome.line())

    # The half that matters more than the derivation - PPA-1464. Three keys
    # were left at In Progress by a green run whose output never named them,
    # and the green result is what stopped anyone looking.
    untransitioned = [o for o in outcomes if not transitioned(o)]
    if untransitioned:
        print(f"NOT TRANSITIONED: {len(untransitioned)} of {len(keys)} key(s) "
              f"found were not transitioned")
        for outcome in untransitioned:
            print(f"  {outcome.key:<10} {outcome.verdict} - {outcome.detail}")
    failed = [o.key for o in outcomes if o.verdict == "FAILED"]
    if failed:
        print(f"FAILED: {', '.join(failed)}", file=sys.stderr)
    return exit_code(outcomes)


if __name__ == "__main__":
    sys.exit(main())
