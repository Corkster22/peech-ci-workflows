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
the session was dispatched with has a Definition of Done condition that pairs
with no stated verdict in its Jira close-out. The grade is
``pr_merge_close_out.build_table`` - the same pairing and the same selection
of comments the merge close-out applies (PPA-1765) - so the push is refused for
exactly the close-out the merge would hold. A condition stated NOT MET is
paired, and is the merge's call to hold, not this guard's. The deny reason
names each such key, each unpaired condition's number and text, the two shapes
the extractor reads, and that the Jira close-out comment is the thing to fix.

A key whose Definition of Done is empty keeps the PPA-1626 test: at least one
comment stating a row.

Allowed without a Jira read: a branch not named ``ppa-*``, a push whose head
commit is the session-pause ``wip:`` commit pt-session-lifecycle defines, and a
session that dispatched nothing. A fix push after a correction passes once
every condition pairs.

A Jira read that fails denies the push
--------------------------------------
Decision 1A, 01-OCT-2026: a gate that lets a push through on an error is not a
gate. A Jira read that fails or runs past its budget denies the push and prints
the error and the key being read. Each read carries ``JIRA_TIMEOUT`` and the
reads together stop at ``BUDGET``, both shorter than the 30-second timeout
hooks.json declares, so a slow Jira returns a deny rather than a killed hook.

Three things still allow with a ``systemMessage``, because none is a Jira
read: a missing peech-ci-workflows clone, an unreadable transcript, and the
guard raising on a fault of its own. The last is ``main``'s outer guard, which
runs for every Bash call, so denying there would block commands that are not
pushes. Dropped (PPA-1765): a fault in this file therefore fails open, visibly.
What breaks if it is never fixed: the push passes with the warning, as it did
before this change, and the merge grades the close-out as it always has.
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
from transition_on_prompt import BRANCH_PREFIXES  # noqa: E402

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
    DOD_FIELD,
    SHAPES,
    jira_get,
    session_keys,
    transcript_records,
)
from pr_merge_close_out import (  # noqa: E402
    UNSTATED,
    build_table,
    checklist_comments,
)

#: Seconds allowed for one Jira read, and for all of them together. Both sit
#: under the 30-second timeout hooks.json declares for this hook.
JIRA_TIMEOUT = 8
BUDGET = 20

#: Printed verbatim in every refusal (PPA-1765 Amendment 2). A gate demanding
#: one-word verdicts pushes a session to write a bare MET over a qualified one,
#: and that would let a ticket close itself with a ruling still open.
VERDICT_RULE = (
    "If a condition is fully met, write MET. If it carries a qualification or "
    "awaits a ruling, write NOT MET and put the reason in the evidence.")

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


class ReadFailed(Exception):
    """A Jira read failed. Carries the key being read and the error."""

    def __init__(self, key, error):
        super().__init__(f"{key}: {error!r}")
        self.key = key
        self.error = error


def gaps_in(key, issue):
    """(absent, [(number, text)]) for one key, or None where it is complete.

    ``absent`` is True where no comment states a row at all. The list is each
    condition the close-out leaves with no stated verdict; with ``absent`` it
    is every condition.
    """
    fields = issue.get("fields") or {}
    comments = (fields.get("comment") or {}).get("comments")
    table = build_table(fields.get(DOD_FIELD), comments, key)
    if not table.conditions:
        # Empty Definition of Done: nothing to pair, so today's test stands.
        return None if checklist_comments(comments) else (True, [])
    if table.absent:
        return True, list(enumerate(table.conditions, 1))
    unpaired = [(n, text) for n, text, verdict in table.rows
                if verdict == UNSTATED]
    return (False, unpaired) if unpaired else None


def keys_with_gaps(keys, get=jira_get, clock=time.monotonic):
    """[(key, absent, unpaired conditions)] for each key the close-out leaves
    short. Raises ``ReadFailed`` on any failed read, and on ``BUDGET`` spent."""
    deadline = clock() + BUDGET
    found = []
    for key in keys:
        remaining = deadline - clock()
        if remaining <= 0:
            raise ReadFailed(key, TimeoutError(
                f"the {BUDGET}s Jira budget ran out before {key}"))
        try:
            issue = get(f"/issue/{key}?fields=comment,{DOD_FIELD}",
                        timeout=min(JIRA_TIMEOUT, remaining))
        except Exception as exc:  # noqa: BLE001 - any failed read denies, naming the key
            raise ReadFailed(key, exc) from exc
        gap = gaps_in(key, issue)
        if gap:
            found.append((key, *gap))
    return found


def gap_lines(key, absent, conditions):
    head = (f"{key} carries no close-out checklist in Jira." if absent
            else f"{key} leaves a Definition of Done condition with no stated "
                 "verdict in its Jira close-out comment:")
    return "\n".join([head, *(f"  {n}. {text}" for n, text in conditions)])


def decision(reason):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}


def deny(branch, gaps):
    return decision(
        f"Push guard (PPA-1626, PPA-1765): {branch} is not pushed yet. The push "
        "lets the pull request merge, and the merge grades the close-out "
        "comment already on each ticket, so every Definition of Done condition "
        "needs a row with a stated verdict first. The order is commit, post the "
        "checklist, push.\n\n"
        + "\n\n".join(gap_lines(*gap) for gap in gaps)
        + "\n\nThe Jira close-out comment is the thing to fix, not the chat "
        "text. Post the corrected checklist on each key named, citing the local "
        "commit hash, then push again. The extractor reads two shapes and no "
        "others:\n" + SHAPES + "\n" + VERDICT_RULE)


def deny_read(branch, failure):
    return decision(
        f"Push guard (PPA-1765): {branch} is not pushed, because the Jira read "
        f"for {failure.key} failed: {failure.error!r}. A guard that lets a push "
        "through on a read error is not a guard (Decision 1A, 01-OCT-2026). "
        "Fix the read, then push again.")


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
    if not branch.startswith(BRANCH_PREFIXES) or is_wip(ref, cwd):
        return None
    # Dropped (PPA-1765): the keys graded are the session's dispatched keys, the
    # set PPA-1626 already used, not every key a commit on the branch names. What
    # breaks if it is never fixed: a key named on the branch but never dispatched
    # in this session is first graded by the merge, which holds it, as before.
    try:
        keys, _ = session_keys(transcript_records(payload.get("transcript_path")))
    except OSError as exc:
        return warn(f"the transcript could not be read ({exc.__class__.__name__})")
    if not keys:
        return None
    try:
        gaps = keys_with_gaps(keys, get)
    except ReadFailed as failure:
        return deny_read(branch, failure)
    return deny(branch, gaps) if gaps else None


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
