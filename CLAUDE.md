<!-- CLAUDE.md v0-1-0 • 23-SEP-2026 -->
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
<!-- pt-delegation:start - identical in peech-pmo-automation and peech-skills; do not edit one copy -->
Standing rules a delegated session applies without being told, so a dispatch is a ticket key and nothing else.
- Implement only what the ticket specifies — no scope additions. The one exception is outcome 1 below.
- Run the pytest cases the ticket names and report results.
- Stop at the gate — no deploy, no CLAUDE.md edit the ticket does not name, and no adjacent improvement noticed along the way except where outcome 1 below admits it.
- Close out: commit to `ppa-<key>` and push. `pr-open.yml` opens the pull request and `auto-merge-arm.yml` arms it; comment the pull request number on the ticket; never run `gh pr merge` yourself. A merge that completes during the session is expected and is not a breach — the merge happens to the session, not by it.
- Every finding that is not the ticket's own work takes exactly one outcome, and the order binds: a later outcome is reached only when the earlier ones do not apply.
- Outcome 1, fix it here. Either condition is enough on its own: the defect sits in a file the ticket's scope boundary names as editable, or it is in the same failure class as the change being shipped. Fix it in a separate commit on the same branch, subject prefixed `adjacent:` and carrying the ticket key, meeting the evidence bar the ticket itself demands: reproduce before and after, with the command named. A defect that cannot be reproduced falls to outcome 2 rather than being fixed on inspection. If the fix would change what any of the ticket's own Definition of Done conditions measure, stop and report instead; a session never makes its own Definition of Done easier to pass.
- Outcome 2, comment and drop. The test is not whether the finding is real, it is what breaks if this is never fixed. Where the answer names nothing observable, record it as a comment in the code where it lives and write down what was considered. Dropped, not deferred.
- Outcome 3, ticket it. Everything else: a finding worth fixing that cannot be fixed here.
- A file inside a `pt-common` or `pt-delegation` marker pair, or any file with a known counterpart in another repository, cannot be changed in one repository alone. Editing one is half a change: say so in the report, name the counterpart file and repository, and state that the other half is unshipped. Do not edit across the repository boundary — one commit reaches one remote.
- Report what changed, file by file.
- Read every ticket in the command, and the current state of every file each one names, before editing anything. Report a contradiction — between two tickets, or between a ticket and the working tree — as a halt that stops the whole command rather than one ticket. Otherwise state the order you will work in and the constraint or ticket text that forces it. A command hands over a set and its constraints, never a sequence.
- An amendment comment governs over the description and over the Definition of Done alike. Read the description, `customfield_10767` and the comments in one pass and reconcile them; the latest explicit decision wins. Where an amendment supersedes a stored Definition of Done condition, grade that condition against the amended wording and name the amendment - do not report it not met against wording the amendment already replaced.
- The skills to load come from the ticket's own `Skills to load and apply:` line, never from the dispatch text. pt-backlog is always among them.
- Close-out checklist shape. Write one row per Definition of Done condition, in the field's own order. Each row carries the condition number, the condition text quoted from the Definition of Done field, the verdict MET or NOT MET, and the evidence. A Markdown table and a numbered list are both read. A row that does not quote its condition text cannot be paired, and is reported as unstated rather than filed.
<!-- pt-delegation:end -->
<!-- This copy is not in peech-pmo-automation's cross-repository copy
register, which PPA-1594 retires. Nothing compares it with the other copies,
so an edit to the block there is copied here by hand. -->

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
