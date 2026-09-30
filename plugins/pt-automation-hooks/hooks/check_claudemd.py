#!/usr/bin/env python3
"""Stop hook (PPA-793) — grade the CLAUDE.md files this session touched.

A rule a session must remember to run still depends on memory, which is the
failure the conformance checker exists to close. Wiring it here makes the gate
fire without anyone deciding to run it (ruling ENFORCEMENT). pytest carries the
same checker as a regression backstop; neither is sufficient alone.

Touched set
-----------
Derived from git the same three ways as ``run_touched_tests.py``, because the
Stop payload carries no list of edited paths:

1. ``git diff --name-only HEAD`` — working tree and index, where a session's
   edits sit before it commits.
2. ``git ls-files --others --exclude-standard`` — untracked new files.
3. ``git diff --name-only <upstream>...HEAD`` — committed but unpushed.
   PPA-1256 made the branch commit part of a session's own close-out, so
   this is the normal shape at the end of a run.

Only CLAUDE.md files, and only files that still exist, are graded.

Verdict files are not in the touched set and cannot be. PPA-1125 moved the
Tier C archive outside every repo, so no verdict edit ever appears in a git
listing of this one. Editing a verdict therefore does not re-grade the
CLAUDE.md it governs; run the checker by hand for that
(``python3 scripts/check_claudemd.py --tiers c``).

Scope — touched files, never the whole repo
-------------------------------------------
Grading every CLAUDE.md on every stop would block every session in the repo
until the last per-file rebuild ticket under epic PPA-789 lands. Scoping to the
touched set means a session that edits a CLAUDE.md is held to the rules for
that file, and a session that does not touch one is not.

Exit codes
----------
Three codes, and no code carries both a verdict and an operational failure
(PPA-1355). The command string in ``.claude/settings.json`` maps 3 to 2, so a
stop is blocked either way; the split exists so the reader is told which
happened.

0 — verdict. Nothing touched, or the touched files pass.
2 — verdict. A FAIL or GATE_STOP finding on a touched file. Blocks the stop.
3 — operational. The gate did not run: the checker could not be started, exited
    on a code it does not produce deliberately, exited 1 or 2 without printing a
    verdict line, or this script itself raised.
"""
import contextlib
import os
import subprocess
import sys
import traceback
from pathlib import Path

# Path resolution for the pt-automation-hooks plugin copy (PPA-1586). The
# repository files this reads resolve from the session's project root, as in
# transition_on_prompt.py. The docstring above still describes the
# peech-pmo-automation layout; it is kept byte for byte so the diff against
# that file stays path resolution alone.
REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
BLOCK = 2
NO_VERDICT = 3

#: The three lines ``cc.render`` closes its report with, one of which is always
#: the last line of a run that reached a verdict.
VERDICT_PREFIXES = ("GATE FAILED", "GATE STOPPED", "GATE PASSED")


def has_verdict(stdout):
    """True when the checker printed one of ``render``'s closing lines.

    ``render`` builds the whole report and prints it in one call, so the line is
    there whenever the checker reached a verdict and absent whenever it died on
    the way. This is what separates a FAIL from a traceback, since both exit 1,
    and an argparse usage error from a GATE_STOP, since both exit 2. Same
    discriminator ``transition_on_prompt.py`` applies to its own subprocess.
    """
    return any(line.startswith(VERDICT_PREFIXES) for line in stdout.splitlines())


def git(*args):
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return r.stdout.splitlines() if r.returncode == 0 else []


def changed_paths():
    paths = set()
    paths.update(git("diff", "--name-only", "HEAD"))
    paths.update(git("ls-files", "--others", "--exclude-standard"))
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream:
        paths.update(git("diff", "--name-only", f"{upstream[0]}...HEAD"))
    return {p.strip() for p in paths if p.strip()}


def claudemd_targets(paths):
    """The CLAUDE.md files these changed paths implicate."""
    targets = {REPO / p for p in map(Path, paths) if p.name == "CLAUDE.md"}
    return sorted(t for t in targets if t.is_file())


def python_bin():
    venv = REPO / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def main():
    # Drain the payload so the writer never sees a broken pipe.
    with contextlib.suppress(Exception):
        sys.stdin.read()

    if not (REPO / ".git").exists():
        # Kept, with the reason recorded (PPA-1355). This is an early-out, not a
        # decision: with .git absent every git() call returns [], so the touched
        # set below is empty and the no-targets return fires anyway. Verified by
        # pointing REPO at a directory with no .git — changed_paths() returned
        # set(). Returning NO_VERDICT here would block every stop in a non-git
        # checkout, including stops that touched no CLAUDE.md, and would still
        # not close the real hole: git() swallows an OSError and a non-zero exit
        # and reports an empty touched set, which is reachable with .git present
        # (git absent from PATH, a corrupt repo). That one is reported, not
        # fixed, here.
        return 0

    targets = claudemd_targets(changed_paths())
    if not targets:
        return 0

    cmd = [python_bin(), "-m", "peech_shared.jobs.claudemd_conformance"]
    for t in targets:
        cmd += ["--file", str(t)]
    try:
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    except OSError as exc:
        sys.stderr.write(
            "Stop blocked — the CLAUDE.md conformance checker could not be "
            f"started ({exc}). The gate did not run.\n"
        )
        return NO_VERDICT

    # The success set stays exactly {0} (PPA-1354).
    if proc.returncode == 0:
        return 0

    # A verdict code needs the verdict line to go with it. 1 and 2 each carry a
    # rule verdict and an operational failure — 1 is a FAIL and every traceback,
    # 2 is a GATE_STOP and every argparse usage error — and the line is what
    # tells them apart (PPA-1355).
    if proc.returncode in (1, 2) and has_verdict(proc.stdout):
        sys.stderr.write(
            "Stop blocked — CLAUDE.md conformance findings on the files this session touched.\n"
            "Fix them, or explain why each stands, before ending the session.\n\n"
            + proc.stdout
            + proc.stderr
            + "\n"
        )
        return BLOCK

    sys.stderr.write(
        "Stop blocked — the CLAUDE.md conformance checker did not run "
        f"(exit {proc.returncode}, no verdict line printed). Fix the checker, "
        "or explain why the gate cannot grade, before ending the session.\n"
        f"{(proc.stdout + proc.stderr)[-2000:]}\n"
    )
    return NO_VERDICT


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # An unhandled exception is an operational failure, not a verdict, so it
        # takes NO_VERDICT with the rest (PPA-1355). The traceback goes out
        # first: the code says the gate did not run, the traceback says why.
        traceback.print_exc()
        sys.stderr.write(
            "Stop blocked — check_claudemd.py raised. The CLAUDE.md gate did "
            "not run.\n"
        )
        sys.exit(NO_VERDICT)
