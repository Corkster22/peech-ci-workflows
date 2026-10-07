"""PPA-1923 - no workflow-level display name carries an em dash.

The name a workflow file sets is the label people read on the GitHub Actions
screen, and the standing rule bars em dashes in text a person reads. Job names
are not checked here: branch protection matches some of them by exact text.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"
EM_DASH = "—"


def display_name(text: str) -> str:
    return yaml.safe_load(text)["name"]


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_a_workflow_display_name_carries_no_em_dash(path):
    assert EM_DASH not in display_name(path.read_text(encoding="utf-8"))


def test_a_display_name_with_an_em_dash_is_caught():
    fixture = f'name: "Pull Request {EM_DASH} Open"\non: push\njobs: {{}}\n'

    assert EM_DASH in display_name(fixture)
