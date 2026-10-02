#!/usr/bin/env python3
"""SessionStart hook (PPA-1774) - post the turns earlier sessions left unposted.

The Stop hook (``log_turn_worklog.py``) posts each turn at the next Stop,
because Claude Code writes a turn's ``turn_duration`` row about 3 ms after that
turn's Stop hooks finish. A session's final turn has no next Stop, so it stayed
off the timesheet until someone ran PPA-1756's catch-up script: the batch 01
session's single 29m50s turn on 01-OCT-2026. This hook closes that gap. When a
new session starts, it posts every turn from earlier sessions that Tempo does
not yet show, with no scheduler and no manual step (Decision 2A, 01-OCT-2026).

Which sessions
--------------
Only sessions whose working folder was one of the four Peech repositories
(PPA-1654 comment 30789), and only turns ending on or after the Stop hook's
``CUTOFF``. The folder is read from the transcript's project directory, which
Claude Code names from the launch folder, so a scratch session elsewhere is not
swept. Every start source fires it: startup, resume, clear and compact. Claude
Code's hook documentation lists ``startup`` for a fresh launch and ``clear`` for
``/clear``, and both fire SessionStart.

One code path
-------------
The parser, dispatch-key mapping, even split, 360-second rounding, tag check
and alerts are ``log_turn_worklog``'s, called through ``sweep``. This file adds
only the choice of sessions. A turn either hook posted is tagged in Tempo, so
the other skips it.

Running out of time is a clean stop - PPA-1774 rework
-------------------------------------------------------
The first live run, 02-OCT-2026 13:44, swept 122 sessions and 124 distinct keys.
Each key costs a Jira id lookup and a Tempo read, about 250 sequential requests
before the first post, against the 25-second ``DEADLINE``. It swept oldest first, spent
the budget on old sessions and alerts, hit the deadline, logged it as a failed
alert, and posted nothing; the next start began again from the oldest session.

So a run now keeps its progress in ``SWEPT`` (``~/.claude/pt-turn-worklog-swept.json``):

* ``sessions`` maps a session id to the transcript size when that session was
  last settled. A session whose file has not grown is skipped without a request,
  and one that has grown is swept again, so a session that gains turns is not lost.
* ``ids`` maps a key to its Jira issue id, which never changes.

Sessions are swept newest first, because the newest holds the final turn this hook
exists to post. When ``DEADLINE`` is reached the run stops without an alert, writes
one log line, and keeps every post already made. A post is tagged in Tempo, so the
next start finds it and posts nothing twice, and it continues with the sessions
not yet settled. A session counts as settled only when every part is in Tempo and
any no-key alert is recorded as sent, so a failure is retried rather than lost.

Dropped (PPA-1774): the first start after install sends one message for each
earlier session since ``CUTOFF`` that had a ticketless turn - 14 of 119 swept
sessions on 02-OCT-2026 - because the ticket asks for one message per session
per reason and the alert record starts empty. What breaks if this is never
fixed: about fourteen direct messages once, then none for those sessions.

Fail open
---------
This hook never blocks a session start and exits 0 on every path. It prints
nothing, because SessionStart stdout would be injected into the model's context.
``log_turn_worklog.DEADLINE`` stops its HTTP calls before ``hooks.json``'s
timeout, and work left at the deadline is picked up at the next start. It never
edits or deletes a worklog.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import log_turn_worklog as worklog  # noqa: E402

REPOSITORIES = ("peech-pmo-automation", "peech-skills", "peech-org-skills",
                "peech-ci-workflows")
PROJECTS = Path.home() / ".claude" / "projects"
SWEPT = Path.home() / ".claude" / "pt-turn-worklog-swept.json"


def project_dirs():
    """Claude Code's project directory names for the four repositories.

    It names a directory from the launch folder with every character outside
    letters and digits replaced by a dash.
    """
    return {re.sub(r"[^A-Za-z0-9]", "-", str(Path.home() / "Documents"
                                             / "Claude-Projects" / name))
            for name in REPOSITORIES}


def transcripts():
    """Session files under the four repositories' project directories that were
    written on or after the cutoff, newest first."""
    allowed = project_dirs()
    found = [path for folder in PROJECTS.glob("*") if folder.name in allowed
             for path in folder.glob("*.jsonl")
             if path.stat().st_mtime >= worklog.CUTOFF.timestamp()]
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)


def load_progress():
    """{"sessions": {id: size}, "ids": {key: issue id}}; empty where unreadable."""
    try:
        kept = json.loads(SWEPT.read_text())
        return {"sessions": dict(kept["sessions"]), "ids": dict(kept["ids"])}
    except (OSError, ValueError, KeyError, TypeError):
        return {"sessions": {}, "ids": {}}


def save_progress(progress):
    """Write the ledger. A failure is logged and never stops the run."""
    try:
        SWEPT.parent.mkdir(parents=True, exist_ok=True)
        SWEPT.write_text(json.dumps(progress))
    except OSError as exc:
        worklog.log("session-start", f"progress not saved: {type(exc).__name__}: {exc}")


def main():
    try:
        json.load(sys.stdin)  # the payload is read for its shape only
    except ValueError:
        pass
    progress = load_progress()
    swept = 0
    try:
        queue = []
        for path in transcripts():
            size = path.stat().st_size
            if progress["sessions"].get(path.stem) == size:
                continue
            marked = worklog.windowed(path)
            if worklog.needs_work(path.stem, marked):
                queue.append((path, size, marked))
            else:
                progress["sessions"][path.stem] = size  # nothing to post or report
        if queue:
            env = worklog.load_env(worklog.CREDENTIALS)
            poster = worklog.Poster(env, progress["ids"])
            try:
                if poster.is_sean():
                    alerts = worklog.Alerts(env)
                    for path, size, marked in queue:
                        try:
                            if worklog.sweep(poster, alerts, path.stem, marked):
                                progress["sessions"][path.stem] = size
                                swept += 1
                                save_progress(progress)
                        except OSError:
                            raise  # network or timeout: end the run, the next start retries
                        except Exception as exc:  # noqa: BLE001 - one session's own data
                            worklog.log(path.stem, f"{type(exc).__name__}: {exc}")
            finally:
                progress["ids"] = poster.ids
    except worklog.DeadlineReached:
        worklog.log("session-start",
                    f"deadline reached after {swept} sessions settled; the next start continues")
    except Exception as exc:  # noqa: BLE001 - fail open on every path
        worklog.log("session-start", f"{type(exc).__name__}: {exc}")
    save_progress(progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
