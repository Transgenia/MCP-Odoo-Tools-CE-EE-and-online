# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""v1.3.0: guided route, Transgenia support channels and the local sandbox script."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp.config import Settings
from odoo_mcp.server import McpServer
from odoo_mcp.support import (
    INSTRUCTIONS,
    SETUP_ENTRY,
    SUPPORT_EMAIL,
    SUPPORT_WHATSAPP_URL,
)
from odoo_mcp.telemetry import PLUGIN_VERSION

ROOT = Path(__file__).resolve().parents[2]


def _load_deploy_local() -> Any:
    spec = importlib.util.spec_from_file_location(
        "deploy_local", ROOT / "scripts" / "deploy_local.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_local"] = module
    spec.loader.exec_module(module)
    return module


dl = _load_deploy_local()


# ------------------------------------------------------------ MCP guidance


def test_initialize_sends_the_guided_route_instructions() -> None:
    result = McpServer(Settings()).initialize({"protocolVersion": "2025-06-18"})
    text = result["instructions"]
    assert text == INSTRUCTIONS
    assert SETUP_ENTRY in text and "/odoo-tools:deploy-local" in text
    assert SUPPORT_EMAIL in text and SUPPORT_WHATSAPP_URL in text
    assert len(text) < 2000  # clients may truncate long server instructions


def test_missing_credentials_point_to_setup_and_support() -> None:
    server = McpServer(Settings())  # no url/db/login/secret
    result = server.call_tool({"name": "odoo_version", "arguments": {}})
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "ODOO_URL" in text
    assert SETUP_ENTRY in text
    assert SUPPORT_EMAIL in text and SUPPORT_WHATSAPP_URL in text


def test_other_tool_errors_carry_no_support_line() -> None:
    server = McpServer(Settings(readonly=True))
    result = server.call_tool({"name": "odoo_create", "arguments": {"model": "x", "values": {}}})
    assert result["isError"] is True
    assert SUPPORT_EMAIL not in result["content"][0]["text"]


# ------------------------------------------------------ repository contract


def _text_files() -> list[Path]:
    skip = {".git", "node_modules", ".venv", "dist", "__pycache__"}
    files = []
    for path in ROOT.rglob("*"):
        if path.is_file() and not skip.intersection(path.parts) and path.suffix in {
            ".md", ".py", ".json", ".yml", ".yaml", ".toml", ".ts"
        }:
            files.append(path)
    return files


def test_whatsapp_links_use_the_international_number() -> None:
    # wa.me needs the country code: the bare 10-digit number opens a Brazilian (+55) one.
    links = set()
    for path in _text_files():
        links.update(re.findall(r"wa\.me/\d+", path.read_text(encoding="utf-8", errors="ignore")))
    assert links == {"wa.me/525580340405"}


def test_versions_agree_everywhere() -> None:
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    pyproject = re.search(
        r'^version = "([^"]+)"', (ROOT / "server/pyproject.toml").read_text(), re.MULTILINE
    )
    assert pyproject
    telemetry_fallback = re.search(
        r'return "([0-9.]+)"  # fallback', (ROOT / "server/src/odoo_mcp/telemetry.py").read_text()
    )
    assert telemetry_fallback
    image_tags = set(re.findall(
        r"ghcr\.io/transgenia/odoo-mcp-tools:([0-9.]+)",
        (ROOT / "commands/deploy-local.md").read_text(),
    ))
    assert {plugin, market["plugins"][0]["version"], pyproject.group(1),
            telemetry_fallback.group(1)} | image_tags == {plugin}
    assert f"## [{plugin}]" in (ROOT / "CHANGELOG.md").read_text()
    assert PLUGIN_VERSION  # importable either way


def test_entry_points_route_to_the_guided_skill() -> None:
    alias = (ROOT / "commands/setup-odoo-tools.md").read_text()
    assert SETUP_ENTRY in alias
    skill = (ROOT / "skills/odoo-setup-mcp/SKILL.md").read_text()
    for phase in ("Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5"):
        assert phase in skill
    assert "/odoo-tools:deploy-local" in skill and SUPPORT_EMAIL in skill


# ------------------------------------------------------------ sandbox script


def _mark_ready(box: Any) -> None:
    env = dl.read_env(box.env_file)
    env["ODOO_READY"] = "1"
    box.write_env(env)


def test_prepare_writes_private_files_and_reuses_secrets(tmp_path: Path) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    env = box.prepare("18.0", 8069, "sandbox", "es_MX", True, "transgenia")
    assert env["ODOO_IMAGE"] == "ghcr.io/transgenia/odoo:18.0"
    assert env["POSTGRES_IMAGE"] == "ghcr.io/transgenia/postgres:16"
    assert env["ODOO_READY"] == "0"
    assert "127.0.0.1:${ODOO_PORT:?}:8069" in box.compose_file.read_text()
    assert f"admin_passwd = {env['ODOO_MASTER_PASSWORD']}" in box.conf_file.read_text()
    if os.name == "posix":
        assert (box.env_file.stat().st_mode & 0o777) == 0o600
        assert (box.dir.stat().st_mode & 0o777) == 0o700
    _mark_ready(box)
    again = box.prepare("18.0", 8070, "other", "en_US", False, "dockerhub")
    for key in ("PG_PASSWORD", "ODOO_ADMIN_PASSWORD", "ODOO_MASTER_PASSWORD",
                "ODOO_DB", "ODOO_LANG", "ODOO_DEMO"):
        assert again[key] == env[key]  # an existing database keeps its settings
    assert again["ODOO_PORT"] == "8070" and again["ODOO_IMAGE"] == "odoo:18.0"
    assert again["ODOO_READY"] == "1"


