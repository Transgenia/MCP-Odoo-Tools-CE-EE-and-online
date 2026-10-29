#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Build the Claude Desktop extension preview, dist/odoo-tools-<version>.mcpb.

  python3 scripts/build_mcpb.py [--out-dir DIR]
  python3 scripts/build_mcpb.py --smoke BUNDLE [--offline]

The bundle (MCPB, manifest_version 0.3) is a zip of ``manifest.json``,
``server/run_stdio.py``, ``server/src/**`` (Python sources only: no caches, no
tests), ``LICENSE``, ``NOTICE`` and a short ``README.md``. The manifest is generated
from ``.claude-plugin/plugin.json``, so the version, the settings and the
environment the server gets never drift from the plugin, and the build stops on
anything Claude Desktop could not resolve. The zip is deterministic: sorted entries,
files only, a fixed timestamp and fixed permissions, so the same sources built with
the same Python give the same bytes.

``--smoke`` unpacks a bundle (or takes an unpacked folder) and starts its server the
way Claude Desktop would, with the manifest's environment and an empty settings
form: no Odoo settings at all. It checks that the server answers ``initialize`` and
``tools/list`` and writes its audit folder under the home folder. ``--offline``
first checks that this process has no network (CI runs it under
``sudo unshare --net``).

The .mcpb never goes into the plugin folder, which is this repository's root: the
Claude plugin directory holds for review a plugin that declares an MCP server as a
.mcpb or ships a .zip or .mcpb file there. CI builds it
(``.github/workflows/mcpb-preview.yml``) and offers it as a workflow artifact, and
git ignores ``dist/`` and ``*.mcpb``. See ``docs/desktop-extension.md``.

Standard library only; Python 3.9 or newer.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ".claude-plugin/plugin.json"
PYPROJECT = "server/pyproject.toml"
SERVER_KEY = "odoo"  # the plugin's mcpServers entry
SOURCES = "server/src"
COPIED = ("LICENSE", "NOTICE", "server/run_stdio.py")

MANIFEST_VERSION = "0.3"
DOCS_URL = "https://docs.transgenia.org/odoo-tools/"
BRANCH = "main"  # the branch the SUPPORT.md link points at
DESCRIPTION = (
    "Preview of odoo-tools by Transgenia for Claude Desktop: the same MCP server and "
    "permission policy as the Claude Code plugin, running locally on your computer and "
    "connecting only to the Odoo you set up (Community, Enterprise or Odoo Online, "
    "versions 10 to 19). Free, MIT licensed. Needs Python {python}."
)

PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}/"
# Claude Desktop has no plugin data folder: these folders go under the home folder.
# A plugin.json value that only Claude Code can resolve stops the build instead.
DESKTOP_ENV = {
    "ODOO_AUDIT_DIR": "${HOME}/.odoo-tools/desktop/audit",
    "ODOO_DIAG_DIR": "${HOME}/.odoo-tools/desktop/diagnostics",
}
# The variables Claude Desktop substitutes in mcp_config (MCPB MANIFEST.md), besides
# ${user_config.KEY}.
DESKTOP_VARIABLES = {"__dirname", "HOME", "DESKTOP", "DOCUMENTS", "DOWNLOADS",
                     "pathSeparator", "/"}
PLATFORMS = ("darwin", "win32")
WINDOWS_COMMAND = "python"  # python.org and the Microsoft Store both install python.exe

# plugin.json userConfig keys, in the order the manifest lists them; all exist in MCPB.
OPTION_KEYS = ("type", "title", "description", "required", "default", "multiple",
               "sensitive", "min", "max")
OPTION_TYPES = {"string", "number", "boolean", "directory", "file"}

FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # the earliest date a zip entry can carry
FILE_MODE = 0o100644  # a regular file, rw-r--r--
UNIX = 3  # "made by" Unix, so every unzip tool reads the mode above

SKIPPED_DIRS = {"__pycache__", "tests", "test", "build", "dist"}

_VARIABLE = re.compile(r"\$\{([^}]*)\}")
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
_VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")


class BuildError(Exception):
    """The sources cannot make a valid bundle; the message says why."""


# -- manifest -------------------------------------------------------------------------


def _field(data: dict[str, Any], key: str, where: str = "plugin.json") -> Any:
    if key not in data:
        raise BuildError(f"{where} has no {key!r}")
    return data[key]


def requires_python(root: Path = ROOT) -> str:
    """The Python requirement of ``server/pyproject.toml``, e.g. ``>=3.9``."""
    text = (root / PYPROJECT).read_text(encoding="utf-8")
    match = re.search(r'^requires-python\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise BuildError(f"{PYPROJECT} has no requires-python")
    return match.group(1)


def _python_text(spec: str) -> str:
    match = re.fullmatch(r">=\s*(\d+\.\d+)", spec)
    return f"{match.group(1)} or newer" if match else spec


def make_user_config(options: dict[str, Any]) -> dict[str, Any]:
    """plugin.json ``userConfig`` as MCPB ``user_config``: the same fields, plus an
    empty default for an optional string, so Claude Desktop passes "" rather than an
    unresolved ``${user_config.KEY}``."""
    config: dict[str, Any] = {}
    for key, option in options.items():
        where = f"userConfig.{key}"
        unknown = sorted(set(option) - set(OPTION_KEYS))
        if unknown:
            raise BuildError(f"{where}: {', '.join(unknown)} has no MCPB equivalent")
        if option.get("type") not in OPTION_TYPES:
            raise BuildError(f"{where}: type {option.get('type')!r} is not an MCPB type")
        if not option.get("title") or not option.get("description"):
            raise BuildError(f"{where}: MCPB needs a title and a description")
        entry = {name: option[name] for name in OPTION_KEYS if name in option}
        if entry["type"] == "string" and not entry.get("required") and "default" not in entry:
            entry["default"] = ""
        config[key] = entry
    return config


def _check_variables(mcp_config: dict[str, Any], user_config: dict[str, Any]) -> None:
    """Every ``${...}`` must be one Claude Desktop substitutes, and every setting must
    reach the server: a setting no variable uses would do nothing."""
    texts: list[tuple[str, str]] = [("args", arg) for arg in mcp_config.get("args", [])]
    texts += list(mcp_config.get("env", {}).items())
    for platform, override in mcp_config.get("platform_overrides", {}).items():
        texts += [(f"{platform} args", arg) for arg in override.get("args", [])]
        texts += list(override.get("env", {}).items())
    used = set()
    for where, text in texts:
        for name in _VARIABLE.findall(text):
            option = name[len("user_config."):] if name.startswith("user_config.") else None
            if option is not None and option in user_config:
                used.add(option)
            elif option is not None or name not in DESKTOP_VARIABLES:
                raise BuildError(f"{where}: Claude Desktop cannot resolve ${{{name}}}; map it "
                                 f"in scripts/build_mcpb.py (DESKTOP_ENV)")
    unused = sorted(set(user_config) - used)
    if unused:
        raise BuildError(f"no environment variable uses the settings {', '.join(unused)}")


def make_manifest(plugin: dict[str, Any], python: str | None = None) -> dict[str, Any]:
    """The MCPB manifest for ``plugin`` (plugin.json), for a Python ``python`` (default:
    the requires-python of server/pyproject.toml)."""
    python = python or requires_python()
    name, version = _field(plugin, "name"), _field(plugin, "version")
    if not (isinstance(name, str) and _NAME.fullmatch(name)):
        raise BuildError(f"plugin.json name {name!r} cannot name the bundle file")
    if not (isinstance(version, str) and _VERSION.fullmatch(version)):
        raise BuildError(f"plugin.json version {version!r} is not a semantic version")
    author = _field(plugin, "author")
    repository = str(_field(plugin, "repository")).rstrip("/")
    user_config = make_user_config(plugin.get("userConfig", {}))
    server = _field(_field(plugin, "mcpServers"), SERVER_KEY, "plugin.json mcpServers")
    args = server.get("args", [])
    if (server.get("command") != "python3" or len(args) != 1
            or not args[0].startswith(PLUGIN_ROOT)):
        raise BuildError(f"plugin.json must start the server as python3 {PLUGIN_ROOT}<file>")
    entry_point = args[0][len(PLUGIN_ROOT):]
    env = {key: DESKTOP_ENV.get(key, value) for key, value in server.get("env", {}).items()}
    for key, value in DESKTOP_ENV.items():
        env.setdefault(key, value)
    mcp_config = {
        "command": "python3",
        "args": ["${__dirname}/" + entry_point],
        "env": env,
        "platform_overrides": {"win32": {"command": WINDOWS_COMMAND}},
    }
    _check_variables(mcp_config, user_config)
    # The listing URLs come from plugin.json when it has them (directory listing fields).
    documentation = plugin.get("documentationUrl") or DOCS_URL
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "name": name,
        "display_name": _field(plugin, "displayName"),
        "version": version,
        "description": DESCRIPTION.format(python=_python_text(python)),
        "author": {key: author[key] for key in ("name", "email", "url") if key in author},
        "repository": {"type": "git", "url": repository},
        "homepage": documentation,
        "documentation": documentation,
        "support": plugin.get("supportUrl") or f"{repository}/blob/{BRANCH}/SUPPORT.md",
        "license": _field(plugin, "license"),
    }
    if plugin.get("privacyPolicyUrl"):
        # The MCPB spec asks for one when the extension connects to an outside service.
        manifest["privacy_policies"] = [plugin["privacyPolicyUrl"]]
    manifest.update({
        "server": {"type": "python", "entry_point": entry_point, "mcp_config": mcp_config},
        "compatibility": {"platforms": list(PLATFORMS), "runtimes": {"python": python}},
        "user_config": user_config,
    })
    return manifest


README = """\
# {display_name} {version} for Claude Desktop (preview)

A free preview of the odoo-tools MCP server by Transgenia as a Claude Desktop
extension. It runs the same MCP server and permission policy as the odoo-tools
plugin for Claude Code, locally on your computer, and sends nothing to Transgenia.

- Needs Python {python}, as `python3` on macOS and `python` on
  Windows. The server uses the Python standard library only and installs
  nothing.
- Settings: the Odoo URL, database and login, and an API key (Odoo 14 and later)
  or a password (Odoo 10 to 13). The API key and the password are sensitive
  settings, masked and stored securely by Claude Desktop.
- The audit trail goes to {audit}, kept {retention} days.
  The diagnostics folder is {diagnostics}.
- Not available on claude.ai on the web or on mobile: the server runs on your
  computer.

Documentation: {docs}
Support: {support}
Source: {source}

MIT License, see LICENSE. Third-party components and the clean-room statement:
NOTICE.
"""


def readme(manifest: dict[str, Any]) -> str:
    env = manifest["server"]["mcp_config"]["env"]

    def home(variable: str) -> str:
        return env.get(variable, "").replace("${HOME}", "~") or "(not set)"

    return README.format(
        display_name=manifest["display_name"], version=manifest["version"],
        python=_python_text(manifest["compatibility"]["runtimes"]["python"]),
        audit=home("ODOO_AUDIT_DIR"), diagnostics=home("ODOO_DIAG_DIR"),
        retention=env.get("ODOO_AUDIT_RETENTION_DAYS", "90"),
        docs=manifest["documentation"], support=manifest["support"],
        source=manifest["repository"]["url"],
    )


# -- files and zip --------------------------------------------------------------------


def _read(root: Path, name: str) -> bytes:
    path = root / name
    if path.is_symlink():
        raise BuildError(f"{name} is a symbolic link; the bundle takes regular files only")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BuildError(f"cannot read {name}: {exc.strerror or exc}") from None


def source_files(root: Path = ROOT) -> list[str]:
    """The Python sources under server/src, as bundle paths: no caches, no tests, no
    hidden files. Anything else there stops the build, so nothing ships by surprise."""
    base = root / SOURCES
    if not base.is_dir():
        raise BuildError(f"{SOURCES} not found under {root}")
    names = []
    for folder, dirs, files in os.walk(base):
        here = Path(folder)
        dirs[:] = sorted(name for name in dirs if not (
            name in SKIPPED_DIRS or name.startswith(".") or name.endswith(".egg-info")))
        for name in dirs:
            if (here / name).is_symlink():
                raise BuildError(f"{(here / name).relative_to(root).as_posix()} is a symbolic "
                                 "link; the bundle takes regular files only")
        for name in files:
            if (name.startswith((".", "test_")) or name.endswith((".pyc", ".pyo", "_test.py"))
                    or name == "conftest.py"):
                continue
            path = (here / name).relative_to(root).as_posix()
            if not name.endswith(".py"):
                raise BuildError(f"{path}: the bundle ships Python sources only; extend "
                                 "source_files() in scripts/build_mcpb.py if it belongs there")
            names.append(path)
    return sorted(names)


def bundle_files(root: Path, manifest: dict[str, Any]) -> dict[str, bytes]:
    """Every file of the bundle, by its path in the zip."""
    files = {
        "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        "README.md": readme(manifest).encode("utf-8"),
    }
    for name in (*COPIED, *source_files(root)):
        files[name] = _read(root, name)
    if manifest["server"]["entry_point"] not in files:
        raise BuildError(f"the entry point {manifest['server']['entry_point']} is not bundled")
    return files


def zip_bytes(files: dict[str, bytes]) -> bytes:
    """A deterministic zip: sorted file entries (no folder entries, which Claude
    Desktop's unpacker would try to write as files), one fixed timestamp, mode 0644."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.create_system = UNIX
            info.external_attr = FILE_MODE << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name], compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)
    return buffer.getvalue()


def build(root: Path = ROOT, out_dir: Path | None = None) -> Path:
    """Write ``<out_dir>/<name>-<version>.mcpb`` (default ``dist/``) and return its path."""
    try:
        plugin = json.loads((root / PLUGIN_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"cannot read {PLUGIN_JSON}: {exc}") from None
    manifest = make_manifest(plugin, requires_python(root))
    data = zip_bytes(bundle_files(root, manifest))
    folder = Path(out_dir) if out_dir is not None else root / "dist"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{manifest['name']}-{manifest['version']}.mcpb"
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    os.replace(partial, path)
    return path


# -- smoke ----------------------------------------------------------------------------

SMOKE_TIMEOUT = 60  # seconds for the whole exchange
PROTOCOL = "2025-06-18"
EXPECTED_TOOLS = ("odoo_version", "odoo_search_read")


def unpack(bundle: Path, folder: Path) -> Path:
    """Extract ``bundle`` into ``folder``, refusing what Claude Desktop's unpacker
    refuses or mishandles: paths outside the folder and folder entries."""
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if (info.filename.endswith("/") or info.filename.startswith("/") or not parts
                    or "\\" in info.filename or ".." in parts or ":" in parts[0]):
                raise BuildError(f"{bundle.name}: unexpected entry {info.filename!r}")
            target = folder.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    return folder


def launch(manifest: dict[str, Any], folder: Path, home: Path,
           platform: str = sys.platform) -> tuple[str, list[str], dict[str, str]]:
    """The command, arguments and environment Claude Desktop derives from the
    manifest when the settings form is empty: each setting's default, else ""."""
    config = manifest["server"]["mcp_config"]
    override = config.get("platform_overrides", {}).get(platform, {})
    command = override.get("command") or config["command"]
    args = override.get("args") or config.get("args", [])
    env = override.get("env") or config.get("env", {})
    values = {"__dirname": str(folder), "HOME": str(home), "pathSeparator": os.sep, "/": os.sep}
    for key, option in manifest.get("user_config", {}).items():
        default = option.get("default", "")
        if isinstance(default, bool):
            default = "true" if default else "false"
        values[f"user_config.{key}"] = str(default)

    def substitute(text: str) -> str:
        return _VARIABLE.sub(lambda m: values.get(m.group(1), m.group(0)), text)

    return command, [substitute(arg) for arg in args], {
        key: substitute(value) for key, value in env.items()}


def reachable(timeout: float = 3.0) -> str | None:
    """A public address this process can connect to, or None when it has no network."""
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53), ("2606:4700:4700::1111", 443)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return f"{host} port {port}"
        except OSError:
            continue
    return None


def _requests() -> bytes:
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                    "clientInfo": {"name": "build_mcpb-smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    return "".join(json.dumps(message) + "\n" for message in messages).encode("utf-8")


def _check(proc: subprocess.CompletedProcess, manifest: dict[str, Any],
           env: dict[str, str]) -> tuple[list[str], dict[str, Any], list[dict[str, Any]]]:
    """What is wrong with the server's answers, its serverInfo and its tools."""
    problems = []
    if proc.returncode != 0:
        problems.append(f"the server exited with status {proc.returncode}")
    replies: dict[Any, dict[str, Any]] = {}
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            problems.append(f"stdout holds a line that is not JSON-RPC: {line[:80]!r}")
            continue
        if isinstance(message, dict) and message.get("jsonrpc") == "2.0":
            replies[message.get("id")] = message
        else:
            problems.append(f"stdout holds a message that is not JSON-RPC 2.0: {line[:80]!r}")
    init = replies.get(1, {}).get("result") or {}
    info = {**(init.get("serverInfo") or {}), "protocolVersion": init.get("protocolVersion")}
    if not init:
        problems.append(f"initialize did not succeed: {replies.get(1)}")
    elif info.get("version") != manifest.get("version"):
        problems.append(f"initialize: the server reports version {info.get('version')!r}, "
                        f"the manifest {manifest.get('version')!r}")
    tools = (replies.get(2, {}).get("result") or {}).get("tools")
    tools = tools if isinstance(tools, list) else []
    names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
    if not names:
        problems.append(f"tools/list listed no tools: {replies.get(2)}")
    missing = [name for name in EXPECTED_TOOLS if name not in names]
    if names and missing:
        problems.append(f"tools/list does not list {', '.join(missing)} (a locked policy?)")
    if len(set(names)) != len(names):
        problems.append("tools/list lists a tool twice")
    for tool in tools:
        schema = tool.get("inputSchema") if isinstance(tool, dict) else None
        if not (isinstance(tool, dict) and tool.get("description")
                and isinstance(schema, dict) and schema.get("type") == "object"):
            problems.append(f"tool {tool!r:.60}: no description or object input schema")
    audit = env.get("ODOO_AUDIT_DIR", "")
    if audit and not (os.path.isdir(audit) and os.listdir(audit)):
        problems.append(f"the server wrote no audit file in {audit}")
    if b"Traceback" in proc.stderr:
        problems.append("the server logged a traceback on stderr")
    return problems, info, tools


def smoke(bundle: Path, *, offline: bool = False) -> int:
    """Run ``initialize`` and ``tools/list`` against the server of ``bundle``."""
    if offline:
        reached = reachable()
        if reached:
            print(f"smoke: FAILED: {reached} is reachable; --offline needs a process with "
                  "no network (for example under sudo unshare --net)")
            return 1
    with tempfile.TemporaryDirectory(prefix="odoo-tools-mcpb-") as tmp:
        work = Path(tmp)
        try:
            folder = bundle.resolve() if bundle.is_dir() else unpack(bundle, work / "bundle")
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            home = work / "home"
            home.mkdir()
            command, args, env = launch(manifest, folder, home)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, BuildError) as exc:
            print(f"smoke: FAILED: cannot read {bundle}: {exc}")
            return 1
        # A minimal environment, as an MCP client gives a stdio server, plus the
        # manifest's. -I -S -B: no PYTHON* variables, no site-packages, no .pyc files,
        # so only the standard library and the bundled sources can answer.
        base = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home)}
        if os.name == "nt":
            base.update(SYSTEMROOT=os.environ.get("SYSTEMROOT", ""), USERPROFILE=str(home))
        argv = [sys.executable, "-I", "-S", "-B", *args]
        try:
            proc = subprocess.run(argv, input=_requests(), capture_output=True, check=False,
                                  env={**base, **env}, timeout=SMOKE_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"smoke: FAILED: the server did not answer: {exc}")
            return 1
        problems, info, tools = _check(proc, manifest, env)
        python = sys.version.split()[0]
        network = "no network" if offline else "network not checked"
        print(f"smoke: {bundle} with Python {python} ({command} in the manifest), "
              f"no Odoo settings, {network}")
        if problems:
            for problem in problems:
                print(f"smoke: FAILED: {problem}")
            print(proc.stderr.decode("utf-8", "replace")[-3000:], end="")
            return 1
        print(f"smoke: initialize: {info.get('name')} {info.get('version')}, "
              f"protocol {info.get('protocolVersion')}")
        print(f"smoke: tools/list: {len(tools)} tools: "
              + ", ".join(tool["name"] for tool in tools))
        audit = env.get("ODOO_AUDIT_DIR", "")
        if audit:
            count = len(os.listdir(audit))
            print(f"smoke: audit: {count} file{'s' if count != 1 else ''} in "
                  f"~/{Path(audit).relative_to(home).as_posix()}")
        print("smoke: OK")
        return 0


# -- command line ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_mcpb.py",
                                     description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out-dir", type=Path,
                        help="folder for the bundle (default: dist/ at the repository root)")
    parser.add_argument("--smoke", type=Path, metavar="BUNDLE",
                        help="instead of building, run the server of BUNDLE (a .mcpb or an "
                        "unpacked folder) over stdio with no Odoo settings: initialize and "
                        "tools/list")
    parser.add_argument("--offline", action="store_true",
                        help="with --smoke: fail unless this process has no network")
    args = parser.parse_args(argv)
    if args.smoke is not None:
        if args.out_dir is not None:
            parser.error("--out-dir builds; --smoke only runs a bundle")
        return smoke(args.smoke, offline=args.offline)
    if args.offline:
        parser.error("--offline needs --smoke")
    try:
        path = build(out_dir=args.out_dir)
    except BuildError as exc:
        print(f"build_mcpb: {exc}", file=sys.stderr)
        return 1
    data = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        count = len(archive.infolist())
    print(f"{path}: {count} files, {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
