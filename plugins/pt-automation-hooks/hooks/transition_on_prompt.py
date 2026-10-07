#!/usr/bin/env python3
"""UserPromptSubmit hook (PPA-1126) — move every PPA key in the prompt to In Progress.

Nothing moved a ticket from To Do to In Progress. PPA-1021 scripted the
transition path so no session would carry transition IDs in prose, PPA-1024
then retired the prose duty from the skill suite because ``pt_transition.py``
owned it — but that script is conductor-run and nobody fired it at dispatch.
PPA-1103 and PPA-1107 both finished their builds with the ticket still at To
Do. This hook fires it instead of asking anyone to remember.

Every key, never the first
--------------------------
A batch prompt carries several keys — bat-cmd-02 dispatched four in one line.
A hook that transitions only the first leaves the rest behind and is worse than
no hook, because it looks like it worked.

The transition never blocks
---------------------------
A Jira failure, a missing credential, an unreachable network: warn and exit
zero. A transition is bookkeeping, and refusing to start work because
bookkeeping failed is the wrong trade. This is the opposite of the deploy
preflight, which refuses on purpose.

Exit 2 is the only code that blocks a UserPromptSubmit hook. Nothing in the
transition half can reach it, and that is unchanged. Three admission checks
below can, each on a positive answer from Jira and on nothing else: the
repository-match check (PPA-1465), the dispatch-completeness check (PPA-1418)
and the Ticket Quality Bar check (PPA-1427), which also carries the
settings-file rule (PPA-1758) and the merge-wait rule (PPA-1769). One refusal
reads the prompt alone and asks Jira nothing: a first line carrying two or
more keys and other words (PPA-1784). The deployed-skill drift report
(PPA-1470) is not one of them - it warns. Every other path in this file
returns 0.

The warning rides out as ``systemMessage`` JSON rather than on stderr, because
stderr from a hook that exits 0 reaches the debug log only — the operator would
never see it. Plain-text stdout would be injected into the model's context
instead, which is why success prints nothing at all.

Every outcome is logged, at ``~/.claude/pt-transition-hook.log``
----------------------------------------------------------------
A warning nobody reads is not a report. PPA-1262: three dispatches on
07-SEP-2026 did not transition, and the cause could not be recovered afterward
because every failure path warned through ``systemMessage`` and returned 0,
leaving no trace. One JSON record per event is appended to that log — the
timestamp, the keys, the subprocess exit code and its stderr verbatim — so a
run that did not transition is findable later without re-deriving it from Jira
history. The log sits under ``~/.claude/`` rather than in a repository: this
file is byte-identical across three checkouts, and none of them wants an
untracked log in its working tree.

Dropped (PPA-1716): the claim above is stale. On 29-SEP-2026 no sibling
repository held a copy of this file and no byte-identity register named it; the
plugin is its one home (PPA-1580, PPA-1587). The same claim sits in
arm_auto_merge.py's docstring, in the ``_PASTE_TAG_RE`` comment below and in
test_transition_on_prompt.py. What breaks if not fixed: a session that reads
one of them looks for a copy or a register in three repositories and finds
none, which cost PPA-1716 and PPA-1720 two rounds of reads each.

**It records every path, not only the failures — PPA-1548.** PPA-1262 left the
log failures-only, and the success path wrote to exactly one place: the
per-session cache in ``$TMPDIR``. PPA-1543 read this file end to end on
18-SEP-2026 and found none of the log call sites on that path, which is why
PPA-1538 and PPA-1543 both sat at To Do with nothing anywhere saying whether
this hook never fired or returned early at one of its own guards. The two look
identical from outside, and separating them is the whole of this change.

The existing sink gained the success records; no second sink was added. One
file, one JSON Lines format and one ``reason`` vocabulary is what keeps a run
greppable, and a reader who first has to work out which of two sinks to look in
has the same problem one level up. The cost is volume: this hook fires on every
prompt, so an ordinary working session now appends a ``no-dispatch`` line per
turn where it previously appended nothing. That is the trade — the log is read
by grepping ``reason``, and a log that is quiet because it records nothing is
the defect being closed.

The reasons, one per path ``_transition`` can take. The refusals already
wrote one each, inside the check that raises them, so nothing was added there:

  ``unreadable-payload``          stdin was not JSON
  ``no-dispatch``                 the leading line named no key
  ``malformed-dispatch``          it named keys and did not qualify; exit 2
                                  at two or more keys, a warning at one
  ``dispatch-for-another-repository`` exit 2, the session is elsewhere
  ``dispatch-spans-repositories``     exit 2, the keys name two remotes
  ``dispatch-incomplete``             exit 2, a dispatchable ticket is unnamed
  ``dispatch-mixed-work-types``       exit 2, one line names both work types
  ``bar-failed``                      exit 2, a ticket fails the Bar
  ``merge-wait-refused``              exit 2, a done list waits on its merge
  ``already-settled``           every dispatched key settled earlier
  ``no-script``                   ``pt_transition.py`` is not on disk
  ``subprocess-failed``           it could not be run
  ``nonzero-exit``                it ran and did not settle every key
  ``unparseable-output``          it ran, exited 0 and printed no verdict
  ``transitioned``                it ran and every verdict line was read
  ``hook-raised``                 anything else, caught by ``main``

The two that carry ``first_line`` are the two that resolved no key, and they
carry it because that line is the entire cause. ``dispatched_keys``' first-line
rule is not relaxed here: a prompt whose leading line is prose still dispatches
nothing, and it now says so.

A parse failure is logged as its own reason and carries the raw stdout with it.
A subprocess that ran but produced no verdict line, and a subprocess that
failed outright, are indistinguishable from the outside — that is exactly the
ambiguity that cost PPA-1262 its root cause.

The log write can never raise: a failure to record a failure still returns 0.

No environment is loaded, and none is needed
--------------------------------------------
PPA-1262 was opened believing ``pt_transition.py`` reads ``JIRA_EMAIL`` and
``JIRA_API_TOKEN`` from its caller. It does not — it holds an absolute
``CREDENTIALS`` path and reads that file itself, with no ``os.environ`` access
anywhere in it. Both the script and this hook run end to end under ``env -i``.
Do not add an environment load here on the strength of the original ticket
text; the load would be dead code and the defect it named does not exist.

Once per key per session
------------------------
Idempotence is already handled downstream: ``pt_transition.py`` reads the
current status and reports NOOP without writing when the key is already at the
target. But this hook fires on every prompt, not on dispatch alone, and a
session that keeps citing PPA-1126 would pay a live Jira read per key per
prompt. Keys that reached a settled verdict are recorded per session and
skipped. A HALT is not settled and is retried on the next prompt.

A dispatched key is not a mentioned one — PPA-1418
--------------------------------------------------
The paragraph above used to end "the cost is one ticket moved a rung early,
visible and reversible". That was accepted as a risk and then observed as a
defect. At 21:22 EDT on 12-SEP-2026 a dispatch carrying PPA-1413 and PPA-1417
cited PPA-1407 in its prose, once, as a pointer to where PPA-1417's evidence
lived. At 21:23:33 PPA-1407 moved from Reopened to In Progress. No session
worked it and nothing was built.

So the two readings are now separated:

* **Dispatched** — the keys on the prompt's first non-blank line, where that
  line holds nothing but PPA keys and separators. This is the shape every
  dispatch in the estate is written in, and it is the only thing transitioned.
* **Mentioned** — every key anywhere in the prompt, which is what ``keys_in``
  has always returned. It no longer transitions anything. It survives because
  the completeness check below needs it: a conductor opting out of a ticket
  writes the key in prose, and that must not be the act that moves it.

A prompt whose first line is prose names no dispatched key, so it transitions
nothing and blocks nothing. That is deliberate: it is not a dispatch.

**This narrows what is transitioned, and the narrowing is the point.** Keys
that are dispatched today sit on the leading line and still move. Keys that
only appear in prose stop moving, which is the defect above. Nothing that was
dispatched stops being transitioned, so the constraint PPA-1418 set on this
choice — that existing behaviour must not silently narrow — is met by the
distinction rather than waived.

An incomplete dispatch is blocked — PPA-1418
---------------------------------------------
A dispatch is required to carry every dispatchable ticket for its repository.
That rule lived only in prose read by an actor composing the line by hand, and
on 12-SEP-2026 it was violated: peech-skills had four open dispatchable tickets
and the dispatch carried three, costing one extra dispatch and two rounds of a
wrong explanation for the omission.

On a prompt carrying dispatched keys, this hook reads the repository's open
dispatchable set — status To Do or Reopened, an execution component, and the
``REPO:`` component the dispatched keys themselves carry — and blocks the prompt
when a ticket in that set is named nowhere in it. The opt-out is naming the key:
a dispatch that says which tickets it is leaving is legal under the standing
rule, so a prompt mentioning an omitted key anywhere passes.

The repository comes from the tickets, never from the checkout — PPA-1419
--------------------------------------------------------------------------
PPA-1418 shipped this deriving the repository from the working directory, and it
was wrong within minutes of merging. A dispatch of three peech-skills tickets
was refused for being incomplete against ``REPO: peech-pmo-automation``, naming
two keys belonging to neither the dispatch nor the repository it was for.

``CLAUDE_PROJECT_DIR`` says where the session is rooted, not which repository
the dispatch is for. Those are two different questions, and the completeness
check asks the second: the dispatched keys carry their own ``REPO:`` component,
and that is what its comparison measures against. Deriving the comparison from
the checkout was PPA-1418's defect and PPA-1419's fix, and it is not revisited.

**Amended by PPA-1465. The working directory is an input, to a different
question.** This passage used to end "so the working directory is not an input
here at all", and it also recorded a cross-repository session as ordinary,
citing PPA-1413 and PPA-1417 shipping to peech-skills from a session rooted in
peech-pmo-automation on 12-SEP-2026. That is no longer ordinary: one session
per repository is the standing practice, and on 16-SEP-2026 a dispatch whose
tickets targeted one repository was pasted into a session rooted in another and
the two sessions collided in one working tree.

So ``CLAUDE_PROJECT_DIR`` is read, and it answers "where is this session" - the
question it was always the right source for. It is compared against the
dispatched keys' repository by the mismatch check below. It is still not the
comparison basis for completeness, which is the thing PPA-1419 corrected.

A dispatch is refused when the two disagree — PPA-1465
------------------------------------------------------
PPA-1460 pinned the Code Terminal label to one form carrying the repository
name, which merged in peech-skills pull request 207. That makes the target
visible; it cannot refuse a paste into the wrong window, and a conductor
writing the label correctly does not stop the paste landing elsewhere. A Code
Terminal block carries no ``cd`` line, because the session's working directory
is set before the paste.

``UserPromptSubmit`` runs inside the receiving session, knows where it is
rooted, and already reads the dispatched keys' ``REPO:`` components. Right
event, right actor, and the read it needs is the read it already performs.

**The refusal has no opt-out, and that is deliberate.** The completeness check
has one, and the Bar check has one, because a conductor can have a reason to
leave a ticket out or to dispatch one that fails an item. A repository mismatch
has no legitimate case: one commit reaches one remote, and a session cannot
ship a ticket to a repository it is not in. If a case emerges later it is a
ticket, not an undocumented escape.

A blocked ticket is not dispatchable — PPA-1465
------------------------------------------------
The dispatchable set the completeness check measures against was chosen by
status and execution component alone, so a ticket whose blocking link was still
open was demanded on every dispatch for its repository, and the only way past
it was an opt-out.

Measured 16-SEP-2026: a dispatch of PPA-1467 was refused for omitting PPA-1464
and PPA-1465. PPA-1464 was blocked by PPA-1456, read live as In Progress on an
unmerged pull request. The ticket was not dispatchable in any sense the
conductor recognises, and the refusal asked for an opt-out to say so. That is
the cost - an opt-out spent on a ticket nobody could have dispatched.

pt-backlog holds that a readiness dependency is a Jira blocking link rather
than a line of prose, so the link is the machine-readable statement of exactly
this and the check reads it. A ticket carrying an ``is blocked by`` link to an
issue that is not Done or Closed is outside the set. The excluded keys and
their blockers are named in a warning: a check that quietly shrinks its own
population is worse than one that asks too much.

A ticket held until its start date is not dispatchable — PPA-1752
------------------------------------------------------------------
PPA-1559 was dispatched against its date hold three times: 23-SEP-2026 and
twice on 25-SEP-2026. Ruling 1A, 30-SEP-2026: a date hold is recorded in the
Target start field, and a ticket whose Target start is later than today is not
dispatchable. PPA-1698 carries the batch generator half in peech-pmo-automation.

A ticket whose Target start is later than today in America/New_York is outside
the set, and is named in a warning beside the blocked keys. A ticket with no
Target start, or one of today or earlier, is demanded as before. The field is
found by its name in Jira's field list, never by its identifier, which Jira
assigns per site.

The set is measured by work type — PPA-1716
--------------------------------------------
Ruling 1A, 29-SEP-2026: a Discovery ticket (``EXA: Delegated Discovery``) runs in
its own session on Opus, launched with ``claude --model opus --effort high``, and
a Delegated ticket (``EXA: Delegated``) runs on Sonnet. The two never share a
dispatch. The completeness check therefore measures a dispatch against the
dispatchable tickets of its own work type only, in its own repository: a
Delegated-only dispatch is not refused for omitting Discovery keys, nor the other
way round. The opt-out is unchanged.

A leading line mixing both types is refused, with no opt-out, naming which keys
belong to which dispatch. Splitting it is the only fix; naming a key again would
put a Discovery ticket in a Sonnet session or the reverse. A ticket carrying both
components is a Discovery ticket, the more specific of the two. A dispatch whose
tickets carry neither is measured against the whole set, as before, and the Bar
check refuses the ticket that has no execution component.

One read for all three — PPA-1465
----------------------------------
The mismatch check, the completeness check and the Bar check want the same
issues and between them the same fields. Each used to ask Jira separately,
which was three searches on the prompt that starts a session. ``read_dispatched``
performs that read once and hands it down. A failure there is not fatal and not
special-cased: each check still owns its warn-and-allow, and one handed None
reads for itself.

Four cases follow from reading the tickets rather than the checkout, and only
the second adds a way to block:

* **The keys agree on one repository.** That repository's dispatchable set is
  the comparison, and an omission blocks as before.
* **The keys disagree.** A dispatch spanning two remotes is the command being
  wrong in its own right — one commit cannot span two remotes, and pt-backlog
  admits exactly one ``REPO:`` component on a Delegated ticket. It blocks, and
  the message names both repositories rather than picking one.
* **Some keys carry no ``REPO:`` component.** The repository is derived from the
  keys that do, and the unscoped keys are named in the warning so they are never
  silently excluded.
* **No key carries one.** No repository can be derived, so the check cannot run.
  It warns and allows, like every other path where the check cannot do its job.
  It does not block on its own inability.

**Why this blocks where the transition warns.** The reasoning recorded above —
a transition is bookkeeping, and refusing to start work because bookkeeping
failed is the wrong trade — does not reach here. An incomplete dispatch is not
bookkeeping about the work; it is the command being wrong, and the session acts
on it immediately. A warning printed above a prompt the session has already
accepted is a check that reports but cannot block.

This check exits 2 only on a positive answer from Jira. Every failure path it
owns — an unreadable working directory, absent credentials, a read failure, a
timeout — warns and allows, because a dispatch must not depend on Jira being
up. It was the only thing in this file that could exit 2 until PPA-1427 added
the Bar check and PPA-1465 the repository-match check; all three share that
policy exactly.

A ticket carrying no execution component is outside the dispatchable set and is
never a reason to block. That is not an oversight: such a ticket has not
cleared the Ticket Quality Bar and is not dispatchable.

The Bar itself is checked, mechanically — PPA-1427
---------------------------------------------------
pt-backlog says to run the Ticket Quality Bar when the EXA: Delegated component
is applied. pt-conduct-gates says a passing Bar is a pre-condition of dispatch.
Two trigger points and neither had a mechanism: both were the conductor
remembering. On 12-SEP-2026 the Bar was named twice in a thread handoff,
recorded there as "named twice, never run", and four tickets were then
dispatched without it.

The Bar splits, and only one half belongs in a script. ``BAR_ITEMS`` below
carries the mechanical half — properties readable off Jira — and each one
blocks. The two judgement items, whether a ticket is self-contained and the
ticket-internal contradiction check, are named there as deliberately out of
scope and are not approximated by a heuristic.

The opt-out is the completeness check's opt-out seen from the other side: there
a key the dispatch omits passes by being named in prose, here a key the
dispatch carries passes the same way. A mention on the dispatch line cannot
waive anything, because that is the mention that put the key in scope.

A barred artifact is caught before the dispatch is spent — PPA-1520
--------------------------------------------------------------------
A Definition of Done condition can demand something a governed rule forbids,
and then no compliant session can satisfy it. Four shipped that way and a
person found every one by reading the ticket afterwards - PPA-1428 condition 8,
PPA-1429 condition 9, PPA-1451 condition 11 and PPA-1453 condition 7, all four
demanding a change log or a revision-history entry, all four amended under
ruling 8A on 16-SEP-2026.

``scripts/check_dod_barred_artifacts.py`` detects them and, until PPA-1520,
nothing called it: its ``main()`` returns 0 whatever it finds, and its own
docstring records that making it block needs a caller that can refuse, an
opt-out, and a decision about precision. This hook is that caller. It already
reads ``customfield_10767`` for the Ticket Quality Bar, so the read costs
nothing, the wiring is one ``BAR_ITEMS`` entry, and the opt-out is the one the
Bar already has - naming the key again in prose.

**Why here and not at Stop.** At the Stop event the ticket is already written
and the session has already worked it, so a barred condition caught there has
already spent the dispatch it should have prevented. The whole value is in
refusing before the work starts.

**Precision was measured rather than assumed**, which is what makes refusing
defensible where the check itself only reports: a 42-ticket sweep returned
seven flags and one real finding before the detection was fixed, and one after.

A settings-file edit is not Delegated work — PPA-1758
------------------------------------------------------
Claude Code's permission check refuses a session's edit to its own repository's
``.claude/settings.json`` with the reason "Self-Modification", and the session
correctly stops. It blocked PPA-1744 and PPA-1745 on 30-SEP-2026. Ruling 1A,
01-OCT-2026: a ticket that edits that file is worked Guided. This check refuses
a Delegated ticket whose Change section names it, before a session spends a run
finding out.

The Change section is read from the description's own headings, so a ticket
that lists the file as untouched under its scope boundary is not a match, and
neither is ``~/.claude/settings.json``, the Mac's user settings. The refusal
shares the Bar's opt-out: naming the key again in prose lets it through, which
a ticket whose Change section describes this very check needs.

A done list that waits on its own merge is not Delegated work — PPA-1769
--------------------------------------------------------------------------
A delegated session posts its Jira close-out before its pull request merges,
so a Definition of Done condition that needs the change merged to main, or a
comment naming the squash-merge commit, can never be reported MET by the
session. The merge close-out workflow then holds or parks the ticket and the
conductor closes it by hand: PPA-1747 and PPA-1767 on 01-OCT-2026. pt-backlog
§ Story Creation Checklist item 6 already says such a condition is a conductor
condition; this check enforces it at dispatch.

A Delegated ticket is refused when a condition that is untagged or tagged
``[machine]`` contains "merged to main" or "squash-merge", in any case. A
condition tagged ``[conductor]`` or ``[observer]`` is not a match, a Guided or
Discovery ticket is never a match, and the phrases are read in the Definition
of Done only, never in the description. The refusal numbers each condition as
the field lists them and shares the Bar's opt-out. Other conditions a session
cannot evidence before its merge, such as a live deploy, are not addressed.

Deployed skills drift, and the session binds one copy — PPA-1470
-----------------------------------------------------------------
Amendment 2, as corrected by the conductor on 16-SEP-2026. A dispatch is only
as good as the skills the session actually loaded, and two different things
make a loaded copy stale.

* **Marketplace freshness.** The deployed copy is older than the marketplace's
  ``origin/main``. A pull has not happened.
* **Session binding.** A Claude Code session resolves one cache SHA at launch
  and holds it for the session's life. A newer SHA can arrive in the same cache
  minutes later and the running session never sees it.

The second is what was actually measured and the first amendment named it
wrongly. At 15:34 on 16-SEP-2026 ``peech-personal`` read as three commits
behind with ``autoUpdate`` true, and that looked like the key failing. Re-read
at 18:41 the clone had reached ``af2b100`` and the cache held a ``6-5-0`` copy
at ``af2b1001d7cc`` - auto-update had delivered. The session serving ``6-2-0``
at 18:46 was bound to ``352848b521a0`` from before the pull. The 15:34 reading
caught the window before the pull, not a failure of the key. PPA-1447 stands on
its own terms and is unaffected.

**What this can and cannot see.** It reads the deployed path recorded in
``~/.claude/plugins/installed_plugins.json``, never a repository working tree.
It cannot read the running session's own bound SHA - a hook is a subprocess and
is told the prompt, not which cache directory the skill loader resolved. So the
session-binding half reports the *condition that makes binding drift possible*:
a SHA newer than the installed one sitting in the same cache. Naming that limit
matters more than the check - a report that implies it has proved a specific
session stale, when it has proved a newer copy exists, is the kind of claim
PPA-1381 was opened about.

**It reports and never refuses.** A stale skill is a fact worth knowing at
dispatch, and it is not the command being wrong. Where the comparison cannot
run - no marketplace clone, no cache, no network - it says so in one line and
the dispatch proceeds.

The cache is never an authority — PPA-1427
--------------------------------------------
"Once per key per session" above is an optimisation, and it was read as a
verdict. PPA-1407 sat at Reopened through the dispatch of 13-SEP-2026 while
PPA-1416, PPA-1418 and PPA-1422 all moved on the same prompt: the conductor
had rejected it at 23:36 EDT, outside the session, and the session's cache
still listed it as settled from an earlier dispatch. Any ticket rejected and
re-dispatched into one session hits this, which is the ordinary rework loop.

So a cached key whose live status is dispatchable is transitioned anyway. The
cache is not deleted — it still exists so a repeated prompt does not re-issue
transitions — and nothing else it holds is second-guessed.

A malformed dispatch is not a silent one — PPA-1434
-----------------------------------------------------
PPA-1418 reasoned about two first lines and there are three. Pure keys and
separators is a dispatch and transitions. Prose with no keys is not a dispatch
and is silent, correctly. Keys *plus* prose is a dispatch its author meant to
write, and it was silent too — indistinguishable from the row above.

``Work PPA-1424, PPA-1425 and PPA-1426.`` failed twice on 13-SEP-2026. The
spelled-out "and" is not in the separator set and neither is the leading
"Work", so the line read as prose, nothing transitioned, and the log held no
record. Traced live against this file on 16-SEP-2026: ``dispatched_keys``
returns ``[]``.

That case now prints one warning naming the keys, the residue that
disqualified the line, and the qualifying form. It warns and does not guess at
the intent behind a malformed line.

**Two or more keys refuse — PPA-1784.** The warning was not enough. On
01-OCT-2026 the line ``PPA-1783 PPA-1776 PPA-1773 PPA-947 - run PPA-1783 first;
the weekly report waits on it`` dispatched nothing, a 13m 45s session built all
four tickets, all four stayed at To Do, and the Definition of Done gate refused
at stop because it had nothing to grade. A first line that carries two or more
distinct keys and anything beside keys and separators now exits 2 with the
warning's text plus one sentence: to ask about the tickets rather than dispatch
them, start the message with a line that carries no ticket key. Nothing is
transitioned. The log record is unchanged, reason ``malformed-dispatch`` with
the first line.

**The threshold is two because one key is ordinary conversation.** A line such
as ``PPA-1783 apply output below`` is a follow-up inside a working session, and
refusing it would block routine turns. It keeps the PPA-1434 behavior: warn and
allow. Every recorded incident carried two or more keys.

**The warning goes through ``warn()`` — PPA-1548.** It went to stderr, on the
reasoning that it describes the prompt the operator just typed rather than a
Jira failure, and PPA-1434's close-out recorded a visibility caveat against
that choice. The caveat was the defect: stderr from a hook exiting 0 reaches
the debug log only, so on 18-SEP-2026 a four-key dispatch transitioned nothing
and warned nobody. Where the warning belongs is decided by who has to read it,
not by what it is about, and ``systemMessage`` is the only path in this file
the operator sees. Both readings also write a log record now, carrying the line
that disqualified itself.
"""
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import zoneinfo
from pathlib import Path

