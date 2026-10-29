# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The Claude Desktop extension preview built by ``scripts/build_mcpb.py``.

The .mcpb is built from this repository but never belongs to it: the repository
root is the plugin folder, and the Claude plugin directory holds for review a plugin
that declares its MCP server as a .mcpb or ships a .zip or .mcpb file there. CI
builds the bundle (``.github/workflows/mcpb-preview.yml``) and git ignores it. These
tests keep its manifest in step with plugin.json, its contents to the expected
files, its build deterministic, and bundles out of the plugin.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/mcpb-preview.yml"
DOCS_URL = "https://docs.transgenia.org/odoo-tools/"
# The keys the MCPB 0.3 schema accepts at the top of a manifest; it rejects others.
MANIFEST_KEYS = {
    "$schema", "dxt_version", "manifest_version", "name", "display_name", "version",
    "description", "long_description", "author", "repository", "homepage",
    "documentation", "support", "icon", "icons", "screenshots", "localization", "server",
    "tools", "tools_generated", "prompts", "prompts_generated", "keywords", "license",
    "privacy_policies", "compatibility", "user_config", "_meta",
}
# security.yml's generic credential patterns, split so that guard does not match here.
CREDENTIALS = re.compile(r"BEGIN [A-Z ]*PRIVATE KEY|ODOO_API_KEY" r"=[A-Za-z0-9]{8,}"
                         r"|ODOO_PASSWORD" r"=[^<>]")
CANARY = "z" * 24  # stands for a secret; low entropy so no scanner takes it for one


@pytest.fixture(scope="module")
def mcpb() -> Any:
    spec = importlib.util.spec_from_file_location("build_mcpb",
                                                  ROOT / "scripts" / "build_mcpb.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_mcpb"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(mcpb: Any, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return mcpb.build(out_dir=tmp_path_factory.mktemp("dist"))


def _plugin() -> dict[str, Any]:
    return json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))


