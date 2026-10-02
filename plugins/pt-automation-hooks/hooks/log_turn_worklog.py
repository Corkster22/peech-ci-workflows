#!/usr/bin/env python3
"""Stop hook (PPA-1757) - post each Claude Code turn to Tempo as non-billable.

When a turn ends, its elapsed time posts by itself as a Tempo worklog on the
PPA or PEECHPMO ticket(s) the session's latest dispatch line names, so Sean's
timesheet no longer waits on a manual top-up (PPA-1654, PPA-1676).

``post_pending_turns.py`` is the SessionStart half (PPA-1774). It calls
``sweep`` below for every earlier session, so the two hooks share one parser,
one split, one rounding rule and one tag, and a turn posted by either is never
posted twice.

What it does, in order
----------------------
1. Reads ``session_id`` and ``transcript_path`` from the hook input.
2. Takes every ``type: system, subtype: turn_duration`` row that ended on or
   after ``CUTOFF``. None - a headless or SDK session, or a slash command -
   means nothing to post.
3. Maps each turn to the keys of the latest dispatch line before it: a first
   non-blank line opening with keys, then nothing or a ``-`` or ``:`` and a
   note (Amendment 1), the older "Execute PPA-XXX." form, or the same line
   beneath a ``<pasted_content>`` tag. A turn with no key is skipped.
4. Posts only when the Jira identity in the credentials file is Sean's.
5. Splits each turn evenly across its keys, remainder seconds to the first, so
   the parts sum to the turn. A key's part counts as posted when its tag is in
   a worklog description on that key's issue. Each part not yet posted posts as
   its own worklog with ``billableSeconds`` 0, rounded up to the next multiple
   of 360 seconds, one tenth of an hour (``round_up``), overstating it by at
   most 359 seconds. Nothing is held across turns and no worklog bundles
   several turns.

Why every row, not the latest
-----------------------------
Read off real transcripts on 01-OCT-2026 (sessions ee775a3f, 89e6134d and
e3c4940c): a turn's ``turn_duration`` row is written about 3 ms after the
turn's last ``stop_hook_summary``, so it is never in the transcript while its
own Stop hook runs. Posting only the latest row would post one turn behind and
lose a turn whenever a Stop did not fire, such as after an interrupt. Posting
every row not yet tagged in Tempo catches up on the next Stop.

A session's final turn has no later Stop in that session, so it posts when the
next session starts in one of the four Peech repositories (PPA-1774,
``post_pending_turns.py``), or when PPA-1756's catch-up script is re-run.

The tag is ``cc-turn:<session_id>:<uuid of the turn_duration row>``, carried as
the whole description. PPA-1756's catch-up writes the same tag, so a part
either one posted is never posted by the other. ``CUTOFF`` keeps turns that
the untagged 23-SEP backfill already covered from posting twice.

Alerts
------
Sean gets one Slack direct message, at most one per session per reason, when a
Tempo post fails and when a turn carries no dispatch key (PPA-1774). The bot
token is ``SLACK_BOT_TOKEN`` in the credentials file, and Sean's Slack user is
found from the Jira email in the same file. ``ALERTS`` records what was sent. A
Slack failure is written to ``LOG`` and nothing else: it never blocks a turn or
a session start.

Fail open
---------
Any exit code other than 2 leaves the turn unaffected, and 2 would block the
stop. This hook never exits 2: every failure - missing transcript or
credentials, a parse error, a network, Tempo or Jira error - is caught,
written as one line to ``LOG`` naming the turn, the reason and the time, and
the hook exits 0. The hooks.json wrapper is fail-open and carries a timeout,
and ``DEADLINE`` stops this file's own calls before that timeout does, so a
slow Tempo never holds a turn open. A key that fails on its own data, such as
one Jira cannot resolve, is logged and the other keys still post. A network or
timeout failure ends the run, and the next Stop retries. Running out of the
hook's own time raises ``DeadlineReached``, a ``TimeoutError`` that is never
alerted, because nothing failed. This hook logs it with the other timeouts; the
SessionStart sweep treats it as a clean stop (PPA-1774 rework).

This hook never deletes or edits a worklog. Tempo DELETE leaves the Jira
mirror worklog behind, so undoing a post means deleting both sides.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

#: The one absolute .env every plugin hook reads (PPA-1126).
CREDENTIALS = Path.home() / "Documents/Claude-Projects/peech-pmo-automation/secrets/.env"
LOG = Path.home() / ".claude" / "pt-turn-worklog-hook.log"
SEAN = "712020:b8cdfe79-6025-4d71-afb5-f83a33dc7732"
JIRA = "https://peech-team.atlassian.net/rest/api/3"
TEMPO = "https://api.tempo.io/4"
ET = ZoneInfo("America/New_York")
#: A turn ending before this was covered by the untagged 23-SEP backfill.
CUTOFF = datetime(2026, 9, 24, tzinfo=ET)
#: Every post is a multiple of this, one tenth of an hour (PPA-1774 Amendment 2).
#: Only Claude Code time is captured, so totals run low, and six-minute steps
#: are the professional norm.
ROUND_SECONDS = 360
ALERTS = Path.home() / ".claude" / "pt-turn-worklog-alerts.json"
SLACK = "https://slack.com/api"
HTTP_TIMEOUT = 5
#: Seconds this file spends on HTTP before it gives up. hooks.json allows more.
DEADLINE = 25
#: Tempo pages a user's worklogs; a day is never near this many pages.
MAX_PAGES = 10

_KEY = r"(?:PPA|PEECHPMO)-\d+\b"
_KEY_RE = re.compile(_KEY, re.IGNORECASE)
#: The keys a line opens with, after an optional "Execute".
_LEAD_RE = re.compile(rf"^\s*(?:execute\s+)?({_KEY}(?:[ ,;&/\t]+{_KEY})*)", re.IGNORECASE)
_PASTE_TAG_RE = re.compile(r"</?pasted_content[^>]*>")
_SEPARATORS = " ,;:.&/\t"
#: What may follow the keys before a note: a dash or a colon, then any text. A
#: comma is not one (Amendment 1, corrected 01-OCT-2026 12:54 ET).
_NOTE_LEADS = ("-", ":")

_started = time.monotonic()


def log(turn, reason):
    """Append one record, and never raise.

    PPA-1757 considered and dropped: a user whose machine has no credentials
    file logs one line per turn here, so the log grows. PPA-1757 rules that a
    silent miss must be findable, the log is local, and a line is ~150 bytes,
    so nothing observable breaks if this is never bounded.
    """
    record = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "turn": turn, "reason": reason}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def tag(session_id, uuid):
    return f"cc-turn:{session_id}:{uuid}"


def dispatch_keys(prompt):
    """The keys a prompt dispatches, or [] where it dispatches none.

    Only the first non-blank line counts, after any pasted_content tag is
    removed. It dispatches when it opens with one or more keys (an optional
    leading "Execute" is allowed) and the rest is nothing but punctuation, or a
    dash or a colon and then any text, so ``PEECHPMO-491 - includes Amendment
    1`` and ``PPA-1757: log turns`` dispatch (PPA-1757 Amendment 1, the rule
    PPA-1756 shipped in a069ce3e). A key followed directly by a word, as in
    ``PPA-1700 is failing, why?``, is prose, and so are a comma note such as
    ``PPA-1757, run the fix`` and a key sentence such as ``PPA-1289. Fetch the
    ticket`` (PPA-1676 Q5). Only the leading keys dispatch, never a key inside
    the note, and a note on a later line does not count.
    """
    for line in _PASTE_TAG_RE.sub("", prompt).splitlines():
        line = line.strip()
        if not line:
            continue
        lead = _LEAD_RE.match(line)
        if lead:
            tail = line[lead.end():]
            if not tail.strip(_SEPARATORS) or tail.lstrip().startswith(_NOTE_LEADS):
                return list(dict.fromkeys(
                    k.upper() for k in _KEY_RE.findall(lead.group(1))))
        return []
    return []


def _prompt_text(row):
    """The text of a prompt typed by a person, or '' for anything else."""
    if row.get("type") != "user" or row.get("isMeta"):
        return ""
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and not any(
            isinstance(p, dict) and p.get("type") == "tool_result" for p in content):
        return "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


def turns(transcript_path):
    """Every (turn_duration row, the keys in force at it), in file order."""
    keys, found = [], []
    for line in Path(transcript_path).read_text(errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("type") == "system" and row.get("subtype") == "turn_duration":
            found.append((row, keys))
        else:
            keys = dispatch_keys(_prompt_text(row)) or keys
    return found


def ended(row):
    """When the turn ended, or None where the row cannot be timed or tagged.

    A row that stays malformed would log at every Stop and block the rows
    after it, so it is skipped rather than treated as a failure.
    """
    ms = row.get("durationMs")
    if not isinstance(ms, int) or isinstance(ms, bool) or ms <= 0 \
            or not isinstance(row.get("uuid"), str):
        return None
    try:
        return datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return None


def round_up(seconds):
    """The next multiple of ``ROUND_SECONDS`` at or above ``seconds``.

    1 to 360 posts as 360 and 361 to 720 as 720, so a post never understates
    its part and overstates it by at most 359 seconds. A part of zero seconds
    stays zero: the caller posts nothing for it. Both hooks post through this.
    """
    return -(-seconds // ROUND_SECONDS) * ROUND_SECONDS


def split_seconds(total, count):
    """``count`` whole-second parts summing to ``total``, remainder first."""
    base, remainder = divmod(total, count)
    return [base + remainder] + [base] * (count - 1)


def load_env(path):
    """KEY=VALUE pairs, parsed as pt_transition.load_credentials parses them."""
    env = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


class DeadlineReached(TimeoutError):
    """This hook ran out of its own time (``DEADLINE``), not out of luck.

    A subclass of ``TimeoutError`` so every handler that already ends a run on a
    timeout still does. The difference is that the work is fine: nothing failed,
    so nothing is alerted, and whatever is left is picked up at the next run.
    """


def http_json(method, url, headers, body=None):
    """One JSON request. Raises on any HTTP, network or timeout failure, and
    raises ``DeadlineReached`` when the hook's own time is spent."""
    left = DEADLINE - (time.monotonic() - _started)
    if left <= 0:
        raise DeadlineReached("hook deadline reached before the request")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", "Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=min(HTTP_TIMEOUT, left)) as resp:
            raw = resp.read()
    except TimeoutError as exc:
        # A request cut short by the deadline, rather than a slow server, reads
        # as a timeout too (the log of 02-OCT-2026 13:44:47).
        if time.monotonic() - _started >= DEADLINE - 0.5:
            raise DeadlineReached("hook deadline reached during the request") from exc
        raise
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}") from exc
    return json.loads(raw) if raw else {}


