#!/usr/bin/env python3
"""SessionEnd hook (PPA-1407) — arm this session's pull request the moment the
session ends, instead of waiting for the half-hourly sweep to infer that it has.

Why an event and not a proxy
----------------------------
``auto-merge-arm.yml`` arms on a ``*/30`` cron and only for a branch that has
had no push for ``QUIET_MINUTES: 20``. That quiet window is a proxy for one
fact — the delegated session has stopped working — and the proxy costs real
things: merge latency of typically thirty and up to fifty minutes, 48 billed
runs a day per private repository, and an unarmed pull request that a reader
inside the window cannot tell from a failure. Claude Code raises the fact
itself as a lifecycle event, so this hook reads the fact and the sweep stays on
as the fallback.

Why SessionEnd and not Stop — the question PPA-1407 gated on
------------------------------------------------------------
Claude Code's hooks reference (https://code.claude.com/docs/en/hooks, read
12-SEP-2026) gives ``Stop`` as "Runs when the main Claude Code agent has
finished responding." That is the end of a turn, not the end of a session, and
arming there reopens exactly the race PPA-1391 closed: the PPA-1388 follow-up
pushes landed 7m25s and 14m00s after the merge they missed, both in later turns
of a live session.

``stop_hook_active`` does not rescue ``Stop``. The same page defines it as
"``true`` when Claude Code is already continuing as a result of a stop hook" —
a loop guard against a hook that blocks forever, with no bearing on whether a
further turn is coming.

``SessionEnd`` is the event that carries the meaning: "Runs when a Claude Code
session ends." Its payload is ``session_id``, ``transcript_path``, ``cwd``,
``hook_event_name`` and ``reason``, where ``reason`` is one of ``clear``,
``resume``, ``logout``, ``prompt_input_exit`` and ``other``.

Every reason arms. ``clear`` is the commonest one in this estate — a conductor
clearing between tickets in the same terminal — and the session whose branch is
checked out at that moment is finished whatever comes next.

Every branch this session touched, and nothing else — PPA-1417
---------------------------------------------------------------
This hook armed one branch until PPA-1417: the checkout's own, at the moment
the session ended. The workflow is one branch per ticket, because
``merge-close-out.py`` reads a single key from the branch-name prefix, so a
dispatch carrying more than one ticket opens more than one pull request and a
one-branch hook reaches only the last of them.

Measured in peech-pmo-automation on 12-SEP-2026 and reported on PPA-1407: a
session built five tickets and opened PRs #48 through #52; ``/exit`` at
20:57:43 EDT armed #52 alone, ``waited_seconds: 0``, ``reason:
prompt_input_exit``. PRs #48 to #51 were left to the half-hourly cron, which
was measured 105 minutes late that evening and 154 minutes late earlier the
same day, and a conductor armed three of them by hand. Four of five pull
requests took the proxy path this hook exists to replace.

So the set is every ppa-* branch this session's HEAD visited, read from the
reflog and bounded below by the session's own start time. The three candidates
PPA-1417 named were weighed:

* **The reflog, bounded by session start.** Chosen. ``git reflog show HEAD``
  records every ``checkout: moving from A to B`` in this clone with a unix
  timestamp, so it names the branches that were actually worked rather than
  the branches that happen to exist. The lower bound comes from the
  session's own transcript — see ``session_start`` below.
* **The ``ppa-*`` branch prefix on its own.** Rejected: that is a sweep. It
  arms every open ticket pull request in the repository, including one another
  session is still pushing to, which is the PPA-1391 race again and worse.
  ``auto-merge-arm.yml`` may sweep because it holds a 20-minute quiet window;
  this hook fires immediately and holds no such guard.
* **Pull requests authored by the token.** Rejected, and strictly worse than
  the prefix: every session in the estate arms under the same PAT, so the
  token identifies the estate rather than the session. It would sweep and
  claim not to be sweeping.

What this does not separate, stated rather than claimed away: the reflog
belongs to the clone, not to the session. Two sessions running against one
checkout share one HEAD and one reflog, so the time bound narrows the set but
cannot split them. That is not a new exposure — those two sessions already
shared the single branch the old behaviour read — and it is the reason the
bound is the session's start rather than the whole reflog.

A branch the session touched but never pushed has no open pull request. It
costs one lookup, is logged ``no-pull-request``, and nothing waits on it: only
the branch checked out at exit can still be racing ``pr-open.yml``, because it
carries the session's last push, so it is the only one the poll budget is
spent on.

The token is PEECH_AUTOMATION_TOKEN, and there is no fallback
-------------------------------------------------------------
PPA-1278: GitHub suppresses every event raised by ``GITHUB_TOKEN``, so a pull
request armed under it merges without raising the push that triggers
``merge-close-out.yml``, and the ticket strands with nothing in any log saying
why. peech-pmo-automation PR #10 and peech-skills PR #130 stranded five tickets
between them that way. ``gh`` honours ``GH_TOKEN`` and ``GITHUB_TOKEN`` from the
environment and its own stored login otherwise, so this hook sets the first
from the PAT and removes the second rather than letting any of the three
decide. An absent PAT is reported and the sweep arms it later; nothing here
falls back.

It never blocks, and it always reports
---------------------------------------
``SessionEnd`` hooks have no decision control — they cannot stop a session
ending and Claude Code discards their JSON output — so every path returns 0 and
the operator-facing line goes to stderr, which is the one channel a SessionEnd
hook still has. One JSON record per run is appended to
``~/.claude/arm-auto-merge-hook.log``: every run, not only the failures,
because the arm time is the evidence PPA-1407 owes and a log that records only
what went wrong cannot supply it. The log sits outside every repository because
this file is byte-identical across two checkouts and neither wants an untracked
log in its working tree.

The wait for the pull request to exist
---------------------------------------
``pr-open.yml`` opens the pull request on the push, so on a session that exits
seconds after pushing the pull request does not exist yet. The hook polls for
it rather than reporting a miss. In the ordinary case — a session that pushed,
wrote its report, and was then read and closed — the pull request has existed
for minutes and the first lookup finds it, so the hook returns in about two
seconds. BUDGET below caps the unlucky case.

BUDGET is the whole run's, not each branch's. Spending it per branch would
multiply the worst case by the number of tickets in the dispatch and overrun
the SessionEnd timeout, so only the branch checked out at exit polls; every
earlier branch was pushed minutes ago and one lookup settles it.

``SessionEnd`` hooks share a 1.5-second budget by default, and the reference
says the budget is "automatically raised to the highest per-hook timeout
configured in settings files, up to 60 seconds". The ``timeout`` in
settings.json is what buys BUDGET; lowering one without the other silently
truncates the poll.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transition_on_prompt import BRANCH_PREFIXES  # noqa: E402

#: The single credential home for every copy of this hook, and the same
#: absolute path pt_transition.py has held since PPA-1126. One .env is one
#: place to rotate a token; peech-skills has no secrets/ directory and no
#: gitignore entry for one.
CREDENTIALS = Path.home() / "Documents/Claude-Projects/peech-pmo-automation/secrets/.env"
TOKEN_KEY = "PEECH_AUTOMATION_TOKEN"

LOG = Path.home() / ".claude" / "arm-auto-merge-hook.log"

#: Seconds to keep looking for a pull request that pr-open.yml has not opened
#: yet, and the gap between attempts. Must stay under the SessionEnd timeout
#: configured in settings.json — see the note at the end of the docstring.
BUDGET = 45
INTERVAL = 5
#: Per-subprocess ceiling. Small enough that one hung `gh` call cannot eat the
#: whole budget on its own.
CALL_TIMEOUT = 15

_SLUG_RE = re.compile(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")
#: One reflog line as `--format=%gd|%gs --date=unix` renders it, for the
#: checkout entries only. `checkout -b` records the same shape as a plain
#: checkout, so a branch the session created is matched here too.
_CHECKOUT_RE = re.compile(r"^HEAD@\{(\d+)\}\|checkout: moving from (\S+) to (\S+)$")


def log(outcome, **fields):
    """Append one JSON record, and never raise.

    A hook that cannot write its log has nowhere left to report that, and
    raising would turn bookkeeping into a session that will not close.
    """
    record = {
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "outcome": outcome,
        **{k: v for k, v in fields.items() if v not in (None, "")},
    }
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def say(message):
    """The operator-facing line. stderr is all a SessionEnd hook has."""
    print(f"auto-merge arm — {message}", file=sys.stderr)


def run(argv, env=None):
    """subprocess.run that reports a failure instead of raising one.

    A `gh` call that times out mid-poll should cost one attempt, not the whole
    hook: raising here would land in main()'s outer guard and abandon a pull
    request the next attempt would have found.
    """
    try:
        return subprocess.run(
            argv, capture_output=True, text=True,
            timeout=CALL_TIMEOUT, env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 1, "", repr(exc))


def git(root, *args):
    proc = run(["git", "-C", str(root), *args])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def read_token():
    """The PAT out of the one .env, or None.

    Same parse as pt_transition.load_credentials: strip, skip blanks and
    comments, split on the first '=', and unquote.
    """
    if not CREDENTIALS.is_file():
        return None
    for line in CREDENTIALS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key.strip() == TOKEN_KEY:
            return val.strip().strip('"').strip("'") or None
    return None


def gh(token, *args):
    """Run `gh` under the PAT. This is the only place a token reaches a
    subprocess, and GITHUB_TOKEN is removed rather than left to lose a
    precedence contest — see "there is no fallback" above.
    """
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    env.pop("GITHUB_TOKEN", None)
    return run(["gh", *args], env=env)


def find_pr(token, slug, branch):
    """(number, already_armed) for the open pull request on this branch, or
    (None, False) if there is not one yet."""
    proc = gh(token, "pr", "list", "--repo", slug, "--head", branch,
              "--state", "open", "--limit", "1",
              "--json", "number,autoMergeRequest")
    if proc.returncode != 0:
        return None, False
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return None, False
    if not rows:
        return None, False
    return rows[0].get("number"), rows[0].get("autoMergeRequest") is not None


def session_start(payload):
    """Epoch seconds this session began, from its own transcript, or None.

    Claude Code creates the transcript when the session opens and appends to it
    until the session closes, so the file's birth time is the session's start
    and its modification time is very nearly the session's end. Only the first
    is useful as a lower bound.

    None means the bound could not be read — no transcript in the payload, the
    file gone, or a filesystem that records no birth time. The caller then
    falls back to the branch checked out at exit, which is what this hook did
    before PPA-1417: narrower than intended, never wider.
    """
    path = payload.get("transcript_path")
    if not path:
        return None
    try:
        born = getattr(Path(path).stat(), "st_birthtime", None)
    except OSError:
        return None
    return float(born) if born else None


def session_branches(root, started_at, current):
    """Every ppa-* branch this session's HEAD visited, current one first.

    The current branch leads because it carries the session's last push and is
    the only one that can still be racing pr-open.yml; the rest follow
    most-recently-touched first, which is the order they were finished in.

    Both sides of each checkout are taken, and the `from` half earns its place
    on one case only: a branch checked out BEFORE the session began, which the
    session then worked on and moved off. A resumed session and one that opens
    on a ticket branch left over from the last both look like that, and the
    checkout onto the branch sits below the time bound, so the move off it is
    the only entry inside the window that names it at all.

    Within the window the `to` half is sufficient on its own — a branch this
    session checked out is named by its own checkout — so the `from` half never
    widens the set for the ordinary multi-ticket dispatch. Measured, not
    assumed: dropping it leaves a four-branch session's set unchanged at four,
    and takes the inherited-branch case from two branches to one.
    """
    ordered = [current] if current.startswith(BRANCH_PREFIXES) else []
    if started_at is None:
        return ordered
    reflog = git(root, "reflog", "show", "--date=unix", "--format=%gd|%gs", "HEAD")
    for line in reflog.splitlines():
        match = _CHECKOUT_RE.match(line.strip())
        if not match:
            continue
        if int(match.group(1)) < started_at:
            # The reflog is strictly newest-first, so everything below this
            # entry predates the session too.
            break
        for name in (match.group(3), match.group(2)):
            if name.startswith(BRANCH_PREFIXES) and name not in ordered:
                ordered.append(name)
    return ordered


def main():
    try:
        return _arm()
    except Exception as exc:  # noqa: BLE001 — a hook that raises is worse
        log("hook-raised", error=repr(exc))
        return 0


def _arm():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        payload = {}
    reason = payload.get("reason")

    root = os.environ.get("CLAUDE_PROJECT_DIR") or ""
    if not root or not Path(root).is_dir():
        log("no-project-dir", reason=reason, project_dir=root)
        return 0

    current = git(root, "branch", "--show-current")
    branches = session_branches(root, session_start(payload), current)
    if not branches:
        # main, a detached head, or a branch opened by hand, with nothing
        # ticket-shaped in the session's reflog either. Not this route's work,
        # and quiet on purpose: it is the commonest outcome by far.
        log("not-a-ticket-branch", reason=reason, branch=current or "(none)")
        return 0

    slug_match = _SLUG_RE.search(git(root, "remote", "get-url", "origin"))
    if not slug_match:
        log("no-remote", reason=reason, branch=branches[0])
        say(f"{len(branches)} branch(es) not armed — origin has no owner/name "
            "this hook could read.")
        return 0
    slug = slug_match.group(1)

    token = read_token()
    if not token:
        # One record per branch, as everywhere else below, so the log says how
        # many pull requests this cost rather than only that a token was absent.
        for branch in branches:
            log("no-token", reason=reason, branch=branch, repo=slug,
                credentials=str(CREDENTIALS))
        say(f"{', '.join(branches)} not armed — {TOKEN_KEY} is absent from "
            f"{CREDENTIALS}. This hook does not fall back to GITHUB_TOKEN or to "
            "the gh login (PPA-1278); auto-merge-arm.yml's sweep will arm them "
            "within the hour.")
        return 0

    # One deadline for the whole run, spent on branches[0] alone — see BUDGET
    # in the docstring. Every later branch gets a single lookup.
    deadline = time.monotonic() + BUDGET
    for index, branch in enumerate(branches):
        arm_one(token, slug, branch, reason, deadline if index == 0 else None)
    return 0


def arm_one(token, slug, branch, reason, deadline):
    """Arm the open pull request on one branch, and write exactly one record.

    ``deadline`` is a monotonic instant to poll until, or None to take the
    answer from a single lookup. Nothing here raises and nothing returns a
    verdict: each branch is independent, and one that cannot be armed must not
    stop the next from being.
    """
    waited = 0
    while True:
        number, already = find_pr(token, slug, branch)
        if number is not None:
            break
        if deadline is None:
            # Touched but never pushed, or its pull request has already merged.
            log("no-pull-request", reason=reason, branch=branch, repo=slug,
                waited_seconds=0)
            say(f"{branch} not armed — it has no open pull request. Nothing was "
                "pushed from it, or its pull request has already merged.")
            return
        if time.monotonic() >= deadline:
            log("no-pull-request", reason=reason, branch=branch, repo=slug,
                waited_seconds=waited)
            say(f"{branch} not armed — no open pull request after {waited}s. "
                "pr-open.yml may still be running; the sweep will arm it.")
            return
        time.sleep(INTERVAL)
        waited += INTERVAL

    if already:
        log("already-armed", reason=reason, branch=branch, repo=slug, pr=number)
        return

    proc = gh(token, "pr", "merge", str(number), "--repo", slug,
              "--auto", "--squash")
    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip() or "no output")[-600:]
        log("arm-failed", reason=reason, branch=branch, repo=slug, pr=number,
            exit_code=proc.returncode, stderr=proc.stderr, stdout=proc.stdout)
        say(f"could not arm #{number} on {branch}; the sweep will try again.\n{detail}")
        return

    log("armed", reason=reason, branch=branch, repo=slug, pr=number,
        waited_seconds=waited)
    say(f"#{number} armed on {branch}. The required checks decide the merge; "
        "this hook does not merge anything.")


if __name__ == "__main__":
    sys.exit(main())