def _entries(bundle: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(bundle) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def _copy_sources(root: Path) -> Path:
    """The files a build reads, copied to ``root``."""
    for name in (".claude-plugin/plugin.json", "server/pyproject.toml", "LICENSE", "NOTICE",
                 "server/run_stdio.py"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, root / name)
    shutil.copytree(ROOT / "server/src", root / "server/src",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _git(*args: str) -> subprocess.CompletedProcess | None:
    """``git args`` in this checkout, or None without git or outside a checkout (a
    release zip has no .git)."""
    if shutil.which("git") is None:
        return None
    probe = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT,
                           capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        return None
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)


# -- the manifest follows plugin.json ---------------------------------------------------


def test_the_manifest_follows_plugin_json(mcpb: Any, built: Path) -> None:
    plugin = _plugin()
    manifest = json.loads(_entries(built)["manifest.json"])
    assert manifest == mcpb.make_manifest(plugin, mcpb.requires_python())
    assert built.name == f"odoo-tools-{plugin['version']}.mcpb"
    assert manifest["manifest_version"] == "0.3"
    assert manifest["name"] == plugin["name"] == "odoo-tools"
    assert manifest["version"] == plugin["version"]
    assert manifest["display_name"] == plugin["displayName"]
    assert manifest["author"] == plugin["author"] == {
        "name": "Transgenia", "email": "dev@transgenia.org", "url": "https://transgenia.org"}
    assert manifest["license"] == plugin["license"] == "MIT"
    assert manifest["repository"] == {"type": "git", "url": plugin["repository"]}
    assert manifest["homepage"] == manifest["documentation"] == plugin["documentationUrl"]
    assert manifest["documentation"] == DOCS_URL
    assert manifest["support"] == plugin["supportUrl"]
    assert manifest["support"] == f"{plugin['repository']}/blob/main/SUPPORT.md"
    assert manifest["privacy_policies"] == [plugin["privacyPolicyUrl"]]
    assert (ROOT / "SUPPORT.md").is_file()
    for words in ("Preview", "same MCP server and permission policy", "locally"):
        assert words in manifest["description"]


def test_every_setting_reaches_the_server_with_its_flags(mcpb: Any) -> None:
    plugin = _plugin()
    options = plugin["userConfig"]
    plugin_env = plugin["mcpServers"]["odoo"]["env"]
    manifest = mcpb.make_manifest(plugin)
    config = manifest["user_config"]
    env = manifest["server"]["mcp_config"]["env"]
    assert list(config) == list(options)
    for key, option in options.items():
        reference = "${user_config." + key + "}"
        variables = [name for name, value in plugin_env.items() if value == reference]
        assert variables, key
        assert all(env[name] == reference for name in variables), key
        for field in ("type", "title", "description", "required", "sensitive", "min", "max"):
            assert config[key].get(field) == option.get(field), (key, field)
        if "default" in option:
            assert config[key]["default"] == option["default"], key
        elif option["type"] == "string" and not option.get("required"):
            assert config[key]["default"] == "", key  # Claude Desktop then passes ""
    assert {key for key, option in config.items() if option.get("sensitive")} == {
        "odoo_api_key", "odoo_password"}
    required = {key for key, option in config.items() if option.get("required")}
    assert required == {"odoo_url", "odoo_db", "odoo_login"}
    assert not any("default" in config[key] for key in required)


def test_the_server_starts_from_the_bundle_folder(mcpb: Any) -> None:
    manifest = mcpb.make_manifest(_plugin(), mcpb.requires_python())
    server = manifest["server"]
    config = server["mcp_config"]
    assert server["type"] == "python" and server["entry_point"] == "server/run_stdio.py"
    assert config["command"] == "python3"
    assert config["args"] == ["${__dirname}/server/run_stdio.py"]
    assert config["platform_overrides"] == {"win32": {"command": "python"}}
    assert config["env"]["ODOO_AUDIT_DIR"] == "${HOME}/.odoo-tools/desktop/audit"
    assert config["env"]["ODOO_AUDIT_RETENTION_DAYS"] == "90"
    assert config["env"]["ODOO_DIAG_DIR"] == "${HOME}/.odoo-tools/desktop/diagnostics"
    assert "CLAUDE_PLUGIN" not in json.dumps(config)  # only Claude Code resolves those
    assert manifest["compatibility"] == {"platforms": ["darwin", "win32"],
                                         "runtimes": {"python": ">=3.9"}}
    # The MCPB 0.3 schema is strict: an unknown key anywhere fails validation.
    assert set(manifest) <= MANIFEST_KEYS
    assert set(config) <= {"command", "args", "env", "platform_overrides"}
    for option in manifest["user_config"].values():
        assert set(option) <= set(mcpb.OPTION_KEYS) and option["title"] and option["description"]


def _set(path: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def change(plugin: dict[str, Any]) -> None:
        *parents, last = path.split("/")
        node = plugin
        for part in parents:
            node = node[part]
        if value is None:
            del node[last]
        else:
            node[last] = value
    return change


@pytest.mark.parametrize(("change", "message"), [
    (_set("mcpServers/odoo/env/ODOO_CACHE_DIR", "${CLAUDE_PLUGIN_DATA}/cache"),
     "${CLAUDE_PLUGIN_DATA}"),
    (_set("mcpServers/odoo/env/ODOO_POLICY", None), "odoo_policy"),
    (_set("mcpServers/odoo/env/ODOO_EXTRA", "${user_config.odoo_extra}"),
     "${user_config.odoo_extra}"),
    (_set("userConfig/odoo_url/pattern", "^https://"), "pattern has no MCPB equivalent"),
    (_set("userConfig/odoo_db/description", None), "a title and a description"),
    (_set("mcpServers/odoo/command", "node"), "python3"),
    (_set("version", "1.5"), "not a semantic version"),
])
def test_what_claude_desktop_cannot_resolve_stops_the_build(
        mcpb: Any, change: Callable[[dict[str, Any]], None], message: str) -> None:
    plugin = copy.deepcopy(_plugin())
    change(plugin)
    with pytest.raises(mcpb.BuildError, match=re.escape(message)):
        mcpb.make_manifest(plugin)


# -- the bundle --------------------------------------------------------------------------


def _tracked_sources() -> list[str]:
    listed = _git("ls-files", "-z", "--", "server/src")
    names = [name for name in (listed.stdout.split("\0") if listed else []) if name]
    if names:
        return sorted(names)
    return sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / "server/src").rglob("*.py")
                  if "__pycache__" not in path.parts)