# Path resolution for the pt-automation-hooks plugin copy (PPA-1578).
# pt_transition.py has one home, the peech-ci-workflows clone (PPA-1581), and
# is read from there in every repository (PPA-1662); a missing clone warns and
# passes - see "no-script" above. The Bar check ships in the plugin and
# resolves from the plugin's own directory. REPO is still the session's project
# root, for the repository-match check and the subprocess's working directory.
# The Bar check's own REPO and SIBLING_ROOT resolve inside the plugin, which
# misplaces only its --verify-rules CLI mode; the hook calls barred_demands()
# alone, which reads no path, so nothing observable breaks. Dropped.
REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from refresh_ci_workflows import CLONE_SCRIPTS  # noqa: E402

SCRIPT = CLONE_SCRIPTS / "pt_transition.py"
TARGET = "In Progress"
TIMEOUT = 90

#: Seconds to allow the dispatchable-set read. Deliberately short: it runs on
#: the dispatch prompt, ahead of the session, and a slow Jira must cost a
#: warning rather than a stalled dispatch.
JIRA_TIMEOUT = 10

#: The statuses a dispatchable ticket sits at, and the components that make one
#: dispatchable. Both are the definition rather than a filter over it - a
#: ticket carrying neither execution component is outside the set.
DISPATCHABLE_STATUSES = ("To Do", "Reopened")
EXECUTION_COMPONENTS = ("EXA: Delegated", "EXA: Delegated Discovery")

