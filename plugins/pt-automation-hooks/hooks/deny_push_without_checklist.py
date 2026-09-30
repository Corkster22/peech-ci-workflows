#!/usr/bin/env python3
"""PreToolUse hook (PPA-1626) - refuse a ticket-branch push before its checklist.

delegation.md orders the close-out commit, post the checklist, push (PPA-1625),
because the push lets the pull request merge and the merge grades whatever
checklist is already on the ticket. Three merges landed first anyway: on
18-SEP-2026 (PPA-1505, PPA-1541) and twice on 23-SEP-2026 (PR #128, PR #130),
each holding finished tickets and posting a held notice that meant nothing. A
written order depends on each session remembering it, so this fires on the push.

What it checks
--------------
A Bash call running ``git push`` of a ``ppa-*`` branch is denied while any key
the session was dispatched with carries no Jira comment that yields rows
through ``pr_merge_close_out.checklist_comments`` - ``stated_rows`` over the
comment's ADF lines, the same read the merge grades with. The deny reason names
each such key and the two shapes that extractor reads.

Allowed without a Jira read: a branch not named ``ppa-*``, a push whose head
commit is the session-pause ``wip:`` commit pt-session-lifecycle defines, and a
session that dispatched nothing. Once a checklist exists every push passes, so
a fix push after a correction is never held.

It never blocks on its own outage
---------------------------------
A Jira read that fails or runs past its budget allows the push and says so in a
``systemMessage``, as a missing peech-ci-workflows clone does. Each read carries
``JIRA_TIMEOUT`` and the reads together stop at ``BUDGET``, both shorter than
the 30-second timeout hooks.json declares, so a slow Jira returns an allow
rather than a killed hook.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refresh_ci_workflows import CLONE_SCRIPTS  # noqa: E402

# The one copy of pr_merge_close_out.py, in the peech-ci-workflows clone
# (PPA-1605), beside the one copy of pt_transition.py it imports (PPA-1662).
# Checked here before grade_definition_of_done is imported, because that module
# prints its own Stop-worded warning and exits when the clone is missing.
CLOSE_OUT = CLONE_SCRIPTS / "pr_merge_close_out.py"
if not CLOSE_OUT.is_file():
    print(json.dumps({"systemMessage": (
        f"pt-automation-hooks: {CLOSE_OUT} is missing, so the push was not "
        "checked for a close-out checklist. Clone peech-ci-workflows to that "
        "path.")}))
    sys.exit(0)
sys.path.append(str(CLOSE_OUT.parent))

# noqa: E402 below - the sys.path inserts above have to run first.
from grade_definition_of_done import (  # noqa: E402
    SHAPES,
    jira_get,
    session_keys,
    transcript_records,
)
from pr_merge_close_out import checklist_comments  # noqa: E402

#: Seconds allowed for one Jira read, and for all of them together. Both sit
#: under the 30-second timeout hooks.json declares for this hook.
JIRA_TIMEOUT = 8
BUDGET = 20

#: ``git push`` at the head of a command segment, through any ``-C <dir>`` or
#: ``-c <key=value>`` git options ahead of the subcommand.
_PUSH_RE = re.compile(
    r"(?:^|[;&|(]\s*|\n\s*)git((?:\s+-[cC]\s+\S+)*)\s+push\b([^;&|\n)]*)")


def push_args(command):
    """(git's -C directory or None, the push's arguments) or None where the
    command runs no ``git push``."""
    match = _PUSH_RE.search(command)
    if not match:
        return None
    options = shlex.split(match.group(1))
    directory = next((options[i + 1] for i, opt in enumerate(options[:-1])
                      if opt == "-C"), None)
    return directory, shlex.split(match.group(2))


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=5).stdout.strip()


def pushed_ref(args, cwd):
    """(local ref, remote branch) this push sends.

    An explicit refspec - ``git push origin ppa-1`` or ``src:dst`` - names both.
    Otherwise it is the current branch, the one ``git push`` and ``git push -u
    origin HEAD`` send.
    """
    positional = [a for a in args if not a.startswith("-")]
    if len(positional) >= 2:
        src, _, dst = positional[1].lstrip("+").partition(":")
        src = src or "HEAD"
        dst = dst or (git(cwd, "rev-parse", "--abbrev-ref", src)
                      if src == "HEAD" else src)
        return src, dst.removeprefix("refs/heads/")
    return "HEAD", git(cwd, "rev-parse", "--abbrev-ref", "HEAD")


def is_wip(ref, cwd):
    """True when the head commit is pt-session-lifecycle's pause commit."""
    return git(cwd, "log", "-1", "--format=%s", ref).lower().startswith("wip:")


def keys_without_checklist(keys, get=jira_get, clock=time.monotonic):
    """Each key whose Jira comments state no checklist row. Raises on any
    failed read, and TimeoutError once ``BUDGET`` is spent."""
    deadline = clock() + BUDGET
    missing = []
    for key in keys:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(f"the {BUDGET}s Jira budget ran out before {key}")
        body = get(f"/issue/{key}/comment?maxResults=100",
                   timeout=min(JIRA_TIMEOUT, remaining))
        if not checklist_comments(body.get("comments")):
            missing.append(key)
    return missing


def deny(branch, missing):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"Push guard (PPA-1626): {branch} is not pushed yet, because "
            f"{', '.join(missing)} carries no close-out checklist in Jira. The "
            "push lets the pull request merge, and the merge grades the "
            "checklist already on the ticket, so the order is commit, post the "
            "checklist, push. Post the checklist on each key named, citing the "
            "local commit hash, then push again. The extractor reads two shapes "
            "and no others:\n" + SHAPES)}}


def warn(why):
    return {"systemMessage": (
        f"pt-automation-hooks push guard: {why}, so the push was allowed "
        "without checking for a close-out checklist.")}


def decide(payload, get=jira_get):
    """The hook output to print, or None to allow silently."""
    command = (payload.get("tool_input") or {}).get("command") or ""
    parsed = push_args(command)
    if parsed is None:
        return None
    directory, args = parsed
    # Dropped (PPA-1626): "cd <dir> && git push" is read from the session's cwd,
    # not <dir>, because following cd means interpreting shell. What breaks if
    # it is never fixed: a push written that way from a cwd off a ppa-* branch
    # skips the check and the merge holds the ticket, as it did before this.
    cwd =str(Path(payload.get("cwd") or os.getcwd(), directory or "."))
    ref, branch = pushed_ref(args, cwd)
    if not branch.startswith("ppa-") or is_wip(ref, cwd):
        return None
    try:
        keys, _ = session_keys(transcript_records(payload.get("transcript_path")))
    except OSError as exc:
        return warn(f"the transcript could not be read ({exc.__class__.__name__})")
    if not keys:
        return None
    try:
        missing = keys_without_checklist(keys, get)
    except Exception as exc:  # noqa: BLE001 - a failed read allows, with a warning
        return warn(f"reading Jira comments failed ({exc!r})")
    return deny(branch, missing) if missing else None


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        output = decide(payload)
    except Exception as exc:  # noqa: BLE001 - the guard never blocks on itself
        output = warn(f"the guard raised {exc!r}")
    if output:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