def test_the_bundle_holds_exactly_the_expected_files(built: Path) -> None:
    entries = _entries(built)
    copied = {"LICENSE", "NOTICE", "server/run_stdio.py", *_tracked_sources()}
    assert set(entries) == copied | {"manifest.json", "README.md"}
    for name in copied:
        assert entries[name] == (ROOT / name).read_bytes(), name
    readme = entries["README.md"].decode("utf-8")
    assert readme.isascii() and "(preview)" in readme
    for words in ("`python3` on macOS", "`python` on", "~/.odoo-tools/desktop/audit",
                  "kept 90 days", "LICENSE", "NOTICE"):
        assert words in readme, words
    assert not [name for name, data in entries.items() if CREDENTIALS.search(
        data.decode("utf-8", "replace"))]


def test_the_bundle_takes_no_secrets_or_caches(mcpb: Any, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root = _copy_sources(tmp_path / "repo")
    planted = {
        "server/src/odoo_mcp/__pycache__/server.cpython-313.pyc": b"cache",
        "server/src/odoo_mcp/stale.pyc": b"cache",
        "server/src/odoo_mcp/.env": CANARY.encode(),
        "server/src/odoo_mcp/.private/settings.py": CANARY.encode(),
        "server/src/.DS_Store": b"finder",
        "server/src/odoo_mcp/tests/test_planted.py": b"raise SystemExit(1)",
        "server/src/odoo_mcp/test_planted.py": b"raise SystemExit(1)",
        "server/src/odoo_mcp_tools.egg-info/PKG-INFO": b"Name: odoo-mcp-tools",
    }
    for name, data in planted.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    for variable in ("ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY", "ODOO_PASSWORD"):
        monkeypatch.setenv(variable, CANARY)  # the build never reads the environment
    entries = _entries(mcpb.build(root, tmp_path / "dist"))
    assert not set(planted) & set(entries)
    for name in entries:
        parts = name.split("/")
        assert not any(part.startswith(".") or part in ("__pycache__", "tests")
                       for part in parts), name
        assert not parts[-1].startswith("test_") and not name.endswith((".pyc", ".pyo")), name
    assert not [name for name, data in entries.items() if CANARY.encode() in data]


def test_an_unexpected_source_file_stops_the_build(mcpb: Any, tmp_path: Path) -> None:
    root = _copy_sources(tmp_path / "repo")
    stray = root / "server/src/odoo_mcp/notes.txt"
    stray.write_text("draft", encoding="utf-8")
    with pytest.raises(mcpb.BuildError, match="Python sources only"):
        mcpb.build(root, tmp_path / "dist")
    stray.unlink()
    try:
        (root / "server/src/odoo_mcp/linked.py").symlink_to(root / "LICENSE")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    with pytest.raises(mcpb.BuildError, match="symbolic link"):
        mcpb.build(root, tmp_path / "dist")


def test_two_builds_give_the_same_bytes(mcpb: Any, built: Path, tmp_path: Path) -> None:
    assert mcpb.build(out_dir=tmp_path / "again").read_bytes() == built.read_bytes()
    # File times and permissions do not reach the bundle.
    root = _copy_sources(tmp_path / "repo")
    first = mcpb.build(root, tmp_path / "one").read_bytes()
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (1_000_000_000, 1_000_000_000))
            path.chmod(0o600)
    assert mcpb.build(root, tmp_path / "two").read_bytes() == first == built.read_bytes()


def test_the_entries_are_sorted_files_with_fixed_metadata(mcpb: Any, built: Path) -> None:
    with zipfile.ZipFile(built) as archive:
        infos = archive.infolist()
    names = [info.filename for info in infos]
    assert names == sorted(names)
    for info in infos:
        # Claude Desktop's unpacker writes every entry as a file: no folder entries.
        assert not info.filename.endswith("/"), info.filename
        assert info.date_time == mcpb.FIXED_TIME
        assert info.create_system == 3 and info.external_attr >> 16 == 0o100644
        assert info.compress_type == zipfile.ZIP_DEFLATED


