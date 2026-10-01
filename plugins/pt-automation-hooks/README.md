# pt-automation-hooks

Peech Tech's shared Claude Code hooks, served from the `peech-ci` marketplace.
`hooks/hooks.json` lists every hook and the event it fires on.

## Turn worklog hook (`hooks/log_turn_worklog.py`)

PPA-1757. When an interactive turn ends, the hook posts the turn's elapsed
time to Tempo as a non-billable worklog on the PPA or PEECHPMO ticket or
tickets in the session's latest dispatch line. It posts only when the Jira
identity in the credentials file is Sean's account. For anyone else it posts
nothing.

- Time comes from the transcript's `turn_duration` row. A headless or SDK
  session, or a slash command, writes none, so nothing posts.
- Claude Code writes a turn's row after that turn's Stop hooks run, so the hook
  posts every row not yet tagged in Tempo, not only the latest. Rows that
  ended before 2026-09-24 00:00 ET never post, because the 23-SEP backfill
  covered them. A session's final turn posts only when a later Stop in that
  session finds its row, or when PPA-1756's script is re-run.
- Several keys in the dispatch split the turn evenly. The first key takes the
  remainder seconds.
- Each worklog carries `billableSeconds` 0 and the tag
  `cc-turn:<session_id>:<uuid of the turn_duration row>` as its description.
  A turn whose tag is already in Sean's Tempo worklogs for that date is
  skipped. PPA-1756's catch-up writes the same tag.
- Credentials are `TEMPO_FM_OAUTH_TOKEN`, `JIRA_EMAIL` and `JIRA_API_TOKEN` in
  `peech-pmo-automation/secrets/.env`.

### The hook never blocks a turn

Exit code 2 blocks a Stop. This hook exits 0 on every path, and its
`hooks.json` wrapper exits 0 when the file is missing and sets a timeout.
Each failure writes one line to `~/.claude/pt-turn-worklog-hook.log` with the
turn, the reason and the time. Read that log to find a missed turn. A turn that
fails part way, after one key posted and before the next, leaves its tag in
Tempo, so it is not retried.

### Undoing a worklog

The hook never edits or deletes a worklog. To undo one, delete both sides.
Tempo DELETE does not remove the Jira mirror worklog that "Timesheets by
Tempo" writes (PPA-1676 finding 1).

1. Delete the worklog in Tempo: `DELETE https://api.tempo.io/4/worklogs/<id>`.
2. Delete the mirror in Jira:
   `DELETE /rest/api/3/issue/<key>/worklog/<id>?adjustEstimate=leave`.

### Tests

From this directory: `python3 -m pytest tests/`. No test calls Tempo or Jira.