class Poster:
    """Sean's Jira and Tempo calls, each lookup made once per run."""

    def __init__(self, env, ids=None):
        """``ids`` is a key-to-issue-id map a caller kept from an earlier run.
        An issue id never changes, so a kept one saves a Jira request."""
        self.jira = {"Authorization": "Basic " + base64.b64encode(
            f"{env['JIRA_EMAIL']}:{env['JIRA_API_TOKEN']}".encode()).decode()}
        self.tempo = {"Authorization": f"Bearer {env['TEMPO_FM_OAUTH_TOKEN']}"}
        self.descriptions = {}
        self.ids = dict(ids or {})

    def is_sean(self):
        return http_json("GET", f"{JIRA}/myself", self.jira).get("accountId") == SEAN

    def issue_id(self, key):
        if key not in self.ids:
            issue = http_json("GET", f"{JIRA}/issue/{key}?fields=summary", self.jira)
            self.ids[key] = int(issue["id"])
        return self.ids[key]

    def posted(self, issue, turn_tag):
        """True when a worklog on that issue already carries the tag."""
        if issue not in self.descriptions:
            found, url = [], f"{TEMPO}/worklogs/issue/{issue}?limit=1000"
            for _ in range(MAX_PAGES):
                page = http_json("GET", url, self.tempo)
                found += [w.get("description") or "" for w in page.get("results", [])]
                url = (page.get("metadata") or {}).get("next")
                if not url:
                    break
            self.descriptions[issue] = found
        return any(turn_tag in d for d in self.descriptions[issue])

    def post(self, issue, part):
        """One worklog for one part, its seconds rounded up by ``round_up``."""
        turn_tag, seconds, row = part
        start = (ended(row) - timedelta(milliseconds=row["durationMs"])).astimezone(ET)
        http_json("POST", f"{TEMPO}/worklogs", self.tempo, {
            "issueId": issue, "authorAccountId": SEAN,
            "startDate": start.strftime("%Y-%m-%d"), "startTime": start.strftime("%H:%M:%S"),
            "timeSpentSeconds": round_up(seconds), "billableSeconds": 0,
            "description": turn_tag})

    def post_key(self, key, parts):
        """Post this key's parts whose tag is not yet on its issue in Tempo.

        Each part posts rounded up to the next multiple of 360 seconds
        (``round_up``), so a post overstates its part by at most 359 seconds,
        and a part of zero seconds posts nothing. Nothing is held across turns
        and no worklog bundles several turns, so a later Stop or session start
        posts only what Tempo does not yet show.

        Whether a part is posted is read per tag and per issue (Amendment 2
        rule 3), so a later Stop finishes a multi-key turn that stopped
        partway. The next session start finishes one left partway at the end of
        a session.
        """
        issue = self.issue_id(key)
        for part in parts:
            if not self.posted(issue, part[0]):
                self.post(issue, part)


