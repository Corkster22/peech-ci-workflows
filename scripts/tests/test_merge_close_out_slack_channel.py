"""PPA-1617 — merge-close-out.yml gives this repository's own push a channel.

On a push `inputs` is empty, so the held notice's channel falls back to the
SLACK_CHANNEL_DELIVERY_OPS repository secret. On workflow_call the caller's
slack_channel input is read first and still wins.
"""

from pathlib import Path

import yaml

WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/merge-close-out.yml")

EXPECTED = ("${{ inputs.slack_channel || "
            "secrets.SLACK_CHANNEL_DELIVERY_OPS }}")


def channel_settings():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return [(job, step.get("name"), step["env"]["SLACK_CHANNEL_DELIVERY_OPS"])
            for job, spec in jobs.items()
            for step in spec["steps"]
            if "SLACK_CHANNEL_DELIVERY_OPS" in step.get("env", {})]


def test_every_channel_setting_falls_back_to_the_repository_secret():
    settings = channel_settings()

    assert settings, "no step sets SLACK_CHANNEL_DELIVERY_OPS"
    for job, step, value in settings:
        assert value == EXPECTED, f"{job} / {step}: {value!r}"
