#!/usr/bin/env python3
"""Stop hook (PPA-1757) - post each Claude Code turn to Tempo as non-billable.

When a turn ends, its elapsed time posts by itself as a Tempo worklog on the
PPA or PEECHPMO ticket(s) the session's latest dispatch line names, so Sean's
timesheet no longer waits on a manual top-up (PPA-1654, PPA-1676).

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
   a worklog description on that key's issue. A part of a minute or more posts
   as its own worklog with ``billableSeconds`` 0. A shorter part is held, never
   rounded up, because Tempo refuses under 60 seconds, and a key's held parts
   post as one worklog, carrying every tag it covers, once they reach 60.

Why every row, not the latest
-----------------------------
Read off real transcripts on 01-OCT-2026 (sessions ee775a3f, 89e6134d and
e3c4940c): a turn's ``turn_duration`` row is written about 3 ms after the
turn's last ``stop_hook_summary``, so it is never in the transcript while its
own Stop hook runs. Posting only the latest row would post one turn behind and
lose a turn whenever a Stop did not fire, such as after an interrupt. Posting
every row not yet tagged in Tempo catches up on the next Stop.

The residual: a session's final turn posts only when a later Stop in that
session finds its row, or when PPA-1756's catch-up script is re-run. Nothing
fires after the last Stop, so without one of those that turn goes unposted. The
same holds for a key's held remainder under a minute when a session ends.

The tag is ``cc-turn:<session_id>:<uuid of the turn_duration row>``, carried as
the whole description of a worklog for one turn, and space-separated with its
fellows in a worklog for held parts. PPA-1756's catch-up writes the same tag,
so a part either one posted is never posted by the other. ``CUTOFF`` keeps turns that
the untagged 23-SEP backfill already covered from posting twice.

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
timeout failure ends the run, and the next Stop retries.

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
#: Tempo refuses a worklog under one minute with HTTP 400 (Amendment 2).
MIN_SECONDS = 60
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


def http_json(method, url, headers, body=None):
    """One JSON request. Raises on any HTTP, network or timeout failure."""
    left = DEADLINE - (time.monotonic() - _started)
    if left <= 0:
        raise TimeoutError("hook deadline reached before the request")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", "Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=min(HTTP_TIMEOUT, left)) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}") from exc
    return json.loads(raw) if raw else {}


class Poster:
    """Sean's Jira and Tempo calls, each lookup made once per run."""

    def __init__(self, env):
        self.jira = {"Authorization": "Basic " + base64.b64encode(
            f"{env['JIRA_EMAIL']}:{env['JIRA_API_TOKEN']}".encode()).decode()}
        self.tempo = {"Authorization": f"Bearer {env['TEMPO_FM_OAUTH_TOKEN']}"}
        self.descriptions = {}
        self.ids = {}

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

    def post(self, issue, parts):
        """One worklog for ``parts``: their total, every tag they cover, and
        the start of the first."""
        row = parts[0][2]
        start = (ended(row) - timedelta(milliseconds=row["durationMs"])).astimezone(ET)
        http_json("POST", f"{TEMPO}/worklogs", self.tempo, {
            "issueId": issue, "authorAccountId": SEAN,
            "startDate": start.strftime("%Y-%m-%d"), "startTime": start.strftime("%H:%M:%S"),
            "timeSpentSeconds": sum(seconds for _, seconds, _ in parts),
            "billableSeconds": 0,
            "description": " ".join(turn_tag for turn_tag, _, _ in parts)})

    def post_key(self, key, parts):
        """Post this key's parts that are not yet in Tempo, or hold them.

        A part of a minute or more posts as its own worklog. Tempo refuses
        anything under 60 seconds, so a shorter part is held, never rounded up,
        and the held parts post as one worklog once they reach 60 seconds
        (Amendment 2). Whether a part is posted is read per tag and per issue,
        so a later Stop finishes a multi-key turn that stopped partway.

        The residual: a key's held remainder under 60 seconds when a session
        ends is never posted, because nothing fires after the last Stop, and a
        multi-key turn left partway at that point stays partway.

        PPA-1757 considered and dropped: bundling the parts of a minute or more
        too, so that one Stop posts one worklog per key. Amendment 2 holds only
        a part under 60 seconds, and PPA-1756 posts one worklog per key under
        one tag, so this keeps to that. A bundle would change how many worklogs
        a day carries, never the day's total, so nothing observable breaks if
        it is never done.
        """
        issue = self.issue_id(key)
        unposted = [part for part in parts if not self.posted(issue, part[0])]
        for part in (p for p in unposted if p[1] >= MIN_SECONDS):
            self.post(issue, [part])
        held = [p for p in unposted if p[1] < MIN_SECONDS]
        if sum(seconds for _, seconds, _ in held) >= MIN_SECONDS:
            self.post(issue, held)


def parts_by_key(session_id, todo):
    """Each key's (tag, seconds, row) parts of the turns it was dispatched on."""
    by_key = {}
    for row, keys in todo:
        total = (row["durationMs"] + 500) // 1000
        for key, seconds in zip(keys, split_seconds(total, len(keys))):
            if seconds > 0:
                by_key.setdefault(key, []).append((tag(session_id, row["uuid"]), seconds, row))
    return by_key


def main():
    turn = "unknown"
    try:
        payload = json.load(sys.stdin)
        session_id = turn = payload["session_id"]
        todo = [(row, keys) for row, keys in turns(payload["transcript_path"])
                if keys and (when := ended(row)) and when >= CUTOFF]
        if todo:
            turn = tag(session_id, todo[0][0]["uuid"])
            poster = Poster(load_env(CREDENTIALS))
            if poster.is_sean():
                for key, parts in parts_by_key(session_id, todo).items():
                    turn = parts[0][0]
                    try:
                        poster.post_key(key, parts)
                    except OSError:
                        raise  # network or timeout: end the run, the next Stop retries
                    except Exception as exc:  # noqa: BLE001 - this key's own data
                        log(turn, f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 - fail open on every path
        log(turn, f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
