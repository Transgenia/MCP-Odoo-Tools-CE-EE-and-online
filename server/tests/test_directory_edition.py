# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The code-free directory edition (distribution/directory).

The directory scans only the folder given as the plugin path (Anthropic's submission
guide), so the edition is a folder of this repository that holds nothing the review
portal restricts: Markdown, JSON and one PNG, with no hook, no server and no option.
These tests keep it that way and keep it honest on every surface (product rules 2, 3
and 5). They say nothing about whether the directory accepts it: only Anthropic decides.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EDITION = ROOT / "distribution" / "directory"
SCOPE = ("This edition of Odoo Tools contains no code and has no connection to Odoo. It adds "
         "no tool for Claude to read or change your Odoo, in any app. It does give Claude "
         "reference knowledge about Odoo 10 to 19 (what changed between versions) and tells you how to "
         "get help connecting Claude to your Odoo. Nothing is wrong with your Claude account, "
         "your Odoo or your computer.")
TEXT_FILES = ("README.md", "skills/odoo-start-here/SKILL.md", "commands/odoo-help.md")
REPO_BLOB = "https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online/blob/main/"


def _preflight() -> Any:
    spec = importlib.util.spec_from_file_location("directory_preflight",
                                                  ROOT / "scripts" / "directory_preflight.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["directory_preflight"] = module
    spec.loader.exec_module(module)
    return module


def _text(rel: str) -> str:
    return (EDITION / rel).read_text(encoding="utf-8")


def _manifest() -> dict[str, Any]:
    return json.loads(_text(".claude-plugin/plugin.json"))


def _files() -> list[str]:
    return sorted(p.relative_to(EDITION).as_posix() for p in EDITION.rglob("*") if p.is_file())


def test_the_edition_passes_the_preflight_with_no_errors_and_no_warnings() -> None:
    report = _preflight().run(EDITION)
    problems = [f for f in report["findings"] if f["severity"] != "info"]
    assert not problems, problems


def test_the_edition_holds_only_markdown_json_and_one_png() -> None:
    suffixes = {Path(name).suffix for name in _files() if Path(name).name != "LICENSE"}
    assert suffixes == {".md", ".json", ".png"}
    assert len(_files()) <= 20


def test_the_edition_has_no_hook_server_option_or_script() -> None:
    manifest = _manifest()
    for key in ("hooks", "mcpServers", "lspServers", "userConfig", "workflows", "channels",
                "dependencies", "settings"):
        assert key not in manifest, key
    assert not (EDITION / "hooks").exists() and not (EDITION / ".mcp.json").exists()
    for name in _files():
        data = (EDITION / name).read_bytes()
        assert not data.startswith(b"#!"), name
        if not name.endswith(".png"):
            assert b"\x00" not in data and data.decode("utf-8"), name


def test_the_edition_does_not_use_the_name_of_the_full_plugin() -> None:
    # The directory lists a plugin per folder, and a folder that is not the root is a new
    # submission. A name of its own also keeps the live odoo-tools listing untouched and
    # keeps the doctor of the full plugin from treating this one as a second copy.
    full = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    manifest = _manifest()
    assert manifest["name"] != full["name"] == "odoo-tools"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", manifest["name"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])


def test_the_license_is_the_same_as_the_full_plugins() -> None:
    assert _text("LICENSE") == (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert _manifest()["license"] == "MIT"


@pytest.mark.parametrize("rel", TEXT_FILES)
def test_every_surface_says_what_this_edition_is(rel: str) -> None:
    # Product rule 2: where the tools cannot run, say so in plain words the first time it
    # matters. This edition has no tools anywhere, so the same words stand in the README,
    # the entry skill and the command, and the plugin description says it too.
    text = re.sub(r"\s+", " ", _text(rel))
    assert SCOPE in text, rel
    assert "has no code and cannot connect to your Odoo" in _manifest()["description"]


def test_the_ways_forward_lead_to_transgenia_through_official_channels_only() -> None:
    # Product rule 3, item 2. Items 1 and 3 of the rule are not met as written (a synced
    # copy of this edition has no tools, and no hosted server exists yet): the product
    # owner decides, see docs/directory-channel.md.
    allowed_mail = {"dev@transgenia.org"}
    for rel in (*TEXT_FILES, "SUPPORT.md", "PRIVACY.md"):
        text = _text(rel)
        assert set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)) <= allowed_mail, rel
    for rel in ("README.md", "skills/odoo-start-here/SKILL.md", "commands/odoo-help.md",
                "SUPPORT.md"):
        text = _text(rel)
        assert "dev@transgenia.org" in text and "+52 55 8034 0405" in text, rel
        assert "https://wa.me/525580340405" in text, rel
        assert not re.search(r"\+\d[\d ()-]{8,}", text.replace("+52 55 8034 0405", "")), rel