def test_prepare_refuses_a_different_odoo_version_once_created(tmp_path: Path) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    box.prepare("17.0", 8069, "sandbox", "en_US", True, "transgenia")
    _mark_ready(box)
    with pytest.raises(dl.SandboxError, match="destroy"):
        box.prepare("18.0", None, None, None, None, "transgenia")


def test_a_failed_first_attempt_can_change_its_options(tmp_path: Path) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    first = box.prepare("17.0", 8069, "sandbox", "xx_BAD", True, "transgenia")
    retry = box.prepare("18.0", None, "demo", "es_MX", False, "transgenia")  # not ready yet
    assert (retry["ODOO_VERSION"], retry["ODOO_DB"], retry["ODOO_LANG"], retry["ODOO_DEMO"]) == (
        "18.0", "demo", "es_MX", "0")
    assert retry["PG_PASSWORD"] == first["PG_PASSWORD"]  # the volume may already exist


def test_plain_up_keeps_the_configured_port_and_version(tmp_path: Path) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    box.prepare("17.0", 8070, None, None, None, "transgenia")
    _mark_ready(box)
    again = box.prepare(None, None, None, None, None, "transgenia")
    assert again["ODOO_PORT"] == "8070" and again["ODOO_VERSION"] == "17.0"
    args = dl.build_parser().parse_args(["sandbox", "up"])
    assert args.port is None and args.odoo is None  # no parser default overrides them


def test_each_directory_is_its_own_compose_project(tmp_path: Path) -> None:
    one, two = dl.Sandbox(tmp_path / "a"), dl.Sandbox(tmp_path / "b")
    assert one.project != two.project
    assert one.project.startswith("odoo-tools-sandbox-")
    assert dl.Sandbox(dl.DEFAULT_DIR).project == "odoo-tools-sandbox"
    assert "name:" not in dl.COMPOSE_FILE  # the CLI flag is the single source


def test_passwords_are_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    env = box.prepare("18.0", 8069, "sandbox", "en_US", True, "transgenia")
    monkeypatch.setattr(dl, "compose_command", lambda: ["docker", "compose"])
    monkeypatch.setattr(dl, "check_docker_running", lambda: None)
    monkeypatch.setattr(dl.Sandbox, "running", lambda self: True)
    monkeypatch.setattr(dl.Sandbox, "pull", lambda self, e, r: e)
    monkeypatch.setattr(dl.Sandbox, "compose", lambda self, *a, **k: None)
    calls: list[tuple[str, str]] = []

    def fake_rpc(url: str, service: str, method: str, args: list[Any], timeout: float = 30) -> Any:
        calls.append((service, method))
        return {"version": {"server_version": "18.0"}, "list": [],
                "create_database": True, "authenticate": 2}.get(method)

    monkeypatch.setattr(dl, "rpc", fake_rpc)
    monkeypatch.setattr(dl, "wait_for_odoo", lambda url, t: {"server_version": "18.0"})
    assert dl.main(["sandbox", "up", "--dir", str(box.dir)]) == 0
    out = capsys.readouterr().out
    assert ("db", "create_database") in calls
    assert dl.read_env(box.env_file)["ODOO_READY"] == "1"  # marked only after success
    for secret in ("PG_PASSWORD", "ODOO_ADMIN_PASSWORD", "ODOO_MASTER_PASSWORD"):
        assert env[secret] not in out
    assert "dev@transgenia.org" in out and "wa.me/525580340405" in out


def test_pull_falls_back_and_tolerates_rate_limits(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    env = box.prepare("18.0", None, None, None, None, "transgenia")
    monkeypatch.setattr(dl.Sandbox, "compose",
                        lambda self, *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    present = {"odoo:18.0", "postgres:16"}  # Docker Hub copies cached, mirror absent
    monkeypatch.setattr(dl, "images_present",
                        lambda e: {e["ODOO_IMAGE"], e["POSTGRES_IMAGE"]} <= present)
    result = box.pull(env, "transgenia")
    assert result["ODOO_IMAGE"] == "odoo:18.0"
    assert dl.read_env(box.env_file)["ODOO_IMAGE"] == "odoo:18.0"
    present.clear()
    with pytest.raises(dl.SandboxError, match="rate-limiting"):
        box.pull(box.prepare(None, None, None, None, None, "transgenia"), "transgenia")


def test_destroy_requires_confirmation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert dl.main(["sandbox", "destroy", "--dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "--yes" in err and "dev@transgenia.org" in err


def test_missing_docker_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dl.shutil, "which", lambda name: None)
    with pytest.raises(dl.SandboxError, match="docs.docker.com"):
        dl.compose_command()


def test_legacy_docker_compose_v1_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dl.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(dl.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    with pytest.raises(dl.SandboxError, match="Compose v2"):
        dl.compose_command()


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_generated_compose_file_is_valid(tmp_path: Path) -> None:
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
    if probe.returncode != 0:
        pytest.skip("docker compose not available")
    box = dl.Sandbox(tmp_path / "sbx")
    box.prepare("18.0", 8069, "sandbox", "en_US", True, "transgenia")
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(box.dir), "-f", str(box.compose_file),
         "--env-file", str(box.env_file), "config", "--quiet"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
