<!-- CLAUDE.md v0-2-0 • 23-SEP-2026 -->
<!-- Graded with --file, the CLAUDE.md conformance gate fails this file on C1
only: no verdict file under _keep-reference/claudemd-verdicts/peech-ci-workflows/.
No hook or CI job grades this repository, so nothing reads that result. -->

# peech-ci-workflows

## Project Overview

Callable GitHub Actions workflows, and the scripts they run, shared by
peech-pmo-automation, peech-skills and peech-org-skills. A caller invokes a
workflow here with `workflow_call` and passes its own credentials as secrets.

The repository is public and holds no secret. Nothing here may carry a token,
a password or a channel id; each arrives from the caller at run time. The
route, and why the repository is public, are recorded in
PeechTech-Framework-SharedAutomationRouting in peech-pmo-automation.

## Architecture

| Path | Holds |
|---|---|
| `.github/workflows/merge-close-out.yml` | Callable. Records the merge hash on each PPA key a merge carried and applies the close-out transition. |
| `.github/workflows/pr-open.yml` | Callable. Opens the pull request for a pushed `ppa-*` branch. |
| `.github/workflows/auto-merge-arm.yml` | Callable. Arms auto-merge on a quiet pull request. |
| `.github/workflows/behind-branch-update.yml` | Callable. Updates a pull request that is behind `main`. |
| `.github/workflows/pytest.yml` | This repository's own check, on pull request and on push to `main`. |
| `scripts/pr_merge_close_out.py` | The close-out rules. Every rule the close-out applies lives here, not in YAML. |
| `scripts/pt_transition.py` | Moves PPA keys to a named status, one live hop at a time. |
| `scripts/tests/` | pytest coverage for both scripts. |

The two scripts have registered copies in the sibling repositories, listed in
peech-pmo-automation's cross-repository copy register. An edit here is half a
change until the counterpart lands or is retired.

## Tech Stack

Python 3.12 in CI, pinned in `.github/workflows/pytest.yml`. The scripts use
the standard library only; the suite needs pytest and PyYAML. There is no
virtualenv and no `peech_shared` here, so a script may not import it.

## Coding Rules

A rule belongs in a script with a test, never in a workflow step, because a
rule written in YAML cannot be unit-tested. A workflow reads caller
configuration from `inputs` and `secrets`, not `vars`.

## Delegation

@delegation.md

## Run Instructions

Nothing here runs locally except the suite. A workflow runs only when a caller
invokes it; `pytest.yml` alone runs on this repository's own pull requests and
pushes to `main`. No schedule runs, and no secret is stored here.

This repository calls none of its own workflows, so no workflow opens, arms or
closes out a pull request here. That replaces the Delegation block's close-out
bullet for this repository only:

- The session commits to `ppa-<key>` and pushes, then posts its close-out
  checklist on each ticket before it stops.
- The conductor opens the pull request and merges it once `pytest` passes.
- No merge here records a hash or applies a transition. The conductor does
  both by hand.
- No `UserPromptSubmit` hook runs here, so a dispatch does not move its keys to
  In Progress.
- If the push is refused, the session stops and reports the staged files. The
  conductor pushes from the Run Terminal.

## Environment Variables

None are read locally. At run time `merge-close-out.yml` sets
`SLACK_CHANNEL_DELIVERY_OPS` from its `slack_channel` input and
`SLACK_BOT_TOKEN` from the caller's secret, and writes the caller's Jira pair
to the credential file `scripts/pt_transition.py` reads. Callers pass
`JIRA_EMAIL`, `JIRA_API_TOKEN`, `PEECH_AUTOMATION_TOKEN` and, optionally,
`SLACK_BOT_TOKEN` as secrets.

## Testing

Run from the repository root: `python3 -m pytest scripts/`

## Common Misreads

No confirmed misreads documented — add entries as patterns emerge.
