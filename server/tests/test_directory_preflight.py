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
import json
import os
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


def test_the_word_eval_is_a_note_and_never_a_failure(plugin: Path) -> None:
    put(plugin, "README.md", README + "\nThe eval word appears here.\n")
    report = _preflight().run(plugin)
    assert report["summary"]["error"] == 0 and report["summary"]["warning"] == 0
    assert ("info", "RUNTIME_FETCH_EXEC") in findings(plugin)


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
    assert set(report["sources"]) == {"checklist", "portal", "repo", "caution"}


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
