# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""A draft release must publish nothing.

``release.yml`` has a draft mode: a manual run with ``draft`` checked creates the tag
and a draft GitHub Release so a maintainer can review it. The jobs that reach users
(the container image, the image mirror and PyPI, which never accepts the same version
twice) must be skipped in that run and run when the draft is published. The workflow
is checked as text because the test dependencies have no YAML parser.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/release.yml"
DRAFT_RUN = "github.event_name == 'workflow_dispatch' && inputs.draft"
PUBLISHING_JOBS = ("container", "mirror", "pypi")


def _jobs() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z][a-z0-9-]*):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


def test_draft_is_a_boolean_input_off_by_default() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    draft = text.split("      draft:\n", 1)[1].split("\n  release:", 1)[0]
    assert "type: boolean" in draft and "default: false" in draft


def test_publishing_the_draft_runs_the_rest() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^  release:\n    types: \[published\]$", text, re.MULTILINE)


def test_jobs_that_reach_users_are_skipped_in_a_draft_run() -> None:
    jobs = _jobs()
    for name in PUBLISHING_JOBS:
        assert f"if: ${{{{ !({DRAFT_RUN}) }}}}" in jobs[name], name


def test_the_release_job_only_drafts_in_a_draft_run() -> None:
    script = _jobs()["github-release"]
    assert DRAFT_RUN in script  # runs although `container` was skipped
    draft_branch = script.split('if [ "$DRAFT" = "true" ]; then', 1)[1].split("elif", 1)[0]
    assert "--draft" in draft_branch
    assert script.count("--draft") == 1  # every other branch publishes or updates
