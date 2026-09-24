#!/usr/bin/env python3
"""Advance PPA tickets to a target status by name, one live hop at a time.

PPA-1021. No transition ID is a literal in this file. Every ID fired comes
from a live read in the same run: the script reads the current status, reads
the transition set actually offered from that status, and fires either the
transition that reaches the target directly or the single transition that
moves one rung toward it — re-reading after each hop, capped at three.

This replaces the fixed In Progress -> Client Validation -> Done chain that
failed on 13-AUG-2026. That script assumed its starting status and fired a
remembered ladder, so it halted on the first step whenever a ticket sat
somewhere else (PPA-965 and PPA-1013 were both still at To Do). Here the
starting status is read, never assumed.

Idempotent by design: a key already at or past the target is reported NOOP and
no write is attempted. Running twice is safe, and a session that already
applied its own transition costs nothing — whichever runs second no-ops.

Conductor-gated by destination. PPA-1025: a hop whose destination is in
CONDUCTOR_ONLY fires only when --conductor is passed. Without the flag the run
halts on that key and writes nothing, naming the destination and the rule.

Both guards were narrowed by PPA-1264, and the record of why is here on
purpose. PPA-1025 put Done and Reopened in CONDUCTOR_ONLY. PPA-1186 finding 4
then added --skip-validation on top of it, because the live "Closed - No client
approval required" transition carries In Progress straight to Done — around
Client Validation, the acceptance gate — while satisfying the conductor guard
completely. Both guards existed for one reason: to stop a delegated session
closing its own ticket.

Nothing closes its own ticket now. Ruled 07-SEP-2026: Done applies when the
outcome can be confirmed, and the actor that applies it is a merge-triggered
GitHub Actions workflow (PPA-1261) observing a mechanical fact — a pull request
merged with every required check green. That is not a session judging its own
work. So PPA-1264 dropped Done from CONDUCTOR_ONLY and retired
--skip-validation outright. Passing --skip-validation now errors rather than
being quietly ignored.

PPA-1264's premise went, PPA-1382 removed it, and PPA-1459 has now brought a
different one back — read all of this before restoring anything. PPA-1264
(07-SEP-2026) kept the In Progress -> Done path open on the stated ground that
it was the merge workflow's ordinary work. PPA-1382 (12-SEP-2026) then made
Client Validation that workflow's only outcome, so the actor PPA-1264 kept the
path open for could no longer use it. PPA-1382 supersedes PPA-1264 on that
point. The removal was never reversed and the gap ran unguarded until PPA-1433
(13-SEP-2026) closed it with validation_skipped() below.

PPA-1459 (17-SEP-2026) narrowed that guard rather than lifting it. Auto-Done
shipped into the merge close-out as 91645d0d2f65, and on two merges it graded
a ticket's Definition of Done, found every condition machine-checkable and
every one reported met, asked for Done, and was refused here — runs 35257775366
and 35277277762, both exiting 1. The actor PPA-1264 named has therefore come
back, but as a different actor than the one PPA-1382 wrote off: not a workflow
that transitions on the bare fact of a merge, but one that reads the ticket's
conditions first and only asks for Done when there is nothing left for a person
to judge.

So the guard now reads: a hop landing on Done from any status but Client
Validation halts and writes nothing, except In Progress to Done inside a run of
the merge close-out workflow. Nothing else moved. Done is still out of
CONDUCTOR_ONLY, --skip-validation is still retired, no flag was added, and the
parser is unchanged. The exemption is granted to where the process is running,
never to what a caller says about itself — see merge_close_out_run().

Do not restore either guard by reading its original rationale alone, and do not
widen PPA-1459's exemption the same way. Both rationales still hold for the
actor they were written about — a session judging its own work — and that actor
reaches Done through neither: it cannot pass a flag that does not exist, and it
cannot be a GitHub Actions runner.

Reopened stays gated, and it is now the whole of --conductor's job. Reopened is
a rejection verdict, a human judgement about work that failed, so it never
becomes a mechanical fact any workflow can observe.

The guard is declarative, not authenticated. load_credentials() reads one
JIRA_EMAIL / JIRA_API_TOKEN pair, so the conductor and a delegated session
authenticate as the same Jira user and no check here can tell them apart.
--conductor is a claim the caller makes, not an identity this script verifies.
It converts an implicit assumption into an explicit, auditable one and removes
the inattention path that let the ownership rule fail four times — PPA-896,
PPA-965, PPA-1013 and PPA-1022. It does not stop a session that decides to
pass the flag.

Distributed, not shared. PPA-1126 copied this file into peech-skills and
peech-org-skills so the UserPromptSubmit transition hook is not dead in two of
the three governed repos. The copies are byte-identical; edit this one and copy
it out again. Credentials stay in one place — see CREDENTIALS below.

Usage:
    python3 scripts/pt_transition.py --keys PPA-1,PPA-2 --to "Done"
    python3 scripts/pt_transition.py --keys PPA-1 --to "Done" --dry-run
    python3 scripts/pt_transition.py --keys PPA-1 --to "Reopened" --conductor
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path.home() / "Documents/Claude-Projects"
CLOUD_ID = "c7797270-45ee-4bba-ab1f-dff570edf68c"
BASE = f"https://api.atlassian.com/ex/jira/{CLOUD_ID}/rest/api/3"
HOP_CAP = 3

# Status *names*, in lifecycle order — from pt-backlog section Close-Out, and
# confirmed against the live PPA Story/Bug workflow on 13-AUG-2026. This is an
# ordering only: it never supplies a transition ID, and it is consulted solely
# to pick which of several offered transitions moves toward the target. Every
# other PPA status (BLOCKED, Info Provided, Need More Info - Client, Reopened,
# Closed - Not Needed) is deliberately off this ladder — those are side states,
# and the script will not route through one on its own initiative.
LIFECYCLE = ("To Do", "In Progress", "Client Validation", "Done")

# The rungs named rather than indexed at each use. PPA-1433 guards the hop
# between the last two, and PPA-1459 exempts one source from that guard; a
# guard that spells its own statuses would be a second place for the ladder to
# be stated - the defect this file exists to avoid.
WORKING, VALIDATION, FINAL = LIFECYCLE[1], LIFECYCLE[-2], LIFECYCLE[-1]

# The one caller PPA-1459 exempts from the PPA-1433 guard, identified by the
# environment GitHub Actions gives its own runner rather than by a flag. The
# path is the same in all three governed repositories, checked 17-SEP-2026, and
# the four facts below are together a statement about where this process is
# running, not a claim its caller makes. PPA-1614 admits the schedule trigger
# beside the push: the hourly re-grade grades held tickets the same way.
MERGE_CLOSE_OUT_WORKFLOW = ".github/workflows/merge-close-out.yml"

# The events a close-out run is raised by. A push to main is the merge itself;
# the schedule is the hourly re-grade of tickets a merge left held (PPA-1614).
# workflow_dispatch is absent on purpose: a dispatch is a person choosing to
# run the workflow, which is a hand run by another route.
#
# Dropped, 24-SEP-2026: peech-pmo-automation's merge-close-out.yml header still
# says GITHUB_EVENT_NAME must be push. It is a comment no code reads, so nothing
# misbehaves while it is wrong; this tuple is the rule.
CLOSE_OUT_EVENTS = ("push", "schedule")

# Status *names* whose arrival is a gate verdict rather than a work event, so
# only the conductor fires a hop landing on one. Names, never IDs — the same
# rule as LIFECYCLE above. Ruled 26-AUG-2026 (PPA-1025) with Done and Reopened
# both here; PPA-1264 dropped Done on 07-SEP-2026, because the actor that
# reaches it is now a merge-triggered workflow reading a merged pull request
# rather than a session judging its own work. Reopened alone remains: a
# rejection verdict is a human judgement no workflow can observe. Client
# Validation was never here — a delegated session applied that one itself.
# Reopened is deliberately off the LIFECYCLE ladder as well: it is a side state
# the script reaches only when a caller names it.
CONDUCTOR_ONLY = ("Reopened",)


# ---------------------------------------------------------------- credentials

#: The single credential home for every copy of this script. Settled 21-AUG-2026
#: under PPA-1126, when the script was distributed into peech-skills and
#: peech-org-skills: the path stays absolute and stays here rather than becoming
#: resolvable per repo. One .env is one place to rotate a token; three would be
#: three, and two of the three repos have no secrets/ directory and no
#: gitignore entry for one. The copies are byte-identical by design.
CREDENTIALS = ROOT / "peech-pmo-automation/secrets/.env"


def load_credentials():
    env = CREDENTIALS
    if not env.is_file():
        raise FileNotFoundError(
            f"no Jira credentials at {env} — this is the single credential home for "
            "every copy of this script (PPA-1126). Clone peech-pmo-automation "
            "alongside this repo, or point CREDENTIALS at the .env you hold.")
    out = {}
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def make_client(creds):
    """Return (get, post). Same Basic-auth/urllib path as
    build_delegated_batches.py's make_getter, extended with the POST the
    transition write needs."""
    auth = base64.b64encode(
        f"{creds['JIRA_EMAIL']}:{creds['JIRA_API_TOKEN']}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    def get(path):
        req = urllib.request.Request(f"{BASE}{path}", headers=headers)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def post(path, payload):
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(payload).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
        return json.loads(body) if body else None

    return get, post


# -------------------------------------------------------------- name matching

# Dash characters Jira renders inside status and transition names, folded to
# the ASCII hyphen. The live PPA workflow renders "Closed – Not Needed" with an
# en dash, while every hand-typed and hand-authored form of that same name uses
# a hyphen — without folding, the two never match and the status is
# unreachable by name (PPA-1039).
_DASH_VARIANTS = str.maketrans({
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    "‒": "-",  # figure dash
    "–": "-",  # en dash
    "—": "-",  # em dash
    "―": "-",  # horizontal bar
    "−": "-",  # minus sign
})


def norm(name):
    """Collapse whitespace, dash variants and case so 'CLIENT VALIDATION'
    matches 'Client Validation' and 'Closed - Not Needed' matches
    'Closed – Not Needed'. Jira renders status names inconsistently across
    surfaces; the operator types what they saw."""
    return " ".join(str(name).translate(_DASH_VARIANTS).split()).casefold()


LADDER = {norm(name): index for index, name in enumerate(LIFECYCLE)}
_CONDUCTOR_ONLY = frozenset(norm(name) for name in CONDUCTOR_ONLY)


def requires_conductor(destination):
    """True when a hop landing on `destination` is the conductor's to fire.

    Pure by design: no client, no credentials, no network, so the guard is
    testable on its own. Compared through norm(), so 'DONE' and ' Done '
    match the same way an operator's --to argument does.
    """
    return norm(destination) in _CONDUCTOR_ONLY


def merge_close_out_run(environ):
    """True when this process is a run of the merge close-out workflow.

    The discriminator PPA-1459 chose, and the reason it is the environment
    rather than a flag: --conductor and the retired --skip-validation are both
    claims a caller makes, and validation_skipped() below is the guard that
    replaced the second of them. Exempting the workflow with a third flag would
    rebuild what has now failed twice, because a hand run can pass any flag it
    reads in --help. These four facts are GitHub's own, written into the runner
    before this process starts. A hand run has none of them: presenting them
    means setting four GitHub variables by hand on a laptop, which is a
    deliberate forgery rather than the inattention path every guard in this
    file was written to close.

    All four are required, and each one is load-bearing:

    * GITHUB_ACTIONS - a runner rather than a laptop.
    * GITHUB_EVENT_NAME and GITHUB_REF - a push to the default branch, which is
      the merge the close-out exists to record, or the scheduled re-grade,
      which GitHub runs on the default branch (PPA-1614). A dispatch is
      refused on any ref, because it is a person choosing to run it.
    * GITHUB_WORKFLOW_REF - this workflow and not another job in the same
      repository. Its documented form is
      ``owner/repo/.github/workflows/name.yml@refs/heads/branch``, so the ref
      is split off before the path is matched.

    Pure by design, like requires_conductor() and validation_skipped(): the
    mapping is passed in rather than read from os.environ, so the guard is
    testable without mutating the process it runs in - and so this repository's
    own pytest job, which is a GitHub Actions run on a push to main, cannot
    change what a test asserts by being one.
    """
    workflow = (environ.get("GITHUB_WORKFLOW_REF") or "").split("@", 1)[0]
    return (environ.get("GITHUB_ACTIONS") == "true"
            and environ.get("GITHUB_EVENT_NAME") in CLOSE_OUT_EVENTS
            and environ.get("GITHUB_REF") == "refs/heads/main"
            and workflow.endswith("/" + MERGE_CLOSE_OUT_WORKFLOW))


def validation_skipped(source, destination, merge_close_out=False):
    """The halt reason when a hop lands on Done from a rung that may not reach
    it, else None.

    PPA-1433. A source-status rule, not a destination rule, and the two are
    independent: CONDUCTOR_ONLY still answers "who may fire this hop", and this
    answers "which rung may it be fired from". Adding Done back to
    CONDUCTOR_ONLY would instead gate the one legitimate hop behind a flag.

    PPA-1459 narrowed it, and the narrowing is not an override. PPA-1186
    finding 4 made this an opt-in via --skip-validation and PPA-1264 retired
    that flag; restoring an override under any name would rebuild the thing
    that has now failed twice, so no flag was added and the parser is
    unchanged. What changed is that a caller now exists that has earned the
    hop. Auto-Done reads the ticket's Definition of Done, finds every condition
    machine-checkable, finds every one reported met, and only then asks for
    Done - so for that caller Client Validation is a scheduling step with
    nothing left to judge, which is the ruling PPA-1459 implements. The
    exemption is granted to where the process is running, never to what it
    says about itself: see merge_close_out_run() above.

    It is narrowed twice over. The exemption covers the one hop the workflow
    fires, In Progress to Done, and no other: a run inside the close-out
    workflow reaching for Done from any other rung is still refused, because
    plan_transition() never asks for that and a run that did has lost track of
    the ticket rather than graded it. Its caller in advance() adds the second
    half, that the hop be the run's first, so the exemption cannot be picked up
    part-way along the ladder.

    What did not change: a hand run is refused from every rung, Client
    Validation remains the one source any caller may reach Done from, and
    Client Validation to Reopened is untouched. Ruled 13-SEP-2026 and standing:
    every PPA ticket a person closes reaches Done through Client Validation.

    Pure by design, like requires_conductor() above: no client, no credentials,
    no network, so the guard is testable on its own.
    """
    if norm(destination) != norm(FINAL):
        return None
    if norm(source) == norm(VALIDATION):
        return None
    if merge_close_out and norm(source) == norm(WORKING):
        return None
    return (f"hop {source!r} -> {destination!r} skips {VALIDATION!r}, the "
            f"acceptance gate every PPA ticket reaches {FINAL!r} through "
            f"(PPA-1433). Only a merge close-out workflow run is exempt, and "
            f"this process is not one (PPA-1459). Nothing fired")


# ------------------------------------------------------------------- planning

def choose_transition(current, target, transitions, ladder=None):
    """Pick the one transition to fire from `current` toward `target`.

    Returns (transition, None) on a clean choice, or (None, reason) when the
    run must halt on this key. Never returns a guess: an ambiguous set halts.
    """
    ladder = LADDER if ladder is None else ladder

    # A target the ladder does not carry is still reachable, provided the live
    # set offers it directly — this branch runs before any ladder lookup. That
    # is what makes the PPA-1025 reject loop work with Reopened off LIFECYCLE:
    # Client Validation -> Reopened and Reopened -> In Progress are each one
    # offered transition, resolved here by name. The ladder is consulted only
    # to pick an intermediate rung, which is why Reopened never becomes one the
    # script routes through on its own initiative.
    direct = [t for t in transitions if norm(t["to"]["name"]) == norm(target)]
    if len(direct) == 1:
        return direct[0], None
    if len(direct) > 1:
        names = ", ".join(repr(t["name"]) for t in direct)
        return None, (f"{len(direct)} transitions reach {target!r} "
                      f"({names}); ambiguous")

    here = ladder.get(norm(current))
    there = ladder.get(norm(target))
    if here is None:
        return None, (f"current status {current!r} is off the lifecycle ladder "
                      f"and {target!r} is not offered from it")
    if there is None:
        return None, (f"target status {target!r} is not on the lifecycle "
                      f"ladder and is not offered from {current!r}")
    if there <= here:
        return None, f"target {target!r} is not forward of {current!r}"

    forward = {}
    for t in transitions:
        rung = ladder.get(norm(t["to"]["name"]))
        if rung is not None and here < rung <= there:
            forward.setdefault(rung, []).append(t)
    if not forward:
        offered = ", ".join(repr(t["to"]["name"]) for t in transitions) or "none"
        return None, (f"no transition offered from {current!r} advances toward "
                      f"{target!r} (offered: {offered})")

    candidates = forward[min(forward)]
    if len(candidates) > 1:
        names = ", ".join(repr(t["name"]) for t in candidates)
        return None, (f"{len(candidates)} transitions reach "
                      f"{candidates[0]['to']['name']!r} ({names}); ambiguous")
    return candidates[0], None


# -------------------------------------------------------------------- reading

def read_status(get, key):
    return get(f"/issue/{key}?fields=status")["fields"]["status"]["name"]


def read_transitions(get, key):
    return get(f"/issue/{key}/transitions")["transitions"]


# ------------------------------------------------------------------ advancing

class Result:
    """One key's outcome. verdict is PASS, NOOP or HALT."""

    def __init__(self, key, start, end, hops, verdict, detail=""):
        self.key = key
        self.start = start
        self.end = end
        self.hops = hops
        self.verdict = verdict
        self.detail = detail

    def line(self):
        text = (f"{self.key:<10} {self.start!r} -> {self.end!r} "
                f"hops={self.hops} {self.verdict}")
        return f"{text} — {self.detail}" if self.detail else text