#: Work type by execution component - PPA-1716. Discovery is tested first, so a
#: ticket carrying both is a Discovery ticket.
WORK_TYPES = (("EXA: Delegated Discovery", "Discovery"),
              ("EXA: Delegated", "Delegated"))

#: The field a date hold is recorded in (PPA-1752), found by this name in Jira's
#: field list, and the zone "today" is read in.
TARGET_START = "Target start"
HOLD_ZONE = "America/New_York"

#: How a Discovery dispatch is launched. Medium since Decision 5B, 07-OCT-2026
#: (PPA-1931); the ``--effort high`` in Ruling 1A's docstring above is the dated
#: record of the launch it ruled on 29-SEP-2026.
DISCOVERY_LAUNCH = "claude --model opus --effort medium"

#: One JSON record per failure, appended. Outside every repository on purpose —
#: see "Every failure is also logged" above.
LOG = Path.home() / ".claude" / "pt-transition-hook.log"

#: The ticket prefixes a dispatch line may carry, defined once. The hooks that
#: match a key or a branch import these rather than spell a prefix again, so a
#: third prefix is one edit (PPA-1825: PEECHPMO is Mac Fleet's space).
TICKET_PREFIXES = ("PPA", "PEECHPMO")
PREFIX_ALT = "|".join(TICKET_PREFIXES)
#: A branch is named for its first key: ``ppa-<n>`` or ``peechpmo-<n>``.
BRANCH_PREFIXES = tuple(f"{p.lower()}-" for p in TICKET_PREFIXES)

_KEY_RE = re.compile(rf"\b(?:{PREFIX_ALT})-\d+\b", re.IGNORECASE)

#: ``pt_transition.py`` prints one line per key: ``KEY 'from' -> 'to' hops=N VERDICT``.
_VERDICT_RE = re.compile(rf"^((?:{PREFIX_ALT})-\d+)\b.*\b(PASS|NOOP|HALT)\b")

#: A HALT is deliberately absent: it means the key did not move, so it is retried.
_SETTLED = ("PASS", "NOOP")

#: What may sit between keys on a dispatch line and still leave it a dispatch.
#: Named once because two things read it: the qualifier in dispatched_keys(),
#: and the residue the PPA-1434 warning reports. A second literal would let the
#: warning describe a rule the qualifier no longer applies.
_SEPARATORS = " ,;:.&/\t"


def keys_in(prompt):
    """Every PPA key mentioned anywhere in the prompt, first-appearance order.

    This is the mentioned set, not the dispatched one. Since PPA-1418 nothing
    is transitioned on the strength of it; it answers the completeness check's
    opt-out, where naming a key in prose is exactly the intended act.
    """
    return list(dict.fromkeys(m.group(0).upper() for m in _KEY_RE.finditer(prompt)))


#: PPA-1573. Claude Code hands a pasted dispatch to this hook inside a
#: pasted_content wrapper, so the first non-blank line is the opening tag and
#: the key line sits beneath it. The pattern is deny_in_scope_spawn.py's
#: (PPA-1566), repeated rather than imported: that hook imports this one, and
#: it has no copy in either sibling this file is distributed to.
_PASTE_TAG_RE = re.compile(r"</?pasted_content[^>]*>")


def unwrapped(prompt):
    """The prompt with any pasted_content tags removed, for the three readers
    of the leading line - ``dispatched_keys``, ``first_nonblank_line`` and
    ``malformed_dispatch_warning`` - so all three see the same first line."""
    return _PASTE_TAG_RE.sub("", prompt or "")


def dispatched_keys(prompt):
    """The keys this prompt dispatches, or [] when it dispatches none.

    The sanctioned position is the first non-blank line, and it qualifies only
    when it holds nothing but PPA keys and separators. A leading line reading
    "PPA-1416, PPA-1418, PPA-1407" dispatches three; a leading line of prose
    dispatches none however many keys sit further down.

    Trailing punctuation on the line is tolerated because a conductor writing
    "PPA-1416, PPA-1418." has still written a key line. Anything else - a verb,
    a repository name, a sentence - is prose, and prose is not a dispatch.
    """
    for line in unwrapped(prompt).splitlines():
        line = line.strip()
        if not line:
            continue
        keys = keys_in(line)
        if keys and not _KEY_RE.sub("", line).strip(_SEPARATORS):
            return keys
        return []
    return []


def first_nonblank_line(prompt):
    """The line ``dispatched_keys`` read, or "" where the prompt is blank.

    PPA-1548. A record saying only that no key resolved sends the next reader
    back to the source to work out why. The line is the whole answer, so the
    record carries it, and it is located here rather than re-walked at the call
    site so the three readers of the leading line can never disagree about
    which line that is.
    """
    for line in unwrapped(prompt).splitlines():
        line = line.strip()
        if line:
            return line
    return ""


#: PPA-1784. The first line carrying this many distinct keys, and anything
#: besides keys and separators, is refused rather than warned about.
REFUSE_AT_KEYS = 2

#: What the refusal adds to the warning's text.
ASK_INSTEAD = ("To ask about these tickets rather than dispatch them, start the "
               "message with a line that carries no ticket key.")


def malformed_dispatch_warning(prompt):
    """The warning for a first line carrying keys that is not a dispatch.

    PPA-1434. ``dispatched_keys`` answers two different questions with the same
    empty list: "this was never a dispatch" and "this was meant as one and is
    malformed". The first is the deliberate quiet path and stays silent. The
    second looked identical to the person who wrote it, and on 13-SEP-2026 the
    line ``Work PPA-1424, PPA-1425 and PPA-1426.`` transitioned nothing, logged
    nothing and warned nobody twice in one evening.

    Returns None where the line qualifies, or carries no key at all. The line
    is located exactly as ``dispatched_keys`` locates it - first non-blank,
    never further down - so the two can never disagree about which line is
    under test.
    """
    for line in unwrapped(prompt).splitlines():
        line = line.strip()
        if not line:
            continue
        keys = keys_in(line)
        if not keys:
            return None          # prose with no keys: never a dispatch
        residue = _KEY_RE.sub("", line).strip(_SEPARATORS)
        if not residue:
            return None          # it qualified; dispatched_keys has it
        return (
            f"{', '.join(keys)} named on the first line, but nothing was "
            f"dispatched.\n\n"
            f"The line is read as prose because {residue!r} sits between the "
            f"keys, and a dispatch line carries nothing but keys and the "
            f"separators {_SEPARATORS.strip()!r}.\n\n"
            f"To dispatch these, make the first line: {', '.join(keys)}"
        )
    return None


#: A ``REPO:`` component value, as Jira stores it.
_REPO_COMPONENT_RE = re.compile(r"^REPO:\s*\S+")


def dispatched_fields(keys, timeout=JIRA_TIMEOUT):
    """{key: fields} for the dispatched keys - the one read every check shares.

    PPA-1465. Three checks now want the dispatched tickets: the repository
    match, the completeness comparison and the Ticket Quality Bar. All three
    want the same issues and between them the same fields, and each used to ask
    Jira for them separately - three searches on the prompt that starts a
    session. This is that read, performed once and handed down.

    One search rather than one read per key, unchanged. A key Jira does not
    return at all is absent from the mapping; every caller treats an absent key
    as unreadable rather than as answering, because "no answer" and "a bad
    ticket" are different things and only the second should refuse.
    """
    query = urllib.parse.urlencode({
        "jql": f"key in ({', '.join(keys)})",
        "fields": "status,components,description,customfield_10767",
        "maxResults": 100,
    })
    data = _jira_get(f"/search/jql?{query}", timeout)
    found = {}
    for issue in data.get("issues") or []:
        fields = issue["fields"]
        names = [c.get("name", "") for c in fields.get("components") or []]
        found[issue["key"].upper()] = {
            "status": (fields.get("status") or {}).get("name", ""),
            "components": names,
            "repo_components": [n for n in names if _REPO_COMPONENT_RE.match(n)],
            "description": " ".join(flatten_adf(fields.get("description"))),
            "dod": " ".join(flatten_adf(fields.get("customfield_10767"))),
            # The same field unflattened, since PPA-1520. The barred-artifact
            # item reports per condition and the flattened string above has
            # lost the boundaries between them; no second Jira call is made.
            "dod_adf": fields.get("customfield_10767"),
            # The description unflattened, since PPA-1758: the Change section
            # is found by its heading, which flattening loses.
            "description_adf": fields.get("description"),
        }
    return found