# -- the smoke test ------------------------------------------------------------------------


def test_the_bundled_server_answers_with_no_odoo_settings(
        mcpb: Any, built: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert mcpb.main(["--smoke", str(built)]) == 0
    out = capsys.readouterr().out
    assert "smoke: OK" in out
    assert re.search(r"tools/list: \d+ tools: .*odoo_version", out)
    assert "~/.odoo-tools/desktop/audit" in out  # ${HOME} reached the server


def test_the_smoke_test_catches_a_broken_default(mcpb: Any, built: Path, tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    folder = mcpb.unpack(built, tmp_path / "bundle")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    manifest["user_config"]["odoo_policy"]["default"] = "standrad"  # locks the server
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert mcpb.main(["--smoke", str(folder)]) == 1
    assert "does not list odoo_search_read" in capsys.readouterr().out


def test_the_offline_smoke_test_refuses_a_network(mcpb: Any, built: Path,
                                                  monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(mcpb, "reachable", lambda timeout=3.0: "1.1.1.1 port 443")
    assert mcpb.main(["--smoke", str(built), "--offline"]) == 1
    assert "is reachable" in capsys.readouterr().out


# -- bundles stay out of the plugin folder -----------------------------------------------


@pytest.mark.parametrize("name", [".claude-plugin/plugin.json", ".mcp.json",
                                  ".claude-plugin/marketplace.json"])
def test_the_plugin_never_refers_to_a_bundle(name: str) -> None:
    path = ROOT / name
    if not path.exists():
        assert name == ".mcp.json"  # the plugin declares its server in plugin.json
        return
    text = path.read_text(encoding="utf-8").lower()
    assert ".mcpb" not in text and ".dxt" not in text


def test_no_bundle_or_archive_is_tracked() -> None:
    listed = _git("ls-files", "-z")
    if listed is None:
        pytest.skip("not a git checkout")
    assert listed.returncode == 0, listed.stderr
    tracked = [name for name in listed.stdout.split("\0")
               if name.lower().endswith((".mcpb", ".dxt", ".zip"))]
    assert not tracked


@pytest.mark.parametrize("path", ["dist/odoo-tools-1.5.0.mcpb", "odoo-tools-1.5.0.mcpb",
                                  "server/odoo-tools.mcpb", "odoo-tools.dxt"])
def test_git_ignores_built_bundles(path: str) -> None:
    result = _git("check-ignore", "-q", "--no-index", path)
    if result is None:
        pytest.skip("not a git checkout")
    assert result.returncode == 0, path


# -- CI and docs ----------------------------------------------------------------------------


def test_the_preview_workflow_builds_validates_smokes_and_uploads() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    triggers = text.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert re.findall(r"^  ([a-z_]+):", triggers, re.MULTILINE) == ["pull_request",
                                                                     "workflow_dispatch"]
    assert re.search(r"^permissions:\n  contents: read$", text, re.MULTILINE)
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", use) for use in uses), uses
    pins = re.findall(r"@anthropic-ai/mcpb(\S*?)[\"'\s]", text)
    assert pins and all(re.fullmatch(r"@\d+\.\d+\.\d+", pin) for pin in pins), pins
    assert 'npx -y "$MCPB" validate' in text and 'npx -y "$MCPB" unpack' in text
    # The smoke test runs in an empty network namespace and checks that it is one.
    assert re.search(r"sudo unshare --net -- .*scripts/build_mcpb\.py \\\n\s*--smoke \S+ --offline",
                     text)
    upload = text.split("actions/upload-artifact@", 1)[1]
    assert "path: dist/*.mcpb" in upload and "archive: false" in upload


def test_the_desktop_doc_is_plain_ascii() -> None:
    text = (ROOT / "docs/desktop-extension.md").read_text(encoding="utf-8")
    assert text.isascii()  # no em or en dashes, curly quotes or emojis
    for words in ("free", "locally", "double-click", "drag", "Settings > Extensions",
                  "Python 3.9", "`python3` on macOS", "`python` on Windows", "Cowork",
                  "masks the API key", "claude.ai", "mobile"):
        assert words in text, words