def advance(get, post, key, target, dry_run=False, ladder=None,
            conductor=False, merge_close_out=False):
    """Walk one key toward `target`, re-reading status after every hop."""
    try:
        start = read_status(get, key)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        return Result(key, "?", "?", 0, "HALT", f"status read failed: {exc}")

    current = start
    if norm(current) == norm(target):
        return Result(key, start, current, 0, "NOOP",
                      "already at target; no write attempted")

    # Already past the target is satisfied, not failed. PPA-1126: the
    # UserPromptSubmit hook asks for "In Progress" on every key in a prompt,
    # and a prompt routinely names a ticket that is already at Client
    # Validation or Done. Halting on those would warn on every prompt about
    # nothing. It also refuses to route backward on its own initiative:
    # without this, a workflow offering a direct backward transition would see
    # it fired and the ticket walked down a rung.
    rungs = LADDER if ladder is None else ladder
    here, there = rungs.get(norm(current)), rungs.get(norm(target))
    if here is not None and there is not None and here > there:
        return Result(key, start, current, 0, "NOOP",
                      f"already past {target!r}; no write attempted")

    planned = []
    for hop in range(1, HOP_CAP + 1):
        try:
            transitions = read_transitions(get, key)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            return Result(key, start, current, hop - 1, "HALT",
                          f"transition read failed: {exc}")

        chosen, reason = choose_transition(current, target, transitions, ladder)
        if chosen is None:
            return Result(key, start, current, hop - 1, "HALT", reason)

        destination = chosen["to"]["name"]

        # Gate on this hop's destination, not on `target`. A run of --to "Done"
        # can reach it through an intermediate rung, so a guard reading only
        # the final target would let the earlier hop through and miss the
        # conductor-owned one. Placed before the dry-run return as well, so a
        # dry run surfaces the same refusal rather than a plan that would not
        # run. Both NOOP paths return above this loop, which is what keeps
        # idempotence outranking the guard: a key already at a conductor-owned
        # target attempts no write, so there is nothing here to gate.
        if requires_conductor(destination) and not conductor:
            return Result(key, start, current, hop - 1, "HALT",
                          f"hop to {destination!r} is conductor-owned "
                          f"(CONDUCTOR_ONLY); re-run with --conductor. "
                          f"Nothing fired")

        # PPA-1433. Placed beside the conductor gate and for the same reasons:
        # it reads this hop's destination rather than `target`, so a walk that
        # reaches Done through an intermediate rung is caught on the hop that
        # actually lands there; and it sits before the dry-run return, so a dry
        # run surfaces the refusal rather than printing a plan that would not
        # run. The live workflow offers "Closed - No client approval required"
        # from In Progress, which reaches Done in one hop while satisfying the
        # conductor guard completely — that is the hop this stops.
        #
        # PPA-1459 threads the one exemption in as an argument rather than
        # letting the guard read os.environ for itself. Same reason the ladder
        # and the conductor flag are threaded: a rule that reaches around its
        # caller for state cannot be tested without arranging that state, and
        # this repository's own pytest job runs inside GitHub Actions.
        # The exemption covers the hop the workflow actually fires and only
        # that one: onto Done, from the status the ticket was already in when
        # the run began. `hop == 1` is what enforces the second half. Without
        # it a --to "Done" run from To Do would take the legitimate ladder hop
        # onto In Progress and inherit the exemption on the next pass, which is
        # the same walk test_done_from_to_do_halts covers for a hand run.
        skipped = validation_skipped(current, destination,
                                     merge_close_out and hop == 1)
        if skipped is not None:
            return Result(key, start, current, hop - 1, "HALT", skipped)

        planned.append(f"{current!r} -> {destination!r} "
                       f"via {chosen['name']!r}")

        if dry_run:
            # The transition set is only readable from the status the issue is
            # actually in, so a dry run can resolve the first hop concretely
            # and no further. Say so rather than inventing the rest.
            if norm(destination) == norm(target):
                return Result(key, start, destination, hop, "PASS",
                              "dry run, nothing fired: " + "; ".join(planned))
            planned.append(f"further hops from {destination!r} need a live "
                           f"read; not resolvable without firing")
            return Result(key, start, current, 0, "PASS",
                          "dry run, nothing fired: " + "; ".join(planned))

        try:
            post(f"/issue/{key}/transitions",
                 {"transition": {"id": chosen["id"]}})
            after = read_status(get, key)
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            return Result(key, start, current, hop - 1, "HALT",
                          f"transition {chosen['name']!r} failed: {exc}")

        if norm(after) == norm(current):
            return Result(key, start, after, hop, "HALT",
                          f"transition {chosen['name']!r} produced no status "
                          f"change; not retrying")
        current = after
        if norm(current) == norm(target):
            return Result(key, start, current, hop, "PASS", "; ".join(planned))

    return Result(key, start, current, HOP_CAP, "HALT",
                  f"target {target!r} not reached within {HOP_CAP} hops")