def read_dispatched(keys, timeout=JIRA_TIMEOUT):
    """(fields, error) for the shared read. Never raises.

    The error rides out rather than being warned about here, because which
    warning is owed depends on which check went without - and each of them
    still owns its own warn-and-allow. A caller handed ``None`` falls back to
    reading for itself, which costs the round trips this exists to save but
    keeps every failure path behaving exactly as it did before PPA-1465.
    """
    try:
        return dispatched_fields(keys, timeout), None
    except Exception as exc:  # noqa: BLE001 - every read failure warns and allows
        return None, exc


def repo_components_of(keys, fields=None, timeout=JIRA_TIMEOUT):
    """{key: "REPO: name" or None} for the dispatched keys.

    Derived from the shared read when it is supplied, and read for itself when
    it is not. A key Jira does not return at all maps to None, the same answer
    a key carrying no ``REPO:`` component gets: the check declines to guess
    which backlog it belongs to.
    """
    found = dispatched_fields(keys, timeout) if fields is None else fields
    return {k: next(iter(found.get(k, {}).get("repo_components") or []), None)
            for k in keys}


def repo_name_of(component):
    """``REPO: peech-skills`` -> ``peech-skills``. None passes through."""
    return component.split(":", 1)[1].strip() if component else None


def session_repository(project_dir=None):
    """The repository this session is rooted in, or None if it cannot be read.

    ``CLAUDE_PROJECT_DIR`` is what Claude Code sets to the session's root, and
    its last path segment is the repository name - the same name the ``REPO:``
    component carries, because every checkout in the estate is cloned under its
    own name. A variable that is unset, empty or unreadable answers None, and
    every caller turns that into a warn-and-allow.
    """
    root = project_dir if project_dir is not None else os.environ.get(
        "CLAUDE_PROJECT_DIR")
    if not root:
        return None
    try:
        return Path(root).resolve().name or None
    except (OSError, ValueError):
        return None


def repository_mismatches(mapping, session_repo):
    """[(key, its repository)] for every dispatched key rooted elsewhere.

    A key carrying no ``REPO:`` component is not a mismatch. It is already
    reported by the completeness check, and a ticket with no repository has not
    cleared the Ticket Quality Bar - refusing it here would be a second answer
    to a question that already has one.
    """
    return [(key, repo_name_of(component))
            for key, component in mapping.items()
            if component and repo_name_of(component) != session_repo]


def mismatch_block_message(mismatches, session_repo):
    """What the conductor reads when a dispatch landed in the wrong window.

    It names each key, the repository its component names and this session's
    own, so the paste can be redirected without opening PPA-1465.
    """
    lines = "\n".join(f"  {key} belongs to {repo}" for key, repo in mismatches)
    return (
        f"Dispatch is for another repository.\n\n"
        f"This session is rooted in {session_repo}.\n\n"
        f"{lines}\n\n"
        "One commit reaches one remote, so a session cannot ship a ticket to a "
        "repository it is not in. Paste this dispatch into the session rooted "
        "in that repository instead.\n\n"
        "There is no opt-out. Naming the key again in the prompt clears a "
        "completeness refusal and a Bar refusal; it does not clear this one, "
        "because no dispatch into the wrong working tree is correct."
    )


def check_repository_match(keys, fields=None, session_repo=None):
    """The block message when this dispatch is for another repository, else None.

    PPA-1465. PPA-1460 pinned the Code Terminal label to carry the repository
    name, which makes the target visible; it cannot refuse a paste into the
    wrong window, and a conductor writing the label correctly does not stop the
    paste landing elsewhere. This is the refusal.

    Every failure warns and allows, exactly as the two checks below do: an
    unreadable session root, absent credentials, a Jira error, a timeout, a key
    Jira does not return, a key carrying no ``REPO:`` component. A block fires
    only on a positive answer - this key belongs to that repository, and this
    session is in a different one.
    """
    if session_repo is None:
        session_repo = session_repository()
    if not session_repo:
        log("session-repository-unreadable", keys)
        warn("repository match not checked - CLAUDE_PROJECT_DIR is unset or "
             "unreadable, so this session's own repository is unknown.")
        return None

    try:
        mapping = repo_components_of(keys, fields=fields)
    except Exception as exc:  # noqa: BLE001 - every read failure warns and allows
        log("repo-match-read-failed", keys, error=repr(exc))
        warn(f"repository match not checked - {exc}")
        return None

    # A dispatch spanning two repositories is the command being wrong in its
    # own right, whichever window it lands in, and the completeness check owns
    # that message. Deferring here keeps that refusal reachable and keeps this
    # one to what it is for: a well-formed dispatch pasted into the wrong
    # session. PPA-1465 adds a refusal where nothing fired before; it does not
    # take one over.
    if scope_of(mapping).blocked:
        return None

    mismatches = repository_mismatches(mapping, session_repo)
    if not mismatches:
        return None

    log("dispatch-for-another-repository", [k for k, _ in mismatches],
        session_repository=session_repo)
    return mismatch_block_message(mismatches, session_repo)


class DispatchScope:
    """What repository a dispatch is for, or why that cannot be answered.

    ``component`` is the one repository to measure against, or None. ``blocked``
    carries a message when the scope itself is the defect - today a dispatch
    spanning two remotes and nothing else. ``unscoped`` lists keys carrying no
    ``REPO:`` component, reported and never silently dropped.
    """

    def __init__(self, component=None, blocked=None, unscoped=()):
        self.component = component
        self.blocked = blocked
        self.unscoped = list(unscoped)


def scope_of(mapping):
    """Resolve the dispatch's repository from its keys' own components."""
    unscoped = [k for k, v in mapping.items() if not v]
    named = sorted({v for v in mapping.values() if v})
    if len(named) > 1:
        return DispatchScope(blocked=(
            "Dispatch spans two repositories.\n\n"
            f"The keys on the dispatch line carry: {', '.join(named)}\n\n"
            "One commit cannot span two remotes, and a Delegated ticket carries "
            "exactly one REPO: component. Split this into one dispatch per "
            "repository. No completeness check ran, because there is no single "
            "backlog to measure against and this hook does not pick one."
        ), unscoped=unscoped)
    if not named:
        return DispatchScope(unscoped=unscoped)
    return DispatchScope(component=named[0], unscoped=unscoped)


def work_type_of(components):
    """``Discovery``, ``Delegated``, or None for a ticket with neither."""
    return next((kind for name, kind in WORK_TYPES if name in components), None)


def work_types_of(keys, fields=None, timeout=JIRA_TIMEOUT):
    """{work type: [keys]} for the dispatched keys, in dispatch order.

    Derived from the shared read when it is supplied, and read for itself when
    it is not, as ``repo_components_of`` is. A key Jira does not return, or one
    carrying no execution component, is in no type: it is the Bar check's to
    refuse, and it must not decide which backlog the rest is measured against.
    """
    found = dispatched_fields(keys, timeout) if fields is None else fields
    by_type = {}
    for key in keys:
        kind = work_type_of(found.get(key, {}).get("components") or [])
        if kind:
            by_type.setdefault(kind, []).append(key)
    return by_type


def dispatchable_jql(component, work_type=None):
    """The dispatchable set, narrowed to one work type where one is named.

    Discovery is the more specific component, so the Delegated set excludes a
    ticket that also carries it - the same tie ``work_type_of`` breaks.
    """
    quoted = ", ".join(f'"{c}"' for c in DISPATCHABLE_STATUSES)
    if work_type is None:
        execution = ", ".join(f'"{c}"' for c in EXECUTION_COMPONENTS)
        typed = f"component in ({execution})"
    else:
        names = [name for name, kind in WORK_TYPES if kind == work_type]
        typed = f'component = "{names[0]}"'
        if work_type == "Delegated":
            typed += f' AND component != "{WORK_TYPES[0][0]}"'
    return (f"project = PPA AND status in ({quoted}) AND {typed} "
            f'AND component = "{component}"')


#: The PEECHPMO half of CLAUDE.md Jamf routing rule 7 (PPA-1829). PEECHPMO
#: has its own copy of the Delegated component, and the Jamf tickets are
#: found by JAMF. The rule asks for statusCategory != Done rather than the
#: PPA statuses, so an In Progress Mac Fleet ticket is still demanded.
JAMF_COMPONENT = "JAMF"
PEECHPMO_DELEGATED = "EXA: Delegated"


def peechpmo_dispatchable_jql():
    """The Mac Fleet dispatchable set. No repository filter applies: not every
    PEECHPMO ticket carries a ``REPO:`` component, and the rule names none."""
    return (f'project = PEECHPMO AND component = "{JAMF_COMPONENT}" '
            f'AND component = "{PEECHPMO_DELEGATED}" '
            "AND statusCategory != Done")


def peechpmo_dispatchable_set(timeout=JIRA_TIMEOUT):
    """Every open dispatchable PEECHPMO key, read live from Jira. Raises."""
    query = urllib.parse.urlencode(
        {"jql": peechpmo_dispatchable_jql(), "fields": "key", "maxResults": 100})
    data = _jira_get(f"/search/jql?{query}", timeout)
    return [issue["key"].upper() for issue in data.get("issues") or []]


#: A blocker that has landed. Anything else still holds the ticket it blocks.
#: Read as names rather than IDs, per the repository's own rule against acting
#: on a remembered transition or status ID.
RESOLVED_STATUSES = ("Done", "Closed")


def unresolved_blockers(issue):
    """The keys of every unresolved issue this one is blocked by.

    pt-backlog holds that a readiness dependency is a Jira blocking link rather
    than a line of prose, so the link is the machine-readable statement of
    exactly this and the check can read it.

    The link type is matched on its ``inward`` description rather than its ID.
    ``is blocked by`` is the direction that gates this issue; the outward
    ``blocks`` direction points at issues waiting on it and never holds it up.
    """
    out = []
    for link in issue.get("fields", {}).get("issuelinks") or []:
        blocker = link.get("inwardIssue")
        if not blocker or (link.get("type") or {}).get("inward") != "is blocked by":
            continue
        status = ((blocker.get("fields") or {}).get("status") or {}).get("name", "")
        if status not in RESOLVED_STATUSES:
            out.append(blocker["key"].upper())
    return out


def target_start_field(timeout=JIRA_TIMEOUT):
    """The identifier of the field named ``TARGET_START``, from Jira's field list.

    PPA-1752. Read rather than written into the code: Jira assigns a custom
    field's identifier per site. Raises where the read fails or no field has the
    name, which the completeness check turns into its usual warn-and-allow.

    Dropped (PPA-1752): this is a third Jira read per dispatch, beside the two
    searches. What breaks if it is never fixed: one extra GET on the prompt that
    starts a session, inside ``JIRA_TIMEOUT``, and nothing observable beyond
    that. Caching the identifier across dispatches would trade it for a stale
    one when the field is renamed or recreated.
    """
    data = _jira_get("/field", timeout)
    for field in data if isinstance(data, list) else []:
        if field.get("name") == TARGET_START:
            return field["id"]
    raise LookupError(f"Jira's field list has no field named {TARGET_START!r}")


def held_until(issue, field, today):
    """The date a ticket is held until, or None where it is dispatchable today.

    A blank Target start, and one of today or earlier, hold nothing.
    """
    value = (issue.get("fields") or {}).get(field)
    if not value:
        return None
    start = datetime.date.fromisoformat(str(value)[:10])
    return start if start > today else None