def parts_by_key(session_id, todo):
    """Each key's (tag, seconds, row) parts of the turns it was dispatched on."""
    by_key = {}
    for row, keys in todo:
        # PPA-1757 considered and dropped: milliseconds become whole seconds
        # here, half up, before the split and the 360-second rounding, because
        # Tempo's timeSpentSeconds is an integer and the remainder-to-first
        # split needs one. It moves a turn by under half a second, and the
        # rounding that follows swallows it, so nothing observable breaks if it
        # is never changed.
        total = (row["durationMs"] + 500) // 1000
        for key, seconds in zip(keys, split_seconds(total, len(keys))):
            if seconds > 0:
                by_key.setdefault(key, []).append((tag(session_id, row["uuid"]), seconds, row))
    return by_key


def _alerted():
    try:
        return set(json.loads(ALERTS.read_text()))
    except (OSError, ValueError):
        return set()


class Alerts:
    """Slack direct messages to Sean, at most one per session per reason."""

    def __init__(self, env):
        self.env = env
        self.headers = {"Authorization": f"Bearer {env.get('SLACK_BOT_TOKEN', '')}"}
        self.channel = None

    def _call(self, method, path, body=None):
        reply = http_json(method, f"{SLACK}/{path}", self.headers, body)
        if not reply.get("ok"):
            raise RuntimeError(f"Slack {path}: {reply.get('error', 'not ok')}")
        return reply

    def send(self, session_id, reason, row, detail):
        """Send one message unless this session already had one for ``reason``.

        Never raises. A failure is logged and the message is retried at the next
        hook run, because it is only recorded as sent once Slack accepted it.
        """
        sent_key = f"{session_id}|{reason}"
        if sent_key in _alerted():
            return
        try:
            if self.channel is None:
                user = self._call("GET", "users.lookupByEmail?email=" + urllib.parse.quote(
                    self.env["JIRA_EMAIL"]))["user"]["id"]
                self.channel = self._call("POST", "conversations.open",
                                          {"users": user})["channel"]["id"]
            seconds = (row["durationMs"] + 500) // 1000
            self._call("POST", "chat.postMessage", {"channel": self.channel, "text": (
                f"Claude Code time log: {reason}.\n"
                f"Session {session_id}, turn ended "
                f"{ended(row).astimezone(ET):%Y-%m-%d %H:%M} ET, "
                f"length {seconds // 60}m {seconds % 60}s.\n{detail}").rstrip()})
            ALERTS.parent.mkdir(parents=True, exist_ok=True)
            ALERTS.write_text(json.dumps(sorted(_alerted() | {sent_key})))
        except DeadlineReached:
            raise  # not sent, not recorded: the next run sends it
        except Exception as exc:  # noqa: BLE001 - an alert never blocks a turn
            log(tag(session_id, row.get("uuid", "?")), f"alert not sent: {type(exc).__name__}: {exc}")