def test_credentials_never_travel_through_a_conversation() -> None:
    # Product rule 5.
    skill = re.sub(r"\s+", " ", _text("skills/odoo-start-here/SKILL.md"))
    assert "Never ask for, accept or repeat an Odoo API key or password" in skill
    command = re.sub(r"\s+", " ", _text("commands/odoo-help.md"))
    assert "Never paste an Odoo API key or password" in command
    assert "Do not send API keys, passwords, private URLs or customer data" in _text("SUPPORT.md")


def test_the_edition_tells_claude_to_run_and_fetch_nothing() -> None:
    skill = re.sub(r"\s+", " ", _text("skills/odoo-start-here/SKILL.md"))
    assert "Do not run shell commands" in skill
    assert "Do not fetch web pages to obtain instructions" in skill
    assert "without running any command and without fetching anything" in _text(
        "commands/odoo-help.md")


def test_the_edition_claims_no_tool_or_command_of_the_full_plugin() -> None:
    for rel in _files():
        if rel.endswith((".md", ".json")):
            text = _text(rel)
            assert not re.search(r"\bodoo_[a-z_]+\b", text), rel  # no odoo_* tool names
            assert "/odoo-tools:" not in text and "odoo-doctor" not in text, rel
            assert "${CLAUDE_PLUGIN" not in text and "userConfig" not in text, rel


def test_the_edition_does_not_give_an_install_command_for_another_plugin() -> None:
    # A pointer for the user to the manual is fine. An install command for a plugin the
    # directory did not review could read as steering around its rules.
    for rel in TEXT_FILES:
        text = _text(rel)
        assert "/plugin install" not in text and "claude plugin install" not in text, rel
        assert "marketplace add" not in text, rel


def test_the_listing_links_point_at_files_that_exist_in_this_repository() -> None:
    manifest = _manifest()
    for key in ("supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"):
        url = manifest[key]
        assert url.startswith(REPO_BLOB), key
        assert (ROOT / url[len(REPO_BLOB):]).is_file(), key
    for key in ("documentationUrl", "homepage", "repository"):
        assert manifest[key].startswith("https://"), key
    assert (EDITION / manifest["icon"]).is_file()


def test_the_icon_is_a_png_of_512_pixels() -> None:
    data = (EDITION / ".claude-plugin" / "icon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(data[16:20], "big") == 512 and int.from_bytes(data[20:24], "big") == 512
    assert len(data) < 256 * 1024


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [name for name in out.decode("utf-8").split("\0") if name]


def test_the_edition_is_versioned_with_the_repository() -> None:
    # The folder a submission points at is what git holds, with no build step between.
    tracked = set(_tracked())
    for name in _files():
        assert f"distribution/directory/{name}" in tracked, name


def test_the_editions_own_icon_is_a_note_and_an_assumption() -> None:
    # Nothing in the portal's reviews shows that the plugin's own icon is exempt from
    # UNREAD_ASSET_REFERENCED, so the edition's report says so in a note, and its gate stays clean
    # on that assumption. If the portal holds the edition for it, this is the line to look at.
    report = _preflight().run(EDITION)
    named = [f for f in report["findings"] if f["code"] == "UNREAD_ASSET_REFERENCED"]
    assert [(f["severity"], f["path"]) for f in named] == [("info", ".claude-plugin/plugin.json")]
    assert report["summary"]["error"] == 0 and report["summary"]["warning"] == 0


def test_the_full_local_plugin_still_fails_the_four_portal_rules() -> None:
    # Calibration: Anthropic's check refused v1.6.1 for three rules and v1.6.3 for four (it added
    # the fields outside its lists). The preflight reproduces them for the repository root, which
    # is why the full plugin cannot be the plugin path of a submission and the edition is a
    # folder of its own.
    _tracked()  # skips outside a git checkout
    report = _preflight().run(ROOT, tracked=True)
    errors = {f["code"] for f in report["findings"] if f["severity"] == "error"}
    assert {"LOCAL_CODE_HOOK_COMMAND", "LOCAL_CODE_MCP_SERVER", "LOCAL_CODE_FILE_TYPE",
            "LOCAL_CODE_UNKNOWN_KEY"} <= errors


def test_the_root_shows_the_edition_as_a_claude_plugin_folder_that_is_not_its_own() -> None:
    # The portal's v1.6.3 text refuses "each .claude-plugin folder but the plugin's own". Scanned
    # from the root, the edition is such a folder; scanned as the plugin path, it is the plugin's
    # own and the folder has no error at all.
    _tracked()
    report = _preflight().run(ROOT, tracked=True)
    folders = {f["path"] for f in report["findings"] if f["code"] == "LOCAL_CODE_FILE_TYPE"
               and f["message"].startswith("a .claude-plugin folder")}
    assert "distribution/directory/.claude-plugin" in folders
    assert _preflight().run(EDITION)["summary"]["error"] == 0


# The portal's lists for v1.6.3 (commit 35f0235, printed 2026-11-13; the review names no file
# for its four blocking findings). The preflight was calibrated on these and on the v1.6.1 lists.
CALIBRATION_COMMIT = "35f0235a58a834d8f4d1f282a20193b817b5d105"  # the whole hash: it cannot grow ambiguous
PORTAL_V163 = {
    "MCP_FORWARDS_CREDENTIAL_ENV": {
        "scripts/build_mcpb.py", "scripts/deploy_local.py", "scripts/directory_preflight.py",
        "server/src/odoo_mcp/config.py", "server/tests/test_audit.py",
        "server/tests/test_diagnostics.py", "server/tests/test_directory_preflight.py",
        "server/tests/test_directory_preflight_gate.py", "server/tests/test_guided_route.py",
        "server/tests/test_install_check.py", "server/tests/test_mcpb_bundle.py",
        "server/tests/test_session_start_hook.py", ".claude-plugin/plugin.json"},
    "RUNTIME_FETCH_EXEC": {
        "CHANGELOG.md", "docs/design/json2-online-lite.md", "docs/directory-channel.md",
        "evals/README.md", "scripts/directory_preflight.py",
        "server/tests/test_directory_preflight.py",
        "server/tests/test_directory_preflight_gate.py", "server/tests/test_docs_surfaces.py"},
    "UNREAD_ASSET_REFERENCED": {
        "server/tests/test_directory_edition.py", "server/tests/test_directory_preflight.py",
        "server/tests/test_directory_preflight_gate.py",
        "distribution/directory/.claude-plugin/plugin.json"},
    "ASSETS_PASSED_UNREAD": {"distribution/directory/.claude-plugin/icon.png"},
}


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], check=False, cwd=ROOT, capture_output=True, timeout=60)