def dispatchable_set(component, excluded=None, unreadable=None,
                     timeout=JIRA_TIMEOUT, work_type=None, held=None,
                     today=None):
    """Every open dispatchable key for this repository, read live from Jira.

    PPA-1716. ``work_type`` narrows the set to Discovery or Delegated tickets;
    None returns both, which is what ``--dispatch-set`` lists.

    A ticket whose blocking link is still open is not in the set - PPA-1465.
    The set is what the completeness check demands, and a blocked ticket was
    demanded on every dispatch for its repository with an opt-out as the only
    way past it. Measured 16-SEP-2026: a dispatch of PPA-1467 was refused for
    omitting PPA-1464, which was blocked by PPA-1456 on an unmerged pull
    request. That is an opt-out spent on a ticket nobody could have dispatched.

    ``excluded`` is a list the caller passes in to collect ``(key, blockers)``
    for each ticket dropped this way. It is an out-parameter rather than a
    second return value so that every existing caller and every test double
    keeps working against a plain list of keys. A check that quietly shrinks
    its own population is worse than one that asks too much, so the caller
    reports what came back in it.

    ``unreadable`` is the same shape for the other direction: ``(key, error)``
    for each row whose links could not be read. Such a row stays in the set,
    which asks too much rather than going quiet, but staying in the set with
    nothing on the record is going quiet about the read itself. The caller
    logs and warns on what came back in it, on the same footing as every other
    failure path here.

    ``held`` is the same out-parameter again, PPA-1752: ``(key, date)`` for each
    ticket whose Target start is later than ``today``, which defaults to today
    in ``HOLD_ZONE``. A held ticket is outside the set. A ticket both blocked
    and held is reported as blocked.

    Raises on any failure. The caller turns that into a warn-and-allow, which
    is the whole of this check's failure policy - see the docstring.

    ``pt_transition.load_credentials`` supplies the credentials, so this file
    still holds no path of its own and there is still one credential home. The
    request is built here rather than through ``make_client`` for one reason:
    that client's getter takes no timeout, and a check running ahead of every
    dispatch cannot wait on a hung socket for as long as the default allows.
    """
    start_field = target_start_field(timeout)
    if today is None:
        today = datetime.datetime.now(zoneinfo.ZoneInfo(HOLD_ZONE)).date()
    query = urllib.parse.urlencode(
        {"jql": dispatchable_jql(component, work_type),
         "fields": f"issuelinks,{start_field}", "maxResults": 100})
    data = _jira_get(f"/search/jql?{query}", timeout)

    keys = []
    for issue in data.get("issues") or []:
        key = issue["key"].upper()
        try:
            blockers = unresolved_blockers(issue)
        except Exception as exc:  # noqa: BLE001 - an unreadable link graph excludes nothing
            blockers = []
            if unreadable is not None:
                unreadable.append((key, repr(exc)))
        if blockers:
            if excluded is not None:
                excluded.append((key, blockers))
            continue
        until = held_until(issue, start_field, today)
        if until:
            if held is not None:
                held.append((key, until))
            continue
        keys.append(key)
    return keys


def held_warning(held):
    """What the conductor reads when a ticket is dropped for its start date."""
    lines = "; ".join(f"{key} (held until {until})" for key, until in held)
    return (f"Not demanded by the completeness check, because its {TARGET_START} "
            f"is later than today: {lines}")


def excluded_warning(excluded):
    """What the conductor reads when a blocked ticket is dropped from the set."""
    lines = "; ".join(f"{key} (blocked by {', '.join(blockers)})"
                      for key, blockers in excluded)
    return (f"Not demanded by the completeness check, because a blocking link "
            f"is still open: {lines}")


def unreadable_warning(unreadable):
    """What the conductor reads when a row's blocking links could not be read."""
    lines = "; ".join(f"{key} ({error})" for key, error in unreadable)
    return (f"Blocking links could not be read, so these are still demanded by "
            f"the completeness check and may be blocked: {lines}")


def _jira_get(path, timeout=JIRA_TIMEOUT):
    """One authenticated GET. Raises on any failure; the caller warns and allows.

    ``pt_transition.load_credentials`` supplies the credentials, so this file
    still holds no path of its own and there is still one credential home.
    """
    sys.path.insert(0, str(CLONE_SCRIPTS))
    from pt_transition import BASE, load_credentials  # noqa: PLC0415

    creds = load_credentials()
    auth = base64.b64encode(
        f"{creds['JIRA_EMAIL']}:{creds['JIRA_API_TOKEN']}".encode()).decode()
    request = urllib.request.Request(
        f"{BASE}{path}",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read())


def missing_from(dispatchable, mentioned):
    """Dispatchable keys this prompt names nowhere. Case-insensitive."""
    named = {k.upper() for k in mentioned}
    return [k for k in dispatchable if k.upper() not in named]


def block_message(missing, component, work_type=None):
    """What the conductor reads instead of the session starting.

    It names the missing keys and the opt-out, so the block can be acted on
    without opening PPA-1418. Where the set was measured by work type it says
    so, because the other type's keys are deliberately not in it.
    """
    scope = f"{component}, {work_type} tickets" if work_type else component
    return (
        f"Dispatch is incomplete for {scope}.\n\n"
        f"Open and dispatchable, but named nowhere in this prompt: "
        f"{', '.join(missing)}\n\n"
        "A dispatch carries every dispatchable ticket for its repository. "
        "Either add the missing keys to the dispatch, or name each one in the "
        "prompt and say why it is being left - naming a key anywhere in the "
        "text is the opt-out and lets this through without dispatching it."
    )


def barred_artifacts(fields):
    """Every barred artifact this ticket's Definition of Done demands.

    The check is ``scripts/check_dod_barred_artifacts.py``. Where this import
    finds nothing the item declines to run, which is the same warn-and-allow
    every other unreachable check here takes.

    The two failures are caught separately for the same reason they are there.
    A check that is not present is the siblings' ordinary state and says
    nothing. A check that is present and will not import has silently disabled
    a Bar item, which is the degrade every other failure path here records.

    The condition text is read from the raw ADF rather than from the flattened
    ``dod`` string beside it, because the check reports per condition and
    flattening the field loses the boundaries between them.
    """
    sys.path.insert(0, str(PLUGIN / "scripts"))
    try:
        from check_dod_barred_artifacts import barred_demands  # noqa: PLC0415
    except ModuleNotFoundError:
        return []
    except Exception as exc:  # noqa: BLE001 - a check that will not import
        log("barred-artifact-check-unreadable", [], error=repr(exc))
        warn(f"barred-artifact Bar item not checked - the check would not "
             f"import: {exc}")
        return []
    try:
        flags = barred_demands("", fields.get("dod_adf"))
    except Exception as exc:  # noqa: BLE001 - every read failure warns, allows
        log("barred-artifact-check-failed", [], error=repr(exc))
        warn(f"barred-artifact Bar item not checked - {exc}")
        return []
    return sorted({flag.bar.artifact for flag in flags})


def _no_barred_artifact(fields):
    """The Bar item's test: the Definition of Done demands nothing barred."""
    return not barred_artifacts(fields)


def _barred_artifact_label(fields):
    """The Bar item's label, naming the bar the ticket actually hit.

    A callable rather than a fixed string because this is the one item whose
    failure does not say the same thing every time: which bar was tripped is
    the part the conductor acts on, and a label reading "a Definition of Done
    free of barred artifacts" sends them to the check to find out which.
    """
    return ("a Definition of Done clear of barred artifacts - it demands "
            + "; ".join(barred_artifacts(fields)))


#: The mechanical half of pt-backlog's Ticket Quality Bar - the items a script
#: can read off Jira. Each is (label, predicate over the issue's fields).
#:
#: The other two Bar items are deliberately absent, and their absence is the
#: design rather than a gap: whether a ticket is self-contained, and the
#: ticket-internal contradiction check, both need judgement this hook cannot
#: supply. A heuristic standing in for either would refuse good tickets and
#: pass bad ones while reading as enforcement. They stay with the conductor.
#:
#: A 'Skills to load and apply:' line is no longer an item. Ruling 1A (PPA-1659
#: comment 30108) has skills load on their own descriptions, so a ticket
#: carries the line only when it needs a skill that would not trigger, and its
#: absence says nothing about the ticket (PPA-1684).
BAR_ITEMS = (
    ("exactly one REPO component",
     lambda f: len(f["repo_components"]) == 1),
    ("an execution component",
     lambda f: bool(set(f["components"]) & set(EXECUTION_COMPONENTS))),
    ("a scope boundary",
     lambda f: any(m in f["description"].lower() for m in SCOPE_MARKERS)),
    ("a non-empty Definition of Done",
     lambda f: bool(f["dod"].strip())),
    (_barred_artifact_label, _no_barred_artifact),
)

#: How a scope boundary is written in practice, lower-cased. Read off the four
#: tickets live on 16-SEP-2026 rather than invented: PPA-1452 heads a section
#: "Scope boundary" and PPA-1433 heads one "Out of scope", while PPA-1427 spends
#: its boundary on "Does not edit ..." sentences. Matching the section heading
#: alone would refuse the third.
SCOPE_MARKERS = (
    "scope boundary", "out of scope", "not in scope", "does not touch",
    "does not edit", "does not change", "not touched", "and nothing else",
    "do not touch", "do not edit", "class exclusion", "files not touched",
)


def flatten_adf(node, out=None):
    """Every text run in an Atlassian Document Format value, space-joined.

    The REST v3 API returns description and customfield_10767 as ADF, so a
    substring test needs the text pulled out of the node tree first. Shape
    errors are not defended against here: the caller treats any exception as a
    read failure and warns, which is the same answer a malformed document
    deserves.
    """
    out = [] if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            out.append(node["text"])
        for child in node.get("content") or []:
            flatten_adf(child, out)
    elif isinstance(node, list):
        for child in node:
            flatten_adf(child, out)
    return out


def bar_fields_of(keys, fields=None, timeout=JIRA_TIMEOUT):
    """{key: fields} for the dispatched keys - status, components, text.

    This was a second read until PPA-1465, on PPA-1427's reasoning that its
    scope boundary left the repository derivation alone. That boundary is now
    spent: a third check wanted the same issues, and three searches on the
    prompt that starts a session is two more than the data needs. The read
    moved to ``dispatched_fields`` and this reads it or falls back to reading
    for itself.

    A key Jira does not return is absent from the mapping. The caller treats an
    absent key as unreadable rather than as failing, because "no answer" and
    "a bad ticket" are different things and only the second should refuse.
    """
    return dispatched_fields(keys, timeout) if fields is None else fields


def bar_failures(fields):
    """The labels of every mechanical Bar item this ticket fails.

    A label is a plain string for the four items whose failure says the same
    thing every time. The barred-artifact item's does not - which bar a
    Definition of Done tripped is the part the conductor acts on - so its label
    is a callable that reads the ticket and names it.
    """
    return [label(fields) if callable(label) else label
            for label, passes in BAR_ITEMS if not passes(fields)]


def mentioned_beyond_dispatch_line(prompt):
    """Keys named somewhere other than the first non-blank line.

    This is the Bar's opt-out and it is the completeness check's opt-out read
    from the other side. There, a key the dispatch omits is waved through by
    naming it in prose. Here, a key the dispatch carries is waved through the
    same way - the conductor writes it a second time, in prose, to say the
    refusal has been seen and the dispatch goes ahead regardless. A mention on
    the dispatch line cannot be the opt-out, because that is the mention that
    put the key in scope.
    """
    lines = (prompt or "").splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            return set(keys_in("\n".join(lines[index + 1:])))
    return set()


