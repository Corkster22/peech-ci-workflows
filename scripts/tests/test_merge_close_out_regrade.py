"""PPA-1614 — the re-grade sweep in the callable merge-close-out.yml.

The sweep's rule is plan_transition(), covered in test_pr_merge_close_out.py.
What lives in YAML is only which job a run takes, so these tests read the
workflow and assert that routing.
"""

from pathlib import Path

import yaml

WORKFLOW = (Path(__file__).resolve().parents[2]
            / ".github/workflows/merge-close-out.yml")


def jobs():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def test_regrade_input_is_boolean_and_defaults_false():
    # PyYAML reads the bare key `on` as the boolean True.
    inputs = yaml.safe_load(WORKFLOW.read_text())[True]["workflow_call"]["inputs"]

    assert inputs["regrade"] == {"type": "boolean", "required": False,
                                 "default": False}


def test_close_out_job_is_skipped_when_regrade_is_true():
    assert jobs()["close-out"]["if"] == "${{ !inputs.regrade }}"


def test_regrade_job_runs_only_when_regrade_is_true():
    assert jobs()["regrade-held"]["if"] == "${{ inputs.regrade }}"


def test_regrade_job_runs_the_script_with_the_regrade_flag():
    last = jobs()["regrade-held"]["steps"][-1]

    assert last["run"] == (
        "python .peech-ci-workflows/scripts/pr_merge_close_out.py --regrade")
    assert "env" not in last, "the re-grade sends no Slack notice"


def test_regrade_job_writes_the_credential_file_before_it_runs():
    name = "Materialise the credential file pt_transition.py reads"
    close_out = {s.get("name"): s for s in jobs()["close-out"]["steps"]}
    steps = jobs()["regrade-held"]["steps"]
    names = [s.get("name") for s in steps]

    assert steps[names.index(name)] == close_out[name], (
        "the re-grade writes the credential file with the close-out's own step")
    assert names.index(name) < len(steps) - 1
