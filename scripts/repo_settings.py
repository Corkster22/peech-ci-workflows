#!/usr/bin/env python3
"""Check, or apply, every repository's GitHub settings from repo-settings.json.

PPA-1632. Repository settings are not code, so the shared workflows cannot
carry them, and until this file they differed by hand across the four
repositories with nothing reporting it. On 23-SEP-2026 PR #33 in
peech-org-skills merged with no required check, because that repository has
none (PPA-1071 comment 29989). Ruled 23-SEP-2026, Decision 3A: one settings
file and one script, no new tools and no copies. safe-settings and Terraform
were considered and rejected as too large for four repositories.

repo-settings.json at the repository root is the single source. Each entry
names the default-branch protection and the repository merge settings. An
entry carrying blocked_by is not read and not written: every setting prints
BLOCKED with the ticket, and the settings it records are the ones intended for
the day the block lifts, so that day needs only --apply.

With no flag, or with --check, the script reads each repository's live
settings and prints one line per setting: MATCH, DRIFT with the live and file
values, or BLOCKED with its ticket. It exits 1 on any DRIFT. --apply writes the
file's values to every repository not marked blocked, then re-reads and prints
the same lines. Only --apply writes. The gh CLI does the reading and writing,
under whatever account `gh auth` holds, so reading protection needs admin
access to each repository.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "repo-settings.json"

PROTECTION = ("pull_request_required", "required_approving_review_count",
              "required_status_checks", "strict", "enforce_admins")
MERGE = ("allow_auto_merge", "allow_squash_merge", "delete_branch_on_merge")


class GhError(RuntimeError):
    """A gh api call exited non-zero. The message carries gh's own output."""


def run_gh(method, path, body=None):
    """Call `gh api` and return the parsed JSON response, or None if empty."""
    cmd = ["gh", "api", "-X", method, path]
    if body is not None:
        cmd += ["--input", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          input=None if body is None else json.dumps(body))
    if proc.returncode != 0:
        raise GhError(f"gh api -X {method} {path}: "
                      f"{(proc.stderr or proc.stdout).strip()}")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def load_settings(path=SETTINGS_FILE):
    return json.loads(Path(path).read_text())


def read_live(gh, repo, branch):
    """Return every setting's live value, keyed as the file keys it.

    An unprotected branch reads as protection with nothing required, so every
    protection setting the file asks for reports DRIFT rather than an error.
    """
    repo_json = gh("GET", f"repos/{repo}")
    live = {name: repo_json[name] for name in MERGE}
    try:
        prot = gh("GET", f"repos/{repo}/branches/{branch}/protection")
    except GhError as exc:
        if "Branch not protected" not in str(exc):
            raise
        prot = {}
    reviews = prot.get("required_pull_request_reviews")
    checks = prot.get("required_status_checks") or {}
    live.update(
        pull_request_required=reviews is not None,
        required_approving_review_count=(
            reviews["required_approving_review_count"] if reviews else None),
        required_status_checks=sorted(checks.get("contexts", [])),
        strict=checks.get("strict", False),
        enforce_admins=prot.get("enforce_admins", {}).get("enabled", False),
    )
    return live


def wanted(entry):
    """Flatten one file entry into the same shape read_live() returns."""
    values = {**entry["protection"], **entry["merge"]}
    values["required_status_checks"] = sorted(values["required_status_checks"])
    return values


def check(gh, settings):
    """Return (lines, drifted) for every setting of every repository."""
    lines, drifted = [], False
    for repo, entry in settings.items():
        file_values = wanted(entry)
        if entry.get("blocked_by"):
            lines += [f"{repo} {name} BLOCKED {entry['blocked_by']}"
                      for name in PROTECTION + MERGE]
            continue
        live = read_live(gh, repo, entry["branch"])
        for name in PROTECTION + MERGE:
            if live[name] == file_values[name]:
                lines.append(f"{repo} {name} MATCH {json.dumps(live[name])}")
            else:
                drifted = True
                lines.append(f"{repo} {name} DRIFT live="
                             f"{json.dumps(live[name])} "
                             f"file={json.dumps(file_values[name])}")
    return lines, drifted


def apply(gh, settings):
    """Write the file's values to every repository not marked blocked.

    The protection PUT replaces the branch's whole protection, so any setting
    the file does not name returns to GitHub's default. Checks are sent as
    `checks` with no app_id rather than as `contexts`, so GitHub keeps the app
    that last reported each check instead of accepting it from any source.
    """
    for repo, entry in settings.items():
        if entry.get("blocked_by"):
            continue
        prot = entry["protection"]
        gh("PUT", f"repos/{repo}/branches/{entry['branch']}/protection", {
            "required_status_checks": {
                "strict": prot["strict"],
                "checks": [{"context": name}
                           for name in prot["required_status_checks"]],
            },
            "enforce_admins": prot["enforce_admins"],
            "required_pull_request_reviews": (
                {"required_approving_review_count":
                    prot["required_approving_review_count"]}
                if prot["pull_request_required"] else None),
            "restrictions": None,
        })
        gh("PATCH", f"repos/{repo}", dict(entry["merge"]))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Check or apply repository settings from "
                    "repo-settings.json. With no flag, checks.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="read live settings and report; the default")
    mode.add_argument("--apply", action="store_true",
                      help="write the file's values to every repository not "
                           "marked blocked, then re-read and report")
    return parser


def main(argv=None, gh=run_gh, settings_path=SETTINGS_FILE):
    args = build_parser().parse_args(argv)
    settings = load_settings(settings_path)
    if args.apply:
        apply(gh, settings)
    lines, drifted = check(gh, settings)
    print("\n".join(lines))
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
