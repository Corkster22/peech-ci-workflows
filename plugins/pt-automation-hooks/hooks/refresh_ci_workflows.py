#!/usr/bin/env python3
"""SessionStart hook (PPA-1662) - keep the peech-ci-workflows clone current.

The plugin's hooks read scripts from one local clone of peech-ci-workflows:
``pr_merge_close_out.py`` since PPA-1605, and ``pt_transition.py`` since
PPA-1581 made that repository its one home and PPA-1662 retired the copy here.
A clone behind ``origin/main`` runs old behaviour in every repository at once,
and nothing else compares it, so this checks at the start of each session.

What it does, in order, and it never blocks a session:

* **No clone.** Warns, naming the path to clone to. Every hook reading it
  already warns and passes on its own; this says so once, up front.
* **Fetch fails.** Warns that freshness was not checked. Offline is ordinary.
* **Matches origin/main.** Silent. Compared by tree, not by ancestry: every
  change squash-merges, so a clone left on a merged ``ppa-*`` branch carries
  the same content as ``origin/main`` under a commit that is not its ancestor.
* **On main, clean, behind.** Fast-forwards, silently.
* **Anything else that differs.** Warns, naming the branch and why it was not
  updated. Moving a branch someone is working on, or a dirty tree, is the
  operator's call and not a session start's.

The warning rides out as ``systemMessage`` JSON, as the other hooks' do.
"""

import json
import subprocess
import sys
from pathlib import Path

#: The clone every hook reads shared scripts from. Named once, here.
CLONE = Path.home() / "Documents" / "Claude-Projects" / "peech-ci-workflows"
CLONE_SCRIPTS = CLONE / "scripts"

#: Seconds for any one git call. Well inside the hook's own timeout.
GIT_TIMEOUT = 20


def git(*args):
    """Run git in the clone. Returns the completed process; never raises on exit."""
    return subprocess.run(["git", "-C", str(CLONE), *args], capture_output=True,
                          text=True, timeout=GIT_TIMEOUT)


def freshness():
    """The warning to show, or None when the clone is current or was updated."""
    if not (CLONE / ".git").exists():
        return (f"{CLONE} is missing, so pt_transition.py and "
                "pr_merge_close_out.py cannot be read and the hooks that use "
                f"them warn and pass. Clone peech-ci-workflows to {CLONE}.")

    fetched = git("fetch", "--quiet", "origin", "main")
    if fetched.returncode != 0:
        return (f"{CLONE} was not checked against origin/main - git fetch "
                f"failed: {fetched.stderr.strip() or fetched.returncode}")

    if git("diff", "--quiet", "HEAD", "origin/main").returncode == 0:
        return None

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    behind = git("merge-base", "--is-ancestor", "HEAD", "origin/main").returncode == 0
    if branch == "main" and not dirty and behind:
        merged = git("merge", "--ff-only", "--quiet", "origin/main")
        if merged.returncode == 0:
            return None
        return (f"{CLONE} lags origin/main and the fast-forward failed: "
                f"{merged.stderr.strip() or merged.returncode}")

    reason = ("its working tree has uncommitted changes" if dirty
              else f"it is on {branch!r}, not main" if branch != "main"
              else "main has diverged from origin/main")
    return (f"{CLONE} differs from origin/main and was not updated, because "
            f"{reason}. The hooks read its scripts as they stand.")


def main():
    """Always returns 0. A session start is never refused over this."""
    try:
        message = freshness()
    except Exception as exc:  # noqa: BLE001 - a hook that raises is worse
        message = f"{CLONE} freshness was not checked: {exc!r}"
    if message:
        print(json.dumps({"systemMessage": f"pt-automation-hooks: {message}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