def _cannot_run(reason: str) -> None:
    """Skip, on a machine where the history is not there; fail in CI, where it must be.

    A skip is green: a job added without the full history would drop this guard in silence.
    GitHub sets CI=true in every job, and every job that runs these tests fetches the history.
    """
    if os.environ.get("CI"):
        pytest.fail(f"{reason}: the calibration test must run in CI (check out with "
                    "fetch-depth: 0)")
    pytest.skip(reason)


def _export(commit: str, target: Path) -> None:
    """The files of ``commit`` under ``target`` (a commit never changes, a work tree does)."""
    try:
        have = _git("cat-file", "-e", commit + "^{commit}").returncode == 0
        shallow = _git("rev-parse", "--is-shallow-repository").stdout.strip() == b"true"
    except (OSError, subprocess.SubprocessError) as exc:
        _cannot_run(f"git cannot be run here ({type(exc).__name__})")
        return
    if not have:
        _cannot_run("this checkout is shallow (a clone with history has the commit)" if shallow
                    else f"commit {commit} is not in this checkout")
        return
    archive = subprocess.run(["git", "archive", commit], cwd=ROOT, capture_output=True,
                             check=True, timeout=60).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            parts = PurePosixPath(member.name).parts
            if not member.isfile() or ".." in parts or PurePosixPath(member.name).is_absolute():
                continue
            handle = tar.extractfile(member)
            assert handle is not None
            path = target.joinpath(*parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(handle.read())


def test_the_preflight_still_finds_every_file_the_portal_listed_for_v163(tmp_path: Path) -> None:
    # A regression test of recall, on the exact files the portal scanned (not on this work tree,
    # which moves). A rule that stops finding one of them has lost what it was calibrated on.
    _export(CALIBRATION_COMMIT, tmp_path)
    report = _preflight().run(tmp_path)

    def where(code: str) -> set[str]:
        return {f["path"] for f in report["findings"] if f["code"] == code}

    for code, listed in PORTAL_V163.items():
        assert listed <= where(code), (code, sorted(listed - where(code)))
    # Where the reading fits exactly, keep it exact: no file the portal did not list.
    assert where("UNREAD_ASSET_REFERENCED") == PORTAL_V163["UNREAD_ASSET_REFERENCED"]
    assert where("ASSETS_PASSED_UNREAD") == PORTAL_V163["ASSETS_PASSED_UNREAD"]
    errors = {f["code"] for f in report["findings"] if f["severity"] == "error"}
    assert {"LOCAL_CODE_HOOK_COMMAND", "LOCAL_CODE_MCP_SERVER", "LOCAL_CODE_FILE_TYPE",
            "LOCAL_CODE_UNKNOWN_KEY"} <= errors
    # The review of v1.6.3 has no INVENTORY_GAPS, and the two SKILL.md that had one are quoted.
    assert not where("INVENTORY_GAPS") and not where("FRONTMATTER")