NO_KEY = "a turn has no dispatch key and nothing was posted"


def windowed(transcript_path):
    """Every (turn_duration row, keys in force) that ended on or after CUTOFF."""
    return [(row, keys) for row, keys in turns(transcript_path)
            if (when := ended(row)) and when >= CUTOFF]


def needs_work(session_id, marked):
    """True when a session has a turn to post, or a no-key alert still unsent.

    Checked before any HTTP, so a Stop in a session with nothing to do, or whose
    ticketless turn was already reported, makes no request.
    """
    return any(keys for _, keys in marked) or (
        bool(marked) and f"{session_id}|{NO_KEY}" not in _alerted())


def sweep(poster, alerts, session_id, marked):
    """Post every turn in ``marked`` that Tempo does not yet show, and alert.

    Returns True when the session is settled: every part is in Tempo and any
    no-key alert is recorded as sent. False means something is left for a later
    run (a key that failed on its own data, or an alert Slack did not accept).

    ``poster`` and ``alerts`` are built once by the caller, so a start that
    sweeps many sessions asks Jira and Slack for each lookup once. A network or
    timeout failure raises, ending the caller's run; ``DeadlineReached`` passes
    through without an alert, because running out of time is not a failed post.
    """
    settled = True
    if (nokey := next((row for row, keys in marked if not keys), None)) is not None:
        alerts.send(session_id, NO_KEY, nokey,
                    "Put the ticket keys on the first line of the next prompt.")
        settled = f"{session_id}|{NO_KEY}" in _alerted()
    todo = [(row, keys) for row, keys in marked if keys]
    for key, parts in parts_by_key(session_id, todo).items():
        try:
            poster.post_key(key, parts)
        except TimeoutError:
            raise  # a slow server or the deadline: end the run, nothing to alert
        except Exception as exc:  # noqa: BLE001 - this key's own data, or the network
            alerts.send(session_id, "a Tempo post failed", parts[0][2],
                        f"{key}: {type(exc).__name__}: {exc}")
            if isinstance(exc, OSError):
                raise  # network failure: end the run; the caller logs it
            log(parts[0][0], f"{type(exc).__name__}: {exc}")
            settled = False
    return settled


def main():
    turn = "unknown"
    try:
        payload = json.load(sys.stdin)
        session_id = turn = payload["session_id"]
        marked = windowed(payload["transcript_path"])
        if needs_work(session_id, marked):
            turn = tag(session_id, next(
                (r for r, k in marked if k), marked[0][0])["uuid"])
            env = load_env(CREDENTIALS)
            poster = Poster(env)
            if poster.is_sean():
                sweep(poster, Alerts(env), session_id, marked)
    except Exception as exc:  # noqa: BLE001 - fail open on every path
        log(turn, f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
