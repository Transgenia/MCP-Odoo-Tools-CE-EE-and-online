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
        condition = jobs[name].split("    if: ", 1)[1].split("\n", 1)[0]
        assert f"!({DRAFT_RUN})" in condition, name


def test_the_release_job_only_drafts_in_a_draft_run() -> None:
    script = _jobs()["github-release"]
    assert DRAFT_RUN in script  # runs although `container` was skipped
    draft_branch = script.split('if [ "$DRAFT" = "true" ]; then', 1)[1].split("elif", 1)[0]
    assert "--draft" in draft_branch
    assert script.count("--draft") == 1  # every other branch publishes or updates


def test_a_pending_draft_stops_the_run_before_anything_is_published() -> None:
    jobs = _jobs()
    preflight = jobs["preflight"]
    assert "isDraft" in preflight and "exit 1" in preflight
    # GitHub lists draft releases only to a token with push access: with the
    # workflow's contents: read the query saw no draft, and the guard never fired
    # (1.5.0). The job that holds the write token runs nothing but the query.
    assert "contents: write" in preflight
    assert "uses:" not in preflight and "checkout" not in preflight
    # a failing gh stops the run instead of reading as "no release"
    assert "set -euo pipefail" in preflight and "|| {" in preflight
    assert "needs: preflight" in jobs["verify"]
    assert "needs: verify" in jobs["container"]
    assert "Release state for this tag" not in jobs["verify"]


def test_a_draft_tag_never_holds_latest_back() -> None:
    meta = _jobs()["container"].split("- name: Image tags", 1)[1].split("- uses:", 1)[0]
    assert "--exclude-drafts" in meta and "git tag -l" not in meta


def test_the_moving_image_tags_fail_closed() -> None:
    # Before 1.5.1 a failing `gh release list` inside the pipe left only this tag in
    # the list, so a re-run of an older tag would have moved `latest` back to it.
    meta = _jobs()["container"].split("- name: Image tags", 1)[1].split("- uses:", 1)[0]
    query = meta.split("published=$(gh release list", 1)[1]
    assert query.index("|| {") < query.index("versions=")
    assert "exit 1" in query.split("versions=", 1)[0]


def test_a_skipped_tag_job_does_not_skip_the_rest() -> None:
    # On a tag push or a release event `tag` is skipped. A job whose condition has no
    # status function gets an implicit success(), which is false when any job up its
    # `needs` chain was skipped: on 2026-10-21 publishing the v1.4.1 draft ran
    # `verify` and skipped everything after it.
    for name, job in _jobs().items():
        if name == "tag":
            continue
        condition = job.split("    if: ", 1)[1].split("\n    runs-on", 1)[0] if "    if: " in job else ""
        assert "!cancelled()" in condition, name
