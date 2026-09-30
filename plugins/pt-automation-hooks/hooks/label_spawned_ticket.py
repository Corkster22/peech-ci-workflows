#!/usr/bin/env python3
"""PostToolUse hook (PPA-1597) - label a ticket a dispatched session creates.

pt-backlog requires a ticket whose origin was a finding surfaced while working
another ticket to carry the label ``spawned`` and a ``Relates`` link to the
ticket whose session surfaced it. Both were applied by hand, so the spawned
count read from them was a floor. This applies them the moment the ticket
exists, after the ticket-creating tool call returns, so the count becomes a
measurement.

What it writes
--------------
* The label ``spawned`` on the new ticket, added to whatever labels it has.
* One ``Relates`` link from the new ticket to each dispatched key the create
  payload names, or to every dispatched key where it names none. A multi-key
  dispatch cannot say which ticket's work surfaced the finding, and a Relates
  link to each is true where a guess at one is not.

What it does not do
-------------------
It labels and links. It refuses nothing, and PPA-1566's deny hook, which runs
before the create, is not changed. A ticket created in a session that holds no
dispatch is not a spawn and gets nothing. A create outside PPA gets nothing.

A failure never fails the tool call
-----------------------------------
The ticket already exists when this runs, so there is nothing left to refuse.
Every failure - an unreadable payload, a response carrying no key, an
unreachable Jira - is logged to ``LOG``, reported to the operator as a
``systemMessage`` where the ticket was created and not labelled, and exits 0.

The dispatched keys come from the deny hook's own ``dispatched_keys()``, so
the two hooks agree on what the session was dispatched to work.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = "mcp__atlassian-rovo__createJiraIssue"
LOG = Path.home() / ".claude" / "pt-spawn-label-hook.log"
LABEL = "spawned"
JIRA_TIMEOUT = 10

#: The new issue's key in the tool's response, as a JSON field whether the
#: response is an object or a JSON string nested inside one.
_KEY_RE = re.compile(r'\\?"key\\?"\s*:\s*\\?"(PPA-\d+)\\?"')
_BROWSE_RE = re.compile(r"/browse/(PPA-\d+)\b")
_ANY_KEY_RE = re.compile(r"\bPPA-\d+\b")


def log(reason, **fields):
    """Append one JSON record, and never raise."""
    record = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "reason": reason, **fields}
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _deny_hook():
    sys.path.insert(0, str(HERE))
    import deny_in_scope_spawn  # noqa: PLC0415

    return deny_in_scope_spawn


def created_key(tool_response):
    """The new ticket's key, or None where the response names none."""
    text = tool_response if isinstance(tool_response, str) \
        else json.dumps(tool_response)
    found = _KEY_RE.search(text) or _BROWSE_RE.search(text)
    return found.group(1) if found else None


def origins(tool_input, keys, new_key):
    """The dispatched keys the payload names, else every dispatched key."""
    deny = _deny_hook()
    text = f"{tool_input.get('summary', '')}\n" \
           f"{deny.flatten(tool_input.get('description', ''))}"
    named = [k for k in keys if k in set(_ANY_KEY_RE.findall(text))]
    return [k for k in (named or keys) if k != new_key]


def jira_write(method, path, body):
    """One authenticated write. Raises; the caller logs and allows."""
    deny = _deny_hook()
    sys.path.insert(0, str(deny.CLONE_SCRIPTS))
    from pt_transition import BASE, load_credentials  # noqa: PLC0415

    creds = load_credentials()
    auth = base64.b64encode(
        f"{creds['JIRA_EMAIL']}:{creds['JIRA_API_TOKEN']}".encode()).decode()
    request = urllib.request.Request(
        f"{BASE}{path}", method=method, data=json.dumps(body).encode(),
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=JIRA_TIMEOUT) as resp:
        resp.read()


def label_and_link(new_key, keys, write=None):
    """Add the label, then one Relates link per origin key."""
    write = write or jira_write
    write("PUT", f"/issue/{new_key}", {"update": {"labels": [{"add": LABEL}]}})
    for key in keys:
        write("POST", "/issueLink", {"type": {"name": "Relates"},
                                     "inwardIssue": {"key": key},
                                     "outwardIssue": {"key": new_key}})


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError) as exc:
        log("unreadable-payload", error=repr(exc))
        return 0
    new_key = None
    try:
        if payload.get("tool_name") != TOOL:
            log("other-tool", tool=payload.get("tool_name"))
            return 0
        tool_input = payload.get("tool_input") or {}
        if str(tool_input.get("projectKey", "")).upper() != "PPA":
            log("not-ppa", project=tool_input.get("projectKey"))
            return 0
        keys = _deny_hook().dispatched_keys(payload)
        if not keys:
            log("no-dispatch")
            return 0
        new_key = created_key(payload.get("tool_response"))
        if not new_key:
            log("no-key", keys=keys)
            return 0
        linked = origins(tool_input, keys, new_key)
        label_and_link(new_key, linked)
    except Exception as exc:  # noqa: BLE001 - never fails the tool call
        log("hook-failed", key=new_key, error=repr(exc))
        if new_key:
            print(json.dumps({"systemMessage": (
                f"pt-automation-hooks: {new_key} was created, but its "
                f"'{LABEL}' label and origin link were not written "
                f"({exc.__class__.__name__}). Apply them by hand.")}))
        return 0
    log("labelled", key=new_key, linked=linked,
        session_id=payload.get("session_id"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