def bar_block_message(failures):
    """What the conductor reads when a dispatched ticket fails the Bar.

    Names each failing key and the items it failed, so the refusal can be acted
    on without opening PPA-1427, and names no ticket key of its own.
    """
    lines = "\n".join(f"  {key} - missing {', '.join(items)}"
                      for key, items in failures.items())
    return (
        "Dispatch carries a ticket that fails the Ticket Quality Bar.\n\n"
        f"{lines}\n\n"
        "pt-backlog runs the Bar when the EXA: Delegated component is applied, "
        "and a ticket that never cleared it is not ready to build from. Either "
        "correct the ticket, or name the key again in the prompt text below "
        "the dispatch line - a second mention is the opt-out and lets this "
        "through."
    )


#: PPA-1758. The repository's own settings file; the home-folder copy is the
#: Mac's user settings and is told apart by what stands in front of the match.
_SETTINGS_RE = re.compile(r"([^\s`'\"(]*)\.claude/settings\.json")
_HOME_PREFIXES = ("~/", "$HOME/", "${HOME}/", "/Users/", "/home/")
_CHANGE_HEADING_RE = re.compile(r"^(the )?changes?\b")

#: What the refusal says after the key: the file and the route.
SETTINGS_ROUTE = (
    "edits .claude/settings.json - work this ticket Guided: chat writes a Run "
    "Terminal script, the operator runs it (Decision 1A, 01-OCT-2026)")


# Dropped (PPA-1758): ``--dispatch-set`` does not run the settings check, so it
# lists a Delegated ticket that edits the file as PASS. What breaks if it is
# never fixed: a dispatch composed from that listing is refused once, with the
# Guided route in the message, and costs one prompt.


def change_section(description):
    """The text under the description's Change heading, from its ADF.

    The section runs to the next heading of the same or a higher level. A
    description with no such heading has no Change section, and nothing in it
    is read: a ticket cannot be told to edit the file by a section it lacks.
    """
    text, level = [], None
    for node in (description or {}).get("content") or []:
        if node.get("type") == "heading":
            depth = (node.get("attrs") or {}).get("level", 1)
            if level is not None and depth <= level:
                break
            title = " ".join(flatten_adf(node)).strip().lower()
            if level is None and _CHANGE_HEADING_RE.match(title):
                level = depth
        elif level is not None:
            flatten_adf(node, text)
    return " ".join(text)


def edits_repo_settings(fields):
    """True for a Delegated ticket whose Change section names a repository's
    ``.claude/settings.json``. A Guided ticket is never a match."""
    if work_type_of(fields["components"]) != "Delegated":
        return False
    return any(not match.group(1).startswith(_HOME_PREFIXES)
               for match in _SETTINGS_RE.finditer(
                   change_section(fields.get("description_adf"))))


def settings_block_message(keys):
    lines = "\n".join(f"  {key} {SETTINGS_ROUTE}" for key in keys)
    return (
        "Dispatch carries a Delegated ticket that Claude Code's permission "
        "check will refuse.\n\n"
        f"{lines}\n\n"
        "The check refuses a session's edit to its own repository's "
        ".claude/settings.json (reason \"Self-Modification\"), so the session "
        "would stop and ship nothing. Move the ticket to Guided, or name the key "
        "again in the prompt text below the dispatch line - a second mention is "
        "the opt-out and lets this through."
    )


#: PPA-1769. The two phrases a delegated session cannot evidence, because its
#: close-out is posted before the merge.
_MERGE_WAIT_RE = re.compile(r"merged to main|squash-merge", re.IGNORECASE)
_EXEMPT_CLASS_RE = re.compile(r"^\[(conductor|observer)\]", re.IGNORECASE)

MERGE_WAIT_FIX = ("a delegated session posts its close-out before the merge and "
                  "cannot prove one - reword the condition to evidence on the "
                  "ticket's own commit, or tag it [conductor]")


def merge_wait_conditions(fields):
    """[(number, text)] of the conditions in a Delegated ticket's Definition of
    Done that wait on their own merge. A Guided ticket is never a match.

    Numbered as the field lists them, from 1. A condition tagged ``[conductor]``
    or ``[observer]`` is exempt; an untagged one and a ``[machine]`` one are not.
    """
    if work_type_of(fields["components"]) != "Delegated":
        return []
    # Imported here, as barred_artifacts() does: the Bar's check ships beside
    # this file, and a copy without it must warn and allow rather than raise.
    sys.path.insert(0, str(PLUGIN / "scripts"))
    try:
        from check_dod_barred_artifacts import conditions_from_adf  # noqa: PLC0415
        conditions = conditions_from_adf(fields.get("dod_adf"))
    except Exception as exc:  # noqa: BLE001 - every read failure warns, allows
        log("merge-wait-check-failed", [], error=repr(exc))
        warn(f"merge-wait check not run - {exc}")
        return []
    return [(number, text) for number, text in enumerate(conditions, start=1)
            if _MERGE_WAIT_RE.search(text) and not _EXEMPT_CLASS_RE.match(text)]


def merge_wait_block_message(waiting):
    lines = "\n".join(f"  {key} condition {number}: {text}"
                      for key, found in waiting.items() for number, text in found)
    return (
        "Dispatch carries a Delegated ticket whose Definition of Done waits on "
        "its own merge.\n\n"
        f"{lines}\n\n"
        f"{MERGE_WAIT_FIX}. Or name the key again in the prompt text below the "
        "dispatch line - a second mention is the opt-out and lets this through."
    )


def check_quality_bar(prompt, keys, shared=None):
    """(block message or None, {key: live status}) for the dispatched keys.

    ``shared`` is the read from PPA-1465, or None to read for itself.

    The statuses ride out of here because they were read anyway, and the
    settled-key cache below needs them - see "The cache is never an authority".

    A read failure returns (None, {}): warn and allow, exactly as the
    completeness check does, because a dispatch must not depend on Jira being
    up.
    """
    try:
        fields = bar_fields_of(keys, fields=shared)
    except Exception as exc:  # noqa: BLE001 - every read failure warns and allows
        log("bar-read-failed", keys, error=repr(exc))
        warn(f"Ticket Quality Bar not checked - {exc}")
        return None, {}

    waived = mentioned_beyond_dispatch_line(prompt)
    failures = {}
    for key in keys:
        if key in waived or key not in fields:
            continue
        missing = bar_failures(fields[key])
        if missing:
            failures[key] = missing

    guarded = [key for key in keys
               if key not in waived and key in fields
               and edits_repo_settings(fields[key])]

    waiting = {key: found for key in keys
               if key not in waived and key in fields
               and (found := merge_wait_conditions(fields[key]))}

    statuses = {k: v["status"] for k, v in fields.items()}
    if not failures and not guarded and not waiting:
        return None, statuses

    messages = []
    if failures:
        log("bar-failed", list(failures), failures=failures)
        messages.append(bar_block_message(failures))
    if guarded:
        log("settings-edit-refused", guarded)
        messages.append(settings_block_message(guarded))
    if waiting:
        log("merge-wait-refused", list(waiting),
            conditions={key: [number for number, _ in found]
                        for key, found in waiting.items()})
        messages.append(merge_wait_block_message(waiting))
    return "\n\n".join(messages), statuses


# --------------------------------------------------------------------------
# Deployed skill drift — PPA-1470 Amendment 2, as corrected
# --------------------------------------------------------------------------

#: Where Claude Code puts what it loads. Outside every repository, which is the
#: point: this reads the deployed copy, never a working tree.
PLUGINS = Path.home() / ".claude" / "plugins"

#: Seconds to allow each git read of the marketplace clone. Short for the same
#: reason JIRA_TIMEOUT is: this runs ahead of the session, and a slow disk must
#: cost a note rather than a stalled dispatch.
SKILL_TIMEOUT = 10

#: ``*Version 6-5-0 • 16-SEP-2026*`` — the header every pt-* skill carries.
_VERSION_RE = re.compile(r"\*Version\s+([0-9][0-9-]*)\s")


def installed_plugins(root=None):
    """[(marketplace, plugin, Path)] as installed_plugins.json records them.

    The install path is what a session loads from. Reading it here rather than
    globbing the cache is deliberate: the cache holds every SHA ever pulled,
    and only one of them is deployed.
    """
    root = PLUGINS if root is None else root
    try:
        data = json.loads((root / "installed_plugins.json").read_text())
    except (OSError, ValueError) as exc:
        # Distinct from no file at all, which skill_drift() already notes. Here
        # the record is the only thing separating "nothing is installed" from
        # "the file that says what is installed could not be read".
        log("plugins-unreadable", [], root=str(root), error=repr(exc))
        return []
    out = []
    for name, entries in (data.get("plugins") or {}).items():
        plugin, _, marketplace = name.partition("@")
        for entry in entries:
            path = entry.get("installPath")
            if path:
                out.append((marketplace, plugin, Path(path)))
    return out


def version_in(path):
    """The version header in a SKILL.md, or None where there is not one."""
    try:
        match = _VERSION_RE.search(path.read_text())
    except OSError as exc:
        # None here drops the skill out of the comparison entirely, so without
        # this record a skill silently stops being compared.
        log("skill-version-unreadable", [], path=str(path), error=repr(exc))
        return None
    return match.group(1) if match else None


def deployed_skill_versions(install_path):
    """{skill: version} for every skill under one deployed plugin copy."""
    skills = install_path / "skills"
    if not skills.is_dir():
        return {}
    return {d.name: version_in(d / "SKILL.md")
            for d in sorted(skills.iterdir()) if (d / "SKILL.md").is_file()}


