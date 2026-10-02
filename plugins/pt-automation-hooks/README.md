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
  covered them. A session's final turn posts when the next session starts (see
  below), or when PPA-1756's script is re-run.
- Several keys in the dispatch split the turn evenly. The first key takes the
  remainder seconds.
- Every post rounds its part up to the next multiple of 360 seconds, one tenth of
  an hour (Sean's ruling, 02-OCT-2026): 1 to 360 seconds posts as 360, 361 to
  720 as 720, and so on. Only Claude Code time is captured, so totals run low,
  and six-minute steps are the professional norm. A post overstates its part by
  at most 359 seconds, and a part of zero seconds posts nothing. One function,
  `round_up`, holds the rule for both hooks. Nothing is held across turns, and
  no worklog bundles several turns.
- Each worklog carries `billableSeconds` 0 and the tag
  `cc-turn:<session_id>:<uuid of the turn_duration row>` as its description. A
  part counts as posted when its tag is in a worklog description on that key's
  issue, so a later Stop finishes a multi-key turn that stopped partway.
  PPA-1756's catch-up writes the same tag.
- Credentials are `TEMPO_FM_OAUTH_TOKEN`, `JIRA_EMAIL` and `JIRA_API_TOKEN` in
  `peech-pmo-automation/secrets/.env`.

### Posting the last turn of a session (`hooks/post_pending_turns.py`)

PPA-1774. A session's final turn has no later Stop, so a SessionStart hook posts
it. When any session starts (`startup`, `resume`, `clear`, `compact` or `fork`),
the hook posts every turn from earlier sessions that Tempo does not yet show. It
sweeps only sessions whose project folder is one of `peech-pmo-automation`,
`peech-skills`, `peech-org-skills` and `peech-ci-workflows`, and only turns
ending on or after the Stop hook's cutoff. It uses the Stop hook's parser,
split, rounding, tag and alerts, so a turn either hook posted is never posted
twice. It prints nothing, never blocks a start, and leaves work at its deadline
for the next start.

### Alerts

Sean gets one Slack direct message, at most one per session per reason, when a
Tempo post fails and when a turn carries no dispatch key. The message names the
session, the turn's end time, its length and the reason. The bot token is
`SLACK_BOT_TOKEN` in the same credentials file, and Sean's Slack user is found
from `JIRA_EMAIL` there. Sent messages are recorded in
`~/.claude/pt-turn-worklog-alerts.json`. A Slack failure is written to the log
and never blocks a turn or a start. The bot needs the `im:write`,
`users:read` and `users:read.email` scopes (`chat:write` to post).

### The hook never blocks a turn

Exit code 2 blocks a Stop. This hook exits 0 on every path, and its
`hooks.json` wrapper exits 0 when the file is missing and sets a timeout.
Each failure writes one line to `~/.claude/pt-turn-worklog-hook.log` with the
turn, the reason and the time. Read that log to find a missed turn. A turn that
fails part way, after one key posted and before the next, is finished for the
other keys at the next Stop, because the posted check is per issue.

### Undoing a worklog

The hook never edits or deletes a worklog. To undo one, delete both sides.
Tempo DELETE does not remove the Jira mirror worklog that "Timesheets by
Tempo" writes (PPA-1676 finding 1).

1. Delete the worklog in Tempo: `DELETE https://api.tempo.io/4/worklogs/<id>`.
2. Delete the mirror in Jira:
   `DELETE /rest/api/3/issue/<key>/worklog/<id>?adjustEstimate=leave`.

### Tests

From this directory: `python3 -m pytest tests/`. No test calls Tempo or Jira.
