#!/usr/bin/env python3
"""SessionStart hook (PPA-1872) - delete local branches whose pull requests all merged.

pt-session-lifecycle Step 6B asks for this cleanup before new work starts, and
nothing enforced it: a branch cut from a stale base conflicts once that base
squash-merges (pt-git-routing, Branch Hygiene After a Squash Merge). SessionStart
fires on startup, resume, clear and compact, so this runs before every dispatch.

The test is the pull request, not git ancestry, because a squash merge leaves
``git branch --merged main`` empty. A branch goes only when
``gh pr list --head <branch> --state all`` returns at least one pull request and
every one shows MERGED. An open, closed-unmerged or absent pull request keeps it,
because it may hold work that never reached main. So does any GitHub failure.

Never deleted: ``main``, the checked-out branch, a branch another worktree holds.
Only local branches go. No remote branch, worktree or working folder is touched,
and no branch is switched. Each deletion is one line in ``LOG`` naming the branch
and its last commit, so ``git branch <branch> <sha>`` restores it.

Acts only when the working folder is one of the four Peech repositories. Fail
open: exits 0 on every path and prints nothing, because SessionStart stdout is
injected into the model's context. ``DEADLINE`` stops the GitHub calls before the
``hooks.json`` timeout (30 s).
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPOSITORIES = ("peech-pmo-automation", "peech-skills", "peech-org-skills",
                "peech-ci-workflows")
ROOT = Path.home() / "Documents" / "Claude-Projects"
LOG = Path.home() / ".claude" / "pt-branch-cleanup-hook.log"
DEADLINE = 20
KEEP = "main"


class DeadlineReached(Exception):
    pass


def run(args, cwd, started):
    """Run a command in ``cwd`` and return its stdout; raises on failure or timeout."""
    left = DEADLINE - (time.monotonic() - started)
    if left <= 0:
        raise DeadlineReached
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=left, check=True)
    return done.stdout


def log(line):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as handle:
            handle.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")
    except OSError:
        pass


def repository(cwd):
    """The repository root when ``cwd`` is inside one of the four, else None."""
    folder = Path(cwd).resolve()
    for name in REPOSITORIES:
        root = (ROOT / name).resolve()
        if folder == root or root in folder.parents:
            return root
    return None


def held_elsewhere(root, started):
    """Branches any worktree has checked out, the current one included."""
    out = run(["git", "worktree", "list", "--porcelain"], root, started)
    return {line.split("refs/heads/", 1)[1] for line in out.splitlines()
            if line.startswith("branch refs/heads/")}


def all_merged(root, branch, started):
    """True only for a non-empty pull request list that is entirely MERGED."""
    states = json.loads(run(["gh", "pr", "list", "--head", branch, "--state", "all",
                             "--json", "state"], root, started))
    return bool(states) and all(item["state"] == "MERGED" for item in states)


def clean(root):
    started = time.monotonic()
    held = held_elsewhere(root, started)
    names = run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
                root, started).split()
    for branch in names:
        if branch == KEEP or branch in held:
            continue
        try:
            if not all_merged(root, branch, started):
                continue
            sha = run(["git", "rev-parse", branch], root, started).strip()
            run(["git", "branch", "-D", branch], root, started)
            log(f"{root.name} deleted {branch} {sha}")
        except DeadlineReached:
            raise
        except Exception as exc:  # noqa: BLE001 - keep this branch, try the next
            log(f"{root.name} kept {branch}: {type(exc).__name__}")


def main():
    try:
        try:
            payload = json.load(sys.stdin)
        except ValueError:
            payload = {}
        root = repository(payload.get("cwd") or Path.cwd())
        if root:
            clean(root)
    except DeadlineReached:
        log("deadline reached; the next start continues")
    except Exception as exc:  # noqa: BLE001 - fail open on every path
        log(f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