def marketplace_skill_versions(marketplace, root=None):
    """{skill: version} on that marketplace's origin/main, or {} .

    Reads the clone Claude Code already keeps, and reads ``origin/main``
    through git rather than the working tree, so a dirty clone cannot report a
    version nobody is served.
    """
    root = PLUGINS if root is None else root
    clone = root / "marketplaces" / marketplace
    if not (clone / ".git").exists():
        return {}
    try:
        listing = subprocess.run(
            ["git", "-C", str(clone), "ls-tree", "-r", "origin/main", "skills/"],
            capture_output=True, text=True, timeout=SKILL_TIMEOUT, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        # The clone is here and git would not read it, which is not the absent
        # clone skill_drift() notes. Recorded so the note is not the only trace.
        log("marketplace-read-failed", [], marketplace=marketplace,
            step="ls-tree", error=repr(exc))
        return {}

    # blob SHA -> skill name, for the SKILL.md files only. One batch read
    # below rather than a `git show` per skill: this runs on every dispatch
    # prompt, and twenty-odd subprocesses is a visible pause on a hook.
    blobs = {}
    for line in listing.stdout.splitlines():
        meta, _, path = line.partition("\t")
        if not path.endswith("/SKILL.md"):
            continue
        parts = meta.split()
        if len(parts) >= 3:
            blobs[parts[2]] = Path(path).parent.name
    if not blobs:
        return {}

    try:
        batch = subprocess.run(
            ["git", "-C", str(clone), "cat-file", "--batch"],
            input="\n".join(blobs) + "\n",
            capture_output=True, text=True, timeout=SKILL_TIMEOUT, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        log("marketplace-read-failed", [], marketplace=marketplace,
            step="cat-file", error=repr(exc))
        return {}

    # `--batch` emits "<sha> blob <size>\n<contents>\n" per request, in the
    # order asked. Splitting on the header keeps it one pass over the stream.
    versions = {}
    for chunk in re.split(r"^([0-9a-f]{40}) blob \d+$", batch.stdout,
                          flags=re.M)[1:]:
        if chunk in blobs:
            current = blobs[chunk]
            continue
        match = _VERSION_RE.search(chunk)
        if match:
            versions[current] = match.group(1)
    return versions


def newer_cache_copies(install_path):
    """Sibling SHA directories in the same cache newer than the deployed one.

    This is the session-binding half, and it is the condition rather than the
    proof - see the docstring. A SHA newer than the installed one means a
    session launched before it arrived is still serving the older copy, and
    nothing here can tell which session that is.
    """
    parent = install_path.parent
    if not parent.is_dir():
        return []
    try:
        deployed_at = install_path.stat().st_mtime
    except OSError as exc:
        # The session-binding half reports nothing from here on, and nothing is
        # also what it reports when there is no newer copy. Only this tells
        # the two apart.
        log("cache-copies-unreadable", [], path=str(install_path),
            error=repr(exc))
        return []
    return sorted(
        d for d in parent.iterdir()
        if d.is_dir() and d != install_path and not d.name.endswith(".bak")
        and d.stat().st_mtime > deployed_at)


def skill_drift(root=None):
    """Lines naming every stale deployed skill, both versions on each.

    Returns ([finding, ...], [note, ...]). A note says the comparison could not
    run; it is never a finding, because an absent clone is not drift.
    """
    root = PLUGINS if root is None else root
    findings, notes = [], []

    plugins = installed_plugins(root)
    if not plugins:
        return [], ["no deployed plugin is recorded, so no skill was compared."]

    for marketplace, plugin, install_path in plugins:
        deployed = deployed_skill_versions(install_path)
        if not deployed:
            notes.append(f"{plugin}: nothing deployed at {install_path}, so "
                         f"no skill was compared.")
            continue

        upstream = marketplace_skill_versions(marketplace, root)
        if not upstream:
            notes.append(f"{marketplace}: no marketplace clone to read "
                         f"origin/main from, so freshness was not compared.")
        for skill, version in sorted(deployed.items()):
            want = upstream.get(skill)
            if want and version and want != version:
                findings.append(
                    f"{plugin}/{skill} is stale: deployed {version}, "
                    f"origin/main {want} (marketplace freshness).")

        for newer in newer_cache_copies(install_path):
            versions = deployed_skill_versions(newer)
            moved = sorted(s for s, v in versions.items()
                           if deployed.get(s) and v and v != deployed[s])
            if moved:
                detail = ", ".join(
                    f"{s} {deployed[s]} -> {versions[s]}" for s in moved)
                findings.append(
                    f"{plugin}: a newer copy sits at {newer.name} carrying "
                    f"{detail}. A session that launched before it arrived is "
                    f"still serving the deployed copy at {install_path.name} "
                    f"(session binding).")
    return findings, notes


def report_skill_drift(root=None):
    """Warn about drift. Never refuses, and never raises."""
    try:
        findings, notes = skill_drift(root)
    except Exception as exc:  # noqa: BLE001 - a report must not break a dispatch
        warn(f"deployed skills not compared - {exc}")
        return
    if findings:
        log("skill-drift", [], findings=findings)
        warn("deployed skills have drifted:\n" + "\n".join(
            f"  - {f}" for f in findings))
    elif notes:
        warn("deployed skills not fully compared - " + " ".join(notes))


def cache_path(session_id):
    slug = re.sub(r"[^A-Za-z0-9_-]", "", str(session_id))[:64] or "nosession"
    return Path(tempfile.gettempdir()) / f"pt-transition-{slug}.txt"


def already_settled(cache):
    try:
        return {line.strip() for line in cache.read_text().splitlines() if line.strip()}
    except OSError:
        return set()


def pending_keys(keys, settled, statuses):
    """The dispatched keys still owed a transition on this prompt.

    PPA-1427. The cache is an optimisation and never an authority. A key it
    lists whose live status is dispatchable has been rejected since it was
    cached, so it is owed the hop again. That is the ordinary rework loop, and
    it is how PPA-1407 sat at Reopened through the dispatch of 13-SEP-2026
    while PPA-1416, PPA-1418 and PPA-1422 all moved: the conductor rejected it
    to Reopened at 23:36 EDT, outside the session, and the cache had no way to
    know.

    A key with no live status falls back to the cache alone, which is what this
    did before any status was read here. The widening is deliberately this
    narrow: no other cached state is second-guessed.
    """
    dispatchable = {s.casefold() for s in DISPATCHABLE_STATUSES}
    return [
        k for k in keys
        if k not in settled
        or " ".join(str(statuses.get(k, "")).split()).casefold() in dispatchable
    ]


def record_settled(cache, keys):
    if not keys:
        return
    try:
        with cache.open("a") as fh:
            fh.write("".join(f"{k}\n" for k in keys))
    except OSError:
        pass  # A cache miss costs a redundant read, never a wrong answer.


def verdict_lines(stdout):
    """Every line of the subprocess's stdout this hook could parse.

    Separate from settled_from() because "no settled key" and "no readable
    output" are different failures. A run where every key HALTed is perfectly
    parseable and settles nothing; treating it as a parse failure would file
    the commonest real failure under the wrong reason.
    """
    return [line for line in stdout.splitlines() if _VERDICT_RE.match(line)]


def settled_from(stdout):
    return [
        m.group(1)
        for m in (_VERDICT_RE.match(line) for line in stdout.splitlines())
        if m and m.group(2) in _SETTLED
    ]


def warn(message):
    print(json.dumps({"systemMessage": f"PPA transition hook — {message}"}))


def log(reason, keys, **fields):
    """Append one JSON record naming an outcome, and never raise.

    JSON Lines rather than prose: stderr is multi-line and is recorded
    verbatim, which a one-field-per-column format cannot carry, and one
    self-describing record per line stays greppable by key or by reason.

    **Every outcome, not only the failures - PPA-1548.** This was a
    failures-only log, and the success path wrote nothing anywhere, so a hook
    that never ran and a hook that returned early at its own guards left the
    same evidence: nothing. The existing sink gained the success records rather
    than a second sink being added, because one file, one format and one
    ``reason`` vocabulary is what makes a run greppable at all - a reader who
    has to know which of two sinks to look in has the same problem one level
    up. ``reason`` names the outcome; a reader wanting failures alone greps the
    reasons that are failures.

    Swallowing OSError here is deliberate and is not the silent-failure this
    ticket closes. A hook that cannot write its log has nowhere left to report
    that, and raising would turn a bookkeeping problem into a session that
    will not start.
    """
    record = {
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "reason": reason,
        "keys": list(keys),
        **{k: v for k, v in fields.items() if v not in (None, "")},
    }
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def mixed_work_types_message(by_type):
    """What the conductor reads when one leading line names both work types.

    ``by_type`` maps each work type to the dispatched keys carrying it. Both
    halves are named, so the split can be made from the message alone.
    """
    return (
        "Dispatch mixes two work types.\n\n"
        "Delegated (its own dispatch, a Sonnet session): "
        f"{', '.join(by_type['Delegated'])}\n"
        f"Discovery (its own dispatch, launched with `{DISCOVERY_LAUNCH}`): "
        f"{', '.join(by_type['Discovery'])}\n\n"
        "The two never share a dispatch. Send each half as its own first "
        "line, in its own session. There is no opt-out: naming a key again "
        "would put a Discovery ticket in a Sonnet session or the reverse."
    )


def _check_ppa_complete(prompt, keys, fields=None):
    """The block message when this dispatch is wrong, else None.

    ``keys`` are the dispatched keys - the leading line's, not every key in the
    prompt - because the repository is read from the tickets being dispatched.

    ``fields`` is the shared read from PPA-1465, or None to read for itself.

    PPA-1716. The dispatch is measured against the dispatchable tickets of its
    own work type, and a leading line mixing the two types is refused.

    Every failure reaching Jira returns None. The check exists to catch a
    conductor's omission, and a Jira outage is not one - blocking on an
    unreadable backlog would make every dispatch in the estate depend on Jira
    being up, which is the trade the transition half already refused.
    """
    try:
        scope = scope_of(repo_components_of(keys, fields=fields))
        by_type = work_types_of(keys, fields=fields)
    except Exception as exc:  # noqa: BLE001 - every read failure warns and allows
        log("repo-scope-read-failed", keys, error=repr(exc))
        warn(f"dispatch completeness not checked - {exc}")
        return None

    if scope.unscoped:
        # Never silently excluded: a key with no REPO: component is named
        # whether or not the rest of the dispatch still resolves.
        log("unscoped-keys", scope.unscoped)
        warn(f"{', '.join(scope.unscoped)} carry no REPO: component, so they "
             "are outside the completeness check. A ticket with no repository "
             "has not cleared the Ticket Quality Bar.")

    if scope.blocked:
        log("dispatch-spans-repositories", keys)
        return scope.blocked

    if len(by_type) > 1:
        # Ahead of the repository check below: a mixed line is wrong whatever
        # backlog it is measured against.
        #
        # Dropped (PPA-1716): a Discovery dispatch into a session not running
        # Opus is not refused. The UserPromptSubmit payload carries session_id,
        # transcript_path, cwd, permission_mode, hook_event_name, prompt and
        # prompt_id - no model - and the only related environment value is
        # CLAUDE_EFFORT, which is effort. The transcript names the model in a
        # ``model`` attachment, but the file does not exist yet when the first
        # prompt fires. All read from a live claude -p probe on 29-SEP-2026
        # (Claude Code 2.1.285, print mode; interactive not probed). What
        # breaks if not fixed: a Discovery ticket can run on Sonnet unnoticed,
        # caught only if the conductor reads the session header.
        log("dispatch-mixed-work-types", keys, by_type=by_type)
        return mixed_work_types_message(by_type)

    if not scope.component:
        # No key named a repository, so there is no backlog to measure against.
        warn("dispatch completeness not checked - no dispatched key carries a "
             "REPO: component, so no repository could be derived.")
        return None

    excluded = []
    unreadable = []
    held = []
    work_type = next(iter(by_type), None)
    try:
        dispatchable = dispatchable_set(scope.component, excluded=excluded,
                                        unreadable=unreadable,
                                        work_type=work_type, held=held)
    except Exception as exc:  # noqa: BLE001 - every read failure warns and allows
        log("dispatchable-read-failed", keys, component=scope.component,
            error=repr(exc))
        warn(f"dispatch completeness not checked for {scope.component} - {exc}")
        return None

    if unreadable:
        # A row left in the set because its links would not parse. It degrades
        # towards asking too much, which is the safe direction, but a degrade
        # nobody can see is the shape condition 4 exists to prevent.
        log("blocker-read-failed", [k for k, _ in unreadable],
            component=scope.component,
            errors=dict(unreadable))
        warn(unreadable_warning(unreadable))

    if excluded:
        # Named rather than dropped in silence: the set the check measures
        # against just shrank, and a check that quietly shrinks its own
        # population is worse than one that asks too much.
        log("blocked-tickets-excluded", [k for k, _ in excluded],
            component=scope.component,
            blockers=dict(excluded))
        warn(excluded_warning(excluded))

    if held:
        # PPA-1752: named for the same reason - the set shrank by a date hold.
        log("held-tickets-excluded", [k for k, _ in held],
            component=scope.component,
            until={k: str(d) for k, d in held})
        warn(held_warning(held))

    missing = missing_from(dispatchable, keys_in(prompt))
    if not missing:
        return None

    log("dispatch-incomplete", missing, component=scope.component,
        work_type=work_type, dispatchable=dispatchable)
    return block_message(missing, scope.component, work_type)


def check_peechpmo_complete(prompt):
    """The block message when the prompt omits a dispatchable PEECHPMO key.

    A Jira failure warns and allows, as the PPA half does.
    """
    try:
        dispatchable = peechpmo_dispatchable_set()
    except Exception as exc:  # noqa: BLE001 - every read failure warns and allows
        log("peechpmo-dispatchable-read-failed", [], error=repr(exc))
        warn(f"dispatch completeness not checked for PEECHPMO - {exc}")
        return None
    missing = missing_from(dispatchable, keys_in(prompt))
    if not missing:
        return None
    log("dispatch-incomplete", missing, component="PEECHPMO",
        dispatchable=dispatchable)
    return block_message(missing, "PEECHPMO (Mac Fleet)")


def check_dispatch_complete(prompt, keys, fields=None):
    """The block message when this dispatch is wrong, else None (PPA-1829).

    Each key is measured against its own project's open set. The PPA keys go
    through ``_check_ppa_complete`` exactly as before; the PEECHPMO keys are
    measured against the PEECHPMO half of Jamf rule 7. A mixed line runs both
    and reports each set's missing keys under its own project.
    """
    pmo = [k for k in keys if k.upper().startswith("PEECHPMO-")]
    if not pmo:
        return _check_ppa_complete(prompt, keys, fields=fields)
    ppa = [k for k in keys if k not in pmo]
    messages = [m for m in (
        _check_ppa_complete(prompt, ppa, fields=fields) if ppa else None,
        check_peechpmo_complete(prompt)) if m]
    return "\n\n".join(messages) or None


def dispatch_set_lines(repository):
    """One line per key the completeness check would demand - PPA-1660.

    Each line is ``key``, ``status``, ``work type`` (PPA-1716) and the Bar
    verdict, tab-separated. The set spans both work types; a dispatch is
    measured against one of them.

    Chat composed dispatches from build_delegated_batches.py or a JQL read, and
    neither applies this hook's test, so a dispatch could be refused for a set
    the conductor never saw. This prints that set by calling what the hook
    calls: ``dispatchable_set`` for the keys, ``dispatched_fields`` and
    ``bar_failures`` for each key's Bar verdict. No second implementation of
    either test exists, and this adds no Jira write.

    Blocked, held (PPA-1752) and unreadable keys are listed after the set,
    marked, because the hook names each in its own warnings. Raises on a read
    failure.

    Dropped (PPA-1660): where the bundled barred-artifact check will not
    import, ``barred_artifacts`` warns through ``warn()``, which writes
    systemMessage JSON to stdout, so that one line lands among these. What
    breaks if not fixed: nothing observable - the check ships in this plugin's
    scripts/ and imports, and a stray line would read as the degrade it is.
    """
    component = (repository if _REPO_COMPONENT_RE.match(repository)
                 else f"REPO: {repository}")
    excluded, unreadable, held = [], [], []
    keys = dispatchable_set(component, excluded=excluded, unreadable=unreadable,
                            held=held)
    fields = dispatched_fields(keys) if keys else {}
    lines = []
    for key in keys:
        if key not in fields:
            lines.append(f"{key}\t?\t?\tBar not read - Jira did not return the key")
            continue
        missing = bar_failures(fields[key])
        verdict = f"FAIL - missing {', '.join(missing)}" if missing else "PASS"
        kind = work_type_of(fields[key]["components"]) or "?"
        lines.append(f"{key}\t{fields[key]['status']}\t{kind}\t{verdict}")
    lines.extend(f"# not demanded, blocked by {', '.join(blockers)}: {key}"
                 for key, blockers in excluded)
    lines.extend(f"# not demanded, held until {until}: {key}"
                 for key, until in held)
    lines.extend(f"# links unreadable, still demanded: {key} ({error})"
                 for key, error in unreadable)
    return lines


def dispatch_set_main(argv):
    """``--dispatch-set <repo>``: print the set and exit 0, whatever the Bar says.

    Exit 1 only when Jira cannot be read, because an empty listing would then
    read as an empty backlog.
    """
    import argparse  # noqa: PLC0415 - the hook path never parses argv

    parser = argparse.ArgumentParser(
        prog="transition_on_prompt.py",
        description="Print the dispatchable set this hook demands for a "
                    "repository, with each key's Ticket Quality Bar verdict.")
    parser.add_argument("--dispatch-set", metavar="REPO", required=True,
                        help="peech-pmo-automation, or 'REPO: peech-skills'")
    args = parser.parse_args(argv)
    try:
        lines = dispatch_set_lines(args.dispatch_set)
    except Exception as exc:  # noqa: BLE001 - reported, never a silent empty set
        print(f"dispatch set not read - {exc!r}", file=sys.stderr)
        return 1
    print("\n".join(lines) if lines else
          f"# no dispatchable key for {args.dispatch_set}")
    return 0


def main():
    """Never raises. Returns 2 only when an admission check refuses, else 0.

    See "The transition never blocks" above: every failure path returns 0, and
    the refusals are the repository-match check, the completeness check and the
    Bar check each answering positively, and the malformed first line carrying
    two or more keys (PPA-1784).

    The outer guard is what makes "any exception is logged" true rather than
    aspirational: an unexpected failure below would otherwise leave the same
    no-trace hole in a different place. It returns 0 rather than 2, so a hook
    that breaks lets the dispatch through instead of refusing every prompt.
    """
    try:
        return _transition()
    except Exception as exc:  # noqa: BLE001 — a hook that raises is worse
        log("hook-raised", [], error=repr(exc))
        return 0


def _transition():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError) as exc:
        log("unreadable-payload", [], error=repr(exc))
        return 0

    prompt = str(payload.get("prompt") or "")
    keys = dispatched_keys(prompt)
    if not keys:
        # Either no key at all, or keys only in prose. Neither is a dispatch,
        # so neither transitions anything and neither is checked for
        # completeness. See "A dispatched key is not a mentioned one" above.
        #
        # A first line carrying keys that still failed the qualifier is the
        # third case PPA-1418 did not reason about - see "A malformed dispatch
        # is not a silent one" above. One key warns and returns 0: it is
        # ordinary conversation. Two or more refuse with exit 2 (PPA-1784),
        # because the session would build with every ticket left at To Do.
        # Nothing is transitioned either way.
        #
        # PPA-1548: both readings record, and the record carries the line the
        # resolver read, so the next occurrence names its own cause instead of
        # needing a code read. The warning rides out as systemMessage, which is
        # where the operator sees it - stderr from a hook exiting 0 reaches the
        # debug log only, which is why a four-key dispatch on 18-SEP-2026
        # transitioned nothing and warned nobody.
        line = first_nonblank_line(prompt)
        malformed = malformed_dispatch_warning(prompt)
        if malformed:
            mentioned = keys_in(line)
            log("malformed-dispatch", mentioned, first_line=line)
            if len(mentioned) >= REFUSE_AT_KEYS:
                print(f"{malformed}\n\n{ASK_INSTEAD}", file=sys.stderr)
                return 2
            warn(malformed)
        else:
            log("no-dispatch", [], first_line=line)
        return 0

    # One Jira read for the three checks below - PPA-1465. A failure here is
    # not handled here: each check owns its own warn-and-allow, and one handed
    # None reads for itself rather than being silently skipped.
    shared, _read_error = read_dispatched(keys)

    mismatched = check_repository_match(keys, fields=shared)
    if mismatched is not None:
        # The refusal with no opt-out, and the only one in this file. A
        # completeness refusal and a Bar refusal both clear by naming the key
        # again, because a conductor can have a reason. There is no reason to
        # ship a ticket from a repository it does not belong to: one commit
        # reaches one remote.
        print(mismatched, file=sys.stderr)
        return 2

    blocked = check_dispatch_complete(prompt, keys, fields=shared)
    if blocked is not None:
        # The one path in this file that refuses a prompt. Exit 2 is the only
        # code a UserPromptSubmit hook can block with, and stderr is what the
        # conductor is shown. Nothing is transitioned: the session will not act
        # on this prompt, so moving its tickets would record work not started.
        print(blocked, file=sys.stderr)
        return 2

    bar_blocked, statuses = check_quality_bar(prompt, keys, shared=shared)
    if bar_blocked is not None:
        # The second refusal, and it refuses for the same reason as the first:
        # the command is wrong rather than the bookkeeping. A ticket that never
        # cleared the Bar is not a ticket a session can build from, and letting
        # it through costs the dispatch either way.
        print(bar_blocked, file=sys.stderr)
        return 2

    # Reported, never refused - a stale skill is a fact worth knowing at
    # dispatch, not the command being wrong. It runs after every refusal so a
    # blocked dispatch is not also told about its skills.
    report_skill_drift()

    cache = cache_path(payload.get("session_id"))
    pending = pending_keys(keys, already_settled(cache), statuses)
    if not pending:
        # Nothing to do, which is an outcome and not an absence - PPA-1548.
        # Without this record a dispatch whose keys were all settled earlier in
        # the session looks exactly like a hook that never fired.
        log("already-settled", keys)
        return 0

    if not SCRIPT.is_file():
        log("no-script", pending, script=str(SCRIPT))
        warn(f"{', '.join(pending)} not moved to {TARGET!r} — no script at "
             f"{SCRIPT}. Clone peech-ci-workflows to {SCRIPT.parents[1]}.")
        return 0

    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--keys", ",".join(pending), "--to", TARGET],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=str(REPO),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log("subprocess-failed", pending, error=repr(exc))
        warn(f"{', '.join(pending)} not moved to {TARGET!r} — {exc}")
        return 0

    record_settled(cache, settled_from(proc.stdout))
    verdicts = verdict_lines(proc.stdout)

    # One record per run, naming which of the three the subprocess produced -
    # PPA-1548. The branches were an if and a second if before, so a run that
    # both failed and printed nothing readable filed two reasons for one
    # outcome; they are one chain now, and the last arm is the success path
    # that filed nothing at all.
    if proc.returncode != 0:
        # stdout as well as stderr: pt_transition.py prints only "HALTED: keys"
        # to stderr and puts the reason for each halt on stdout, so stderr
        # alone records that a run failed without recording why.
        log("nonzero-exit", pending, exit_code=proc.returncode,
            stderr=proc.stderr, stdout=proc.stdout)
        detail = (proc.stderr.strip() or proc.stdout.strip() or "no output")[-600:]
        warn(f"{', '.join(pending)} — not every key reached {TARGET!r}:\n{detail}")
    elif not verdicts:
        # A subprocess that ran and produced no readable verdict line at all.
        # Distinct from a non-zero exit and previously indistinguishable from
        # it, because both were silent. The raw stdout rides along because the
        # parse is what failed, so the text the parse could not read is the
        # whole evidence.
        log("unparseable-output", pending, exit_code=proc.returncode,
            stderr=proc.stderr, stdout=proc.stdout)
        warn(f"{', '.join(pending)} — {TARGET!r} reported no verdict this "
             f"hook could read; see {LOG}")
    else:
        # The path this ticket exists for. It writes no warning, because a
        # success the operator did not ask about is noise - but it writes a
        # record, because the alternative is what PPA-1543 measured: a
        # successful transition left a per-session cache entry and nothing
        # else, so it could not be told apart from a hook that never ran.
        log("transitioned", pending, target=TARGET, exit_code=proc.returncode,
            verdicts=verdicts)
    return 0


if __name__ == "__main__":
    sys.exit(dispatch_set_main(sys.argv[1:]) if sys.argv[1:] else main())