def run(get, post, keys, target, dry_run=False, ladder=None,
        conductor=False, merge_close_out=False):
    return [advance(get, post, key, target, dry_run, ladder, conductor,
                    merge_close_out)
            for key in keys]


def exit_code(results):
    return 1 if any(r.verdict == "HALT" for r in results) else 0


# ------------------------------------------------------------------------ cli

def parse_keys(raw):
    return [k.strip().upper() for k in raw.split(",") if k.strip()]


class RetiredFlag(argparse.Action):
    """Fail with a message naming the ticket that retired the flag.

    A flag simply dropped from the parser gets argparse's generic "unrecognized
    arguments" line, which reads like a typo. A caller passing --skip-validation
    is following a procedure that was documented for months, so the error names
    what retired it and what to do instead. PPA-1264: "A caller passing it gets
    a clear error naming this ticket rather than a silent no-op."
    """

    def __init__(self, option_strings, dest, help=None):
        super().__init__(option_strings, dest, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        parser.error(
            f"{option_string} was retired by PPA-1264 and does nothing. It is "
            f"not coming back: PPA-1433 refuses every hop onto {FINAL!r} whose "
            f"source is not {VALIDATION!r}, with no override, so there is "
            f"nothing to skip. Route the ticket through {VALIDATION!r} and "
            f"re-run without the flag.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Move PPA tickets to a target status by name, hopping one "
                    "live transition at a time.")
    parser.add_argument("--keys", required=True,
                        help="comma-separated issue keys, e.g. PPA-1,PPA-2")
    parser.add_argument("--to", required=True, dest="target",
                        help='target status name, e.g. "Done"')
    parser.add_argument("--dry-run", action="store_true",
                        help="print the planned hops and fire nothing")
    parser.add_argument("--conductor", action="store_true",
                        help="claim the conductor role, permitting a hop onto "
                             f"a conductor-owned status ({', '.join(CONDUCTOR_ONLY)}). "
                             "Without it such a hop halts and writes nothing. "
                             "The claim is not verified — see the module "
                             "docstring")
    parser.add_argument("--skip-validation", action=RetiredFlag,
                        help="RETIRED by PPA-1264. Passing it is an error, not "
                             "a no-op — see the module docstring")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    keys = parse_keys(args.keys)
    if not keys:
        print("no keys given", file=sys.stderr)
        return 2

    get, post = make_client(load_credentials())
    # The single read of the real environment in this file. Everything below it
    # takes the answer as an argument - see merge_close_out_run().
    results = run(get, post, keys, args.target, args.dry_run,
                  conductor=args.conductor,
                  merge_close_out=merge_close_out_run(os.environ))
    for result in results:
        print(result.line())

    halted = [r.key for r in results if r.verdict == "HALT"]
    if halted:
        print(f"HALTED: {', '.join(halted)}", file=sys.stderr)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
