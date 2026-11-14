#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Local preflight for a plugin folder before it is submitted to Anthropic's directory.

This is Transgenia's own check. It is NOT Anthropic's scanner, and a clean result does
not mean the directory will accept, list or publish anything: only Anthropic decides
that. It reads a plugin folder (by default ``distribution/directory``, the code-free
edition) and reports what the rules we know of would flag. Every finding names where
its rule comes from:

``checklist``  Anthropic's public pre-submission checklist
               (https://claude.com/docs/plugins/pre-submission-checklist.md).
``portal``     the text of the review portal for v1.6.1 (checked 2026-11-08) and v1.6.3
               (printed 2026-11-13). No public Anthropic page repeats it: command hooks,
               local MCP servers, files outside Markdown, text, JSON, YAML and a few image
               types, and config fields outside its lists are accepted only from Verified
               organizations.
``reference``  Claude Code's plugin manifest reference (https://code.claude.com/docs/en/plugins-reference.md).
``validator``  the output of ``claude plugin validate --profile directory`` of Claude Code 2.1.325
               (the flag is in its --help and not in the public CLI reference).
``repo``       a rule of this repository (docs/product-rules.md, .claude/CLAUDE.md).
``caution``    our own reading, kept stricter than the sources on purpose.

``python3 scripts/directory_preflight.py [PATH]`` exits 1 when a finding is an error,
and 2 when it cannot read the folder or the checker itself fails. ``--tracked`` inspects the files git tracks
(``git ls-files``), which is how the full local plugin at the repository root is
shown to fail the portal's four blocking rules. ``--fail-on warning`` also fails on
warnings, ``--json`` prints the report for tools.

The checker never repairs anything and never asks to disguise a file. A file that is
not accepted is removed from the folder, not renamed, re-encoded or hidden in another
type; a hook or a local server is not moved to another mechanism.

Calibration (2026-11-14). Two reports of one portal, whose rules changed between them (v1.6.1,
commit 182ace3, and v1.6.3, commit 35f0235), are all the data there is, so a rule here is a
reading of both and not a copy of the portal's logic. On the repository root as it was in those
two commits it finds the four blocking codes (the portal names no file for any of them) and every
file the portal listed (v1.6.3, v1.6.1): 13 of 13 and 10 of 10 for MCP_FORWARDS_CREDENTIAL_ENV (and
20 files more that the portal did not list on v1.6.3), 8 of 8 and 4 of 4 for RUNTIME_FETCH_EXEC (as
a note on the word 'eval', which one more file holds), 4 of 4 for UNREAD_ASSET_REFERENCED (and no
other on v1.6.3), and the five listing fields of UNKNOWN_KEY. The lists are in
server/tests/test_directory_edition.py. On the repository as it is now the counts differ, because
this module and the documents next to it name files and words that those commits did not.
These recalls are in-sample: the credential and asset rules were fitted after the lists were
seen (the credential list is also separated by file size about as well as by the environment
term), and only the word 'eval' was fitted on v1.6.1 and then held on v1.6.3. The edition folder
has no error and no warning, on one assumption: that the plugin's own icon is not held (it is
reported as a note, not a warning). Over-reporting is intended: a hold costs a review, a miss
costs a surprise. Its limits: LOCAL_CODE_UNKNOWN_KEY is judged for plugin.json, package.json,
a remote server's entry and its oauth; the portal's text also names marketplace.json, hooks files
and other MCP files, which are not judged here. The precise credential tier reads only a name
written the way a variable is (in quotes or in capitals), so a camelCase read such as
process.env.apiKey is not found by it, and Odoo's own self.env code can trip the broad tier. The
text of a finding about an image does not replace a look at the image: only its text is screened.
The text of an image is its runs of 8 or more characters of text (printable ASCII, a tab, a line
feed, a carriage return), read in the whole file and again in every place that can hold a message,
each place cut exactly, so that the bytes that frame it (a length, a type, a checksum) are no part of
it: in a PNG every chunk, in a JPEG every segment (the entropy-coded data after the scan header is no
place), in a GIF every extension (not its colour tables or its pictures), in a WebP every chunk. Only
the runs of a place are read, never its raw bytes: compressed or random bytes spell short words by
chance (npx, uvx, bunx), and reading them whole raised false warnings. What stays unread: a text of
fewer than 8 characters; a compressed chunk (zTXt, a compressed iTXt); UTF-16 text; a text broken by
any byte that is not text (a NUL or another control byte, an accented or CJK letter), whose pieces
are read apart and a short one is dropped; and a token inside a binary record (an IPTC caption, an
EXIF value) that sticks to the bytes that frame that record (a length, an offset): it is found only
when the byte before it is not a letter, a digit or an underscore. The sub-blocks of a GIF extension
are cut every 255 bytes and each one is read alone and all of them joined, so a word of a comment
that a cut falls in ('ta' and 'sk-...') can be read as a token: the price of finding a token that
starts a sub-block. The XMP packet that Adobe writes in a GIF is raw XML and no sub-blocks: it is
read only in the whole file. A noisy picture can still raise a warning by chance (a launcher word
inside a run: about 2 percent of 5 MiB of random bytes): look at the text of the image before
changing anything.

Speed. The patterns that read a line were measured for a cost that grows with the square of the
text: the doubling test of server/tests/test_directory_preflight_gate.py repeats each of several
hundred units (hand-written ones on six kinds of input, the words of this module's own patterns
on two) at a second size when the first is not trivial, and a unit that looks quadratic is measured
again and fails only if three tries agree (a burst of load on the machine does not repeat). The
readers of an image have a doubling test of their own, on six shapes, and so has the reading of
the code spans of a Markdown line, on two. The shapes that stalled the gate are kept as tests.
That measures the shapes it tries, and a quadratic whose cost is far below its floors is not seen:
it is not a proof for every input. A crafted file under the 5 MiB read limit can still be slow, and
the checker has no clock of its own.
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import json
import os
import posixpath
import re
import stat
import struct
import subprocess
import sys
import unicodedata
import urllib.parse
import zlib
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "distribution" / "directory"

Report = dict[str, Any]

DISCLAIMER = (
    "This is Transgenia's local preflight. It is not Anthropic's scanner and a clean "
    "result is not an approval: only Anthropic decides what the directory accepts."
)

CHECKLIST = "checklist"
REFERENCE = "reference"
VALIDATOR = "validator"
PORTAL = "portal"
REPO = "repo"
CAUTION = "caution"
SOURCES = {
    CHECKLIST: "https://claude.com/docs/plugins/pre-submission-checklist.md",
    REFERENCE: "Claude Code's plugin manifest reference: https://code.claude.com/docs/en/plugins-reference.md",
    VALIDATOR: ("the output of `claude plugin validate --profile directory` of Claude Code "
                "2.1.325 (the flag is in its --help, not in the public CLI reference; the "
                "checklist says that the plain command checks only that files are well-formed)"),
    PORTAL: ("review portal text for v1.6.1 (2026-11-08) and v1.6.3 (2026-11-13), not in any "
             "public Anthropic page"),
    REPO: "docs/product-rules.md and .claude/CLAUDE.md of this repository",
    CAUTION: "Transgenia's own stricter reading",
}

ERROR, WARNING, INFO = "error", "warning", "info"

MAX_FILES = 512
MAX_DEPTH = 40
MAX_PATH_CHARS = 200
MAX_PER_KIND = 25
MAX_JSON_BYTES = 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024
# checklist: "keep every file in the plugin folder under 5 MiB" (validation stops, images too)
MAX_READ_BYTES = 5 * 1024 * 1024

# The types the portal accepts from an organization that is not Verified.
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
DATA_SUFFIXES = {".json", ".yml", ".yaml"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}
# Names without a suffix that the portal names as allowed ("a license, a readme,
# .gitignore") when they are UTF-8 text.
EXEMPT_NAMES = {"license", "licence", "copying", "readme", ".gitignore"}
AMBIGUOUS_NAMES = {"notice", "authors", "codeowners", "security"}

# Held by the public checklist ("any other binary file, such as an .ico, .pdf, or .zip
# file or a compiled executable") and refused by this repository's rule 1.
HELD_SUFFIXES = {".ico", ".pdf", ".zip", ".mcpb", ".dxt", ".exe", ".dll", ".so", ".dylib",
                 ".whl", ".tar", ".gz", ".tgz", ".jar", ".bin", ".wasm", ".7z", ".rar"}

PACKAGE_CONFIG_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
    "pnpm-workspace.yaml", "yarn.lock", ".yarnrc", ".yarnrc.yml", ".npmrc", ".pnpmfile.cjs",
    "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "pipfile.lock", "poetry.lock",
    "uv.lock", "pip.conf", "cargo.toml", "cargo.lock", "go.mod", "go.sum", "gemfile",
    "gemfile.lock", "composer.json", "composer.lock", "bun.lockb", "deno.json", "mix.exs",
}
REQUIREMENTS = re.compile(r"^(?:[\w.]*[-_.])?requirements[\w.-]*\.txt$")

IMAGE_MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".ico": (b"\x00\x00\x01\x00",),
}
# What a file is when its content is a program or a package, whatever its name says.
BINARY_MAGIC = (
    (b"\x7fELF", "an ELF program"),
    (b"MZ", "a Windows program"),
    (b"\xfe\xed\xfa\xce", "a Mach-O program"),
    (b"\xfe\xed\xfa\xcf", "a Mach-O program"),
    (b"\xce\xfa\xed\xfe", "a Mach-O program"),
    (b"\xcf\xfa\xed\xfe", "a Mach-O program"),
    (b"\xca\xfe\xba\xbe", "a Mach-O or Java class file"),
    (b"\x00asm", "a WebAssembly module"),
    (b"PK\x03\x04", "a zip archive"),
    (b"\x1f\x8b", "a gzip archive"),
    (b"%PDF", "a PDF document"),
    (b"7z\xbc\xaf\x27\x1c", "a 7-zip archive"),
    (b"BZh", "a bzip2 archive"),
    (b"\xfd7zXZ\x00", "an xz archive"),
)

WEAK_MAGIC = {b"MZ", b"BZh"}

# Keys of plugin.json that the official reference lists (fetched 2026-11-10).
KNOWN_KEYS = {
    "$schema", "name", "displayName", "version", "description", "author", "homepage",
    "repository", "license", "keywords", "metadata", "icon", "documentationUrl",
    "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl", "defaultEnabled",
    "dependencies", "settings", "userConfig", "types", "channels", "skills", "commands",
    "agents", "hooks", "mcpServers", "lspServers", "outputStyles", "workflows",
    "experimental",
}
LISTING_FIELDS = {"icon", "documentationUrl", "supportUrl", "privacyPolicyUrl",
                  "termsOfServiceUrl"}
# The closed lists the portal prints for its blocking finding LOCAL_CODE_UNKNOWN_KEY (v1.6.3,
# printed 2026-11-13). The portal names no file for it: these are its words, and which file of a
# repository trips it is our reading (package.json is the one that fits).
PACKAGE_JSON_KEYS = {
    "name", "displayName", "version", "description", "keywords", "homepage", "bugs", "license",
    "author", "contributors", "maintainers", "funding", "repository", "private", "type", "files",
    "engines", "$schema",
}
REMOTE_SERVER_KEYS = {"type", "url", "headers", "timeout", "alwaysLoad", "oauth", "name", "title",
                      "displayName", "description"}
REMOTE_SERVER_TEXT_KEYS = {"name", "title", "displayName", "description"}
OAUTH_KEYS = {"clientId", "callbackPort", "authServerMetadataUrl", "scopes"}
OAUTH_SERVER_TYPES = {"http", "sse"}
PLAIN_VERSION = re.compile(r"[0-9A-Za-z.<>=^~|*\s-]*")
# Images (SVG apart: the portal did not count the SVG icon of v1.6.3) and fonts that a command, a
# script or a setting could name: the portal's UNREAD_ASSET_REFERENCED (checklist: "Don't refer
# to bundled images or fonts from commands, hooks, or scripts, or write their paths in backticks
# or a code block").
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf",
                  ".otf", ".eot")
# Every asset name ends with one of the suffixes: a text names an asset only where one of them
# is, so the check looks at those places and, at each, only for the lengths of the names that
# end with that suffix, never at every name in every line.
ASSET_SUFFIX_IN_TEXT = re.compile(r"\.(?:png|jpe?g|gif|webp|ico|woff2?|ttf|otf|eot)")
# The characters that end a file name in a text (the check does not look for a name that holds
# one of them, and says so), and the longest name it looks for.
ASSET_NAME_STOP = re.compile(r"[\s/\\\"'`()<>\[\]{},;|=*?:]")
MAX_ASSET_NAME = 255
# A maximal run of backticks: what opens and what closes an inline code span in Markdown.
BACKTICK_RUN = re.compile(r"`+")
# Keys that start a program on the user's computer or declare one.
LOCAL_CODE_KEYS = {
    "hooks": ("LOCAL_CODE_HOOK_COMMAND", PORTAL),
    "mcpServers": ("LOCAL_CODE_MCP_SERVER", PORTAL),
    "lspServers": ("LOCAL_CODE_OTHER", CAUTION),
    "workflows": ("LOCAL_CODE_OTHER", CAUTION),
    "types": ("LOCAL_CODE_OTHER", CAUTION),
    "channels": ("LOCAL_CODE_OTHER", CAUTION),
    "monitors": ("LOCAL_CODE_OTHER", CAUTION),
}
# Files that Claude Code loads from a default location and that start or declare a program
# on the user's computer (plugin manifest reference, "Standard layout"). A path is judged
# by its first component or its whole name, case-insensitively.
LOCAL_CODE_PATHS = (
    (".lsp.json", "a language server configuration: Claude Code starts the servers it lists"),
    ("monitors/", "monitors: shell commands that Claude Code runs in the background"),
    ("settings.json", "plugin settings: subagentStatusLine and statusLine run a command"),
    (".claude/settings.json", ("Claude Code settings inside the plugin: they can declare "
                               "hooks and a status line")),
    (".claude/settings.local.json", ("Claude Code settings inside the plugin: they can declare "
                                     "hooks and a status line")),
    ("bin/", ("a bin/ folder: its files go on the PATH of the Bash tool, and claude.ai and "
              "Cowork do not install a plugin that has one (product rule 1)")),
    ("workflows/", "workflows: JavaScript that runs inside Claude Code"),
)
RESERVED_NAMES = {"claude", "anthropic", "anthropics", "official", "plugin", "mcp", "test"}
WINDOWS_DEVICES = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
SYSTEM_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
COMPONENT_FOLDERS = ("skills", "commands", "agents", "hooks", "monitors", "bin", "workflows",
                     "output-styles", "themes")

CREDENTIAL_WORDS = {
    "key", "apikey", "accesskey", "secretkey", "privatekey", "password", "passwd", "pass", "pwd",
    "token", "authtoken", "accesstoken", "bearer", "secret", "credential", "credentials", "auth",
    "authorization", "cookie", "session", "passphrase", "pat", "private", "login",
}


def _credential_like(name: str) -> bool:
    """True when a variable, header, option or JSON key is named like a credential.

    Judged word by word (camelCase and punctuation split the words), so ``ODOO_API_KEY`` and
    ``X-Api-Key`` are credentials and ``monkey_name`` and ``X-Keyboard`` are not.
    """
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return any(word.lower() in CREDENTIAL_WORDS for word in re.split(r"[^A-Za-z0-9]+", spaced))
USER_CONFIG_REF = re.compile(r"^\$\{user_config\.([A-Za-z0-9_]+)\}$")
USER_CONFIG_ANY = re.compile(r"\$\{user_config\.([A-Za-z0-9_]+)\}")
AUTH_SCHEME = re.compile(r"(?:Bearer|Basic|Token)?", re.IGNORECASE)
ENV_REF = re.compile(r"\$\{([^}]+)\}")
OWN_VARIABLES = {"CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR"}
# A credential written into a file (checklist: "keep real credentials out of every file").
SECRET_PATTERNS = (
    ("a private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY(?: BLOCK)?-----")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("an AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a provider secret key (sk-...)", re.compile(r"\bsk-(?:ant-|live-|proj-)?[A-Za-z0-9_-]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    # (?<![A-Za-z0-9_-]) and not \b: a '-' is a boundary and a char of the token, so after \b every
    # 'eyJ' of a long run of 'eyJ-eyJ-' would start a scan of the rest of the run. The price: a token
    # that follows a hyphen ('x-token-eyJ...') is not read; one after a quote, a space, '=' or the
    # start of a line is.
    ("a JSON Web Token", re.compile(
        r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")),
)
# Where a program reads a credential from the user's machine: the environment of a shell, of
# a language runtime, or a well-known credential file.
SHELL_CRED_VAR = re.compile(
    r"(?:\$\{?|%)([A-Za-z0-9_]*(?:KEY|PASSWORD|PASSWD|TOKEN|BEARER|SECRET|CREDENTIAL)"
    r"[A-Za-z0-9_]*)\}?%?")
# The two runs of white space and the name before the credential word are bounded: unbounded, a
# word like ``env`` followed by a long run of spaces, or a long word made of
# ``GetEnvironmentVariable``, backtracks quadratically. The price: a name with more than 64
# characters before the credential word is not read through the five forms that only this pattern
# reads (ENV[...], GetEnvironmentVariable(...), Deno.env.get(...), process.env[...] and getenv NAME
# without a parenthesis); ENV_READ, which has no such bound, also reads os.environ, os.getenv,
# process.env.NAME, $env:NAME and getenv(...).
ENV_INDEX = re.compile(
    r"(?:process\.env|\bENV|Deno\.env\.get|GetEnvironmentVariable|os\.environ(?:\.get)?"
    r"|\bgetenv|\bGetenv)\s{0,8}[\[(.]?\s{0,8}[\"']?([A-Za-z0-9_]{0,64}(?:KEY|PASSWORD|PASSWD|TOKEN|"
    r"BEARER|SECRET|CREDENTIAL|PAT)[A-Za-z0-9_]*)", re.IGNORECASE)
CRED_FILES = re.compile(
    r"~/\.(?:aws/credentials|ssh/id_\w+|npmrc|netrc|pypirc|docker/config\.json|kube/config|"
    r"config/gh/hosts\.yml|git-credentials)", re.IGNORECASE)
ENV_READ = re.compile(
    r"(?:os\.environ(?:\.get)?\s*[\[(]|os\.getenv\s*\(|process\.env\.|\$env:|getenv\s*\()"
    r"\s*[\"']?([A-Za-z0-9_]*(?:KEY|PASSWORD|PASSWD|TOKEN|BEARER|SECRET|CREDENTIAL)"
    r"[A-Za-z0-9_]*)", re.IGNORECASE)
# A program that reads, copies or sets the environment, or names an env file, and that names a
# credential: the shape of the files the portal listed for MCP_FORWARDS_CREDENTIAL_ENV on v1.6.1 and
# v1.6.3 (its test files and tools too). It is our reading of two lists, not the portal's rule.
ENV_TOUCH = re.compile(
    r"os\\?\.environ|os\\?\.getenv|\bgetenv\b|process\\?\.env\b|\$env:|\.setenv\(|\bsetenv\(|"
    r"\benviron\b|read_env\b|dotenv|\.env\b|env_file|--env-file", re.IGNORECASE)
CREDENTIAL_TEXT = re.compile(
    r"api[_-]?key|password|passwd|\btoken\b|_token\b|\bsecret|bearer|credential|passphrase",
    re.IGNORECASE)
PROGRAM_SUFFIXES = {".py", ".ts", ".js", ".mjs", ".cjs", ".sh", ".bash", ".ps1", ".bat", ".cmd"}

# A command that downloads code and runs it at once. The portal flagged four files of v1.6.1
# and eight of v1.6.3 for this. None of the four held one (see docs/directory-channel.md); of the
# eight, this script and its two test files hold such commands as text. So the patterns are the
# genuine ones, not a copy of the portal's. Every rule is evaluated on one
# logical line (a backslash-newline joins two) with two linear searches, never with a
# pattern that can backtrack over the whole line.
DOWNLOADER = re.compile(r"\b(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod|"
                        r"downloadstring|downloadfile|certutil|bitsadmin)\b", re.IGNORECASE)
RUNNERS = {"sh", "bash", "zsh", "dash", "ksh", "python", "python3", "node", "perl", "ruby",
           "php", "iex", "invoke-expression", "pwsh", "powershell", "source"}
WRAPPERS = {"sudo", "env", "exec", "command", "nohup", "time", "xargs"}
FETCH_THEN = (
    ("a download that is run in a second step",
     re.compile(r"(?:&&|;)\s*(?:chmod\s+\+x|(?:ba|z)?sh\s|python3?\s|node\s|\./|start-process|"
                r"&\s)", re.IGNORECASE)),
    ("PowerShell download run with Invoke-Expression",
     re.compile(r"\b(?:iex|invoke-expression)\b", re.IGNORECASE)),
)
FETCH_SINGLE = (
    ("shell that runs the output of a download",
     re.compile(r"\b(?:ba|z)?sh\s+-c\s+[\"']?\$\(\s*(?:curl|wget)\b|\beval\s+[\"']?\$\(\s*"
                r"(?:curl|wget)\b|\b(?:source|\.)\s+<\(\s*(?:curl|wget)\b|\b(?:ba|z)?sh\s+<\(\s*"
                r"(?:curl|wget)\b", re.IGNORECASE)),
    ("a package launcher that fetches and runs code",
     re.compile(r"\b(?:npx|bunx|uvx|pipx\s+run|npm\s+exec|pnpm\s+dlx|yarn\s+dlx|uv\s+run)\b",
                re.IGNORECASE)),
    ("python -c that fetches a URL and runs it",
     re.compile(r"\bpython3?\s+-c\b", re.IGNORECASE)),
    ("node -e that runs code given on the command line",
     re.compile(r"\bnode\s+(?:-e|--eval|-p|--print)\b", re.IGNORECASE)),
    ("a download made with certutil or bitsadmin",
     re.compile(r"\b(?:certutil\b.{0,400}-urlcache|bitsadmin\b.{0,400}/transfer)",
                re.IGNORECASE)),
    ("an image or a container started from a registry",
     re.compile(r"\b(?:docker|podman)\s+run\b", re.IGNORECASE)),
)
INSTALL_FROM_URL = (re.compile(r"\b(?:pip3?\s+install|npm\s+(?:i|install)|cargo\s+install|"
                               r"gem\s+install|go\s+install|uv\s+pip\s+install)\b", re.IGNORECASE),
                    re.compile(r"(?:git\+|github:|--git\b|https?://)", re.IGNORECASE))
SVG_ACTIVE = re.compile(r"<script|\bon[a-z]+\s*=|<foreignObject|javascript:", re.IGNORECASE)
EVAL_WORD = re.compile(r"\beval\b", re.IGNORECASE)

INLINE_SHELL = re.compile(r"(?<![\\`])!`[^`\n]+`|^[ \t>*+-]*(?:`{3,}|~{3,})[ \t]*!", re.MULTILINE)
FRONTMATTER_FENCE = "---"
# The emoji blocks as code point ranges. A regex class with astral escapes reads as overlapping
# ranges to some scanners (CodeQL reports them as \ufffd-\ufffd); numbers say the same, plainly.
EMOJI_RANGES = ((0x1F000, 0x1F2FF), (0x1F300, 0x1FAFF), (0x2600, 0x27BF))


def is_emoji(ch: str) -> bool:
    return any(low <= ord(ch) <= high for low, high in EMOJI_RANGES)


COMPONENT_DIRS = ("skills/", "commands/", "agents/")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LOOKS_LIKE_SHELL = re.compile(
    r"^(?:set\s+-[a-z]+|export\s+\w+=|(?:curl|wget|sudo|chmod|rm|cp|mv|mkdir|echo|cd|"
    r"python3?|node|npm|npx|pip3?|bash|sh)\s+\S)", re.IGNORECASE)



@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    path: str
    message: str
    source: str
    line: int = 0

    def __post_init__(self) -> None:
        # A name or a message may hold a control character or a lone surrogate (a file name
        # that is not UTF-8): neither may reach a terminal or break the report.
        for field in ("path", "message"):
            object.__setattr__(self, field, _printable(getattr(self, field)))

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "severity": self.severity, "path": self.path,
                "line": self.line, "message": self.message, "source": self.source}

    def format(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.severity.upper():<7} {self.code:<27} {where}\n          {self.message} [{self.source}]"


def _printable(text: str) -> str:
    """``text`` with control characters and lone surrogates written out, never sent raw."""
    safe = text.encode("utf-8", "backslashreplace").decode("utf-8")
    return re.sub(r"[\x00-\x1f\x7f]", lambda m: f"\\x{ord(m.group()):02x}", safe)


def list_files(base: Path, tracked: bool) -> list[str]:
    """Posix paths relative to ``base``, sorted. Symbolic links are listed, never followed."""
    if tracked:
        # The repository is what is being judged, and its own config can name a program that git
        # runs when it looks at the tree (core.fsmonitor): this call must never run it. A name
        # that is not valid UTF-8 is kept (os.fsdecode) so that check_names reports it.
        out = subprocess.run(["git", "-c", "core.fsmonitor=false", "ls-files", "-z"],
                             cwd=str(base), capture_output=True, check=True, timeout=60).stdout
        return sorted(os.fsdecode(name) for name in out.split(b"\0") if name)
    # Iterative, so that a deep tree cannot exhaust the recursion limit of the interpreter CI
    # pins, and fail-closed: a folder that cannot be listed raises OSError (exit status 2).
    names: list[str] = []
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack:
        here, depth = stack.pop()
        with os.scandir(str(here)) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)
        for entry in entries:
            rel = (here / entry.name).relative_to(base).as_posix()
            if entry.name == ".git" and here == base and not entry.is_symlink():
                continue  # only the repository's own .git folder is skipped
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                names.append(rel)  # a file, a link or a special file: judged one by one
            elif depth + 1 > MAX_DEPTH:
                names.append(rel)  # a folder that is not walked: check_file reports it
            else:
                stack.append((here / entry.name, depth + 1))
    return sorted(names)


def classify(rel: str) -> str:
    """markdown, text, json, yaml, image, svg, exempt, ambiguous or other."""
    name = PurePosixPath(rel).name.lower()
    suffix = PurePosixPath(name).suffix
    # The portal lets a license, a readme and .gitignore stay, by name: only at the root,
    # so that a script cannot hide under one of those names in a folder.
    if name in EXEMPT_NAMES and "/" not in rel:
        return "exempt"
    if name in AMBIGUOUS_NAMES:
        return "ambiguous"
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix == ".txt":
        return "text"
    if suffix == ".json":
        return "json"
    if suffix in (".yml", ".yaml"):
        return "yaml"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix == ".svg":
        return "svg"
    return "other"


def _is_package_config(rel: str) -> bool:
    name = PurePosixPath(rel).name.lower()
    return name in PACKAGE_CONFIG_NAMES or bool(REQUIREMENTS.match(name)) \
        or ("/requirements/" in "/" + rel.lower() and name.endswith(".txt")) or name in {
        "constraints.txt", "pubspec.yaml", "environment.yml", "jsr.json", "bower.json",
        "vcpkg.json", ".yarnrc.yaml", "bunfig.toml", "uv.toml", "conda-lock.yml", "lerna.json",
        "turbo.json", "nx.json", "rush.json", "renovate.json", "package.resolved", "podfile.lock",
        "cartfile.resolved", "mix.lock", "lock.json"} or name.endswith((".lock", "-lock.json",
                                                                         "-lock.yaml"))


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _png_problem(data: bytes) -> str | None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "no PNG signature"
    pos, first, idat = 8, True, False
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            return "a chunk runs past the end of the file (truncated)"
        if (zlib.crc32(data[pos + 4:end - 4]) & 0xFFFFFFFF) != struct.unpack(">I", data[end - 4:end])[0]:
            return "a chunk with a wrong checksum"
        if first and kind != b"IHDR":
            return "the first chunk is not IHDR"
        first = False
        idat = idat or kind == b"IDAT"
        pos = end
        if kind == b"IEND":
            if pos != len(data):
                return "bytes after the last chunk (a second file appended?)"
            return None if idat else "no image data"
    return "no IEND chunk (truncated)"


def _gif_problem(data: bytes) -> str | None:
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data) < 14:
        return "no GIF signature"

    def skip_blocks(pos: int) -> int | None:
        while pos < len(data):
            size = data[pos]
            pos += 1
            if size == 0:
                return pos
            pos += size
        return None

    flags = data[10]
    pos: int | None = 13 + (3 * (1 << ((flags & 7) + 1)) if flags & 0x80 else 0)
    while pos is not None and pos < len(data):
        block = data[pos]
        if block == 0x3B:
            return None if pos == len(data) - 1 else "bytes after the GIF trailer"
        if block == 0x21:
            pos = skip_blocks(pos + 2)
        elif block == 0x2C and pos + 10 <= len(data):
            local = data[pos + 9]
            pos += 10 + (3 * (1 << ((local & 7) + 1)) if local & 0x80 else 0) + 1
            pos = skip_blocks(pos)
        else:
            return "a block that is not part of a GIF"
    return "no GIF trailer (truncated)"


def _jpeg_problem(data: bytes) -> str | None:
    if not data.startswith(b"\xff\xd8\xff"):
        return "no JPEG signature"
    pos, size = 2, len(data)
    while pos < size:
        if data[pos] != 0xFF:
            return "a marker is missing"
        while pos < size and data[pos] == 0xFF:
            pos += 1
        if pos >= size:
            break
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            return None if pos == size else "bytes after the end of the image"
        if marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if pos + 2 > size:
            return "truncated"
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > size:
            return "a segment runs past the end of the file (truncated)"
        pos += length
        if marker == 0xDA:  # entropy-coded data runs until the next real marker
            while pos + 1 < size and not (
                    data[pos] == 0xFF and data[pos + 1] != 0x00 and not 0xD0 <= data[pos + 1] <= 0xD7):
                pos += 1
            if pos + 1 >= size:
                return "no end-of-image marker (truncated)"
    return "no end-of-image marker (truncated)"


def _webp_problem(data: bytes) -> str | None:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return "no WebP signature"
    if struct.unpack("<I", data[4:8])[0] + 8 != len(data):
        return "the RIFF size does not match the file (truncated, or bytes appended)"
    return None if data[12:16] in (b"VP8 ", b"VP8L", b"VP8X") else "no WebP image chunk"


def _image_problem(suffix: str, data: bytes) -> str | None:
    """A complete image of the type its name says (checklist: complete PNG, JPEG, GIF, WebP)."""
    if suffix == ".png":
        return _png_problem(data)
    if suffix in (".jpg", ".jpeg"):
        return _jpeg_problem(data)
    if suffix == ".gif":
        return _gif_problem(data)
    if suffix == ".webp":
        return _webp_problem(data)
    return None if any(data.startswith(magic) for magic in IMAGE_MAGIC.get(suffix, ())) \
        else "no signature of that type"


# A run of text in the bytes of an image: printable ASCII, a tab (a command can be written with
# tabs), a line feed and a carriage return (a command can go on over two lines, with either line
# ending), eight characters or more. It is the only way a place is read, because a message is text.
# A text of fewer than eight characters is not read ('npx foo' is a warning in a text file and
# nothing in an image): runs that short are what compressed or random bytes produce all the time, and
# reading a place whole made short words such as npx or uvx appear in pictures. A run of eight starts
# at about one position in 3,500 of random bytes, and about one run in 60,000 holds a launcher word
# (5 of 305,582 runs over 1 GiB): a noisy picture of 5 MiB still gets a warning about 2 percent of
# the time, which is a reason to look and not an error. Every place is read the same way, the
# picture's own chunks included: their runs are the runs of the whole file, cut at the edge of the
# chunk, so that a token that sticks to a chunk type or a checksum is found there too.
PRINTABLE_RUN = re.compile(rb"[\t\n\r\x20-\x7e]{8,}")


def _png_texts(data: bytes) -> Iterable[bytes]:
    """The body of every chunk of a PNG, cut exactly: nothing of the length, the type or the
    checksum (a text chunk holds a keyword and a text, a private or a metadata chunk whatever it
    holds; the chunks of the picture hold bytes that are no text, of which only the runs are read)."""
    pos = 8
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        end = pos + 12 + length
        if end > len(data):
            return
        yield data[pos + 8:end - 4]
        pos = end


def _jpeg_texts(data: bytes) -> Iterable[bytes]:
    """The body of every segment of a JPEG, cut exactly (no length): the comment, the Exif, XMP and
    Photoshop (IPTC) metadata, the other application segments and the scan header. The
    entropy-coded data after the scan header is no place."""
    pos, size = 2, len(data)
    while pos < size:
        if data[pos] != 0xFF:
            return
        while pos < size and data[pos] == 0xFF:
            pos += 1
        if pos >= size:
            return
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            return
        if marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if pos + 2 > size:
            return
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > size:
            return
        yield data[pos + 2:pos + length]
        pos += length
        if marker == 0xDA:  # entropy-coded data runs until the next real marker
            while pos + 1 < size and not (
                    data[pos] == 0xFF and data[pos + 1] != 0x00 and not 0xD0 <= data[pos + 1] <= 0xD7):
                pos += 1


# The 258 bytes that end the XMP extension that Adobe writes in a GIF: the XML packet is raw after the
# 11 bytes 'XMP Data' and 'XMP', and this trailer makes a reader of sub-blocks walk through it to the
# end of the extension (any length byte found in the XML leads into the ramp 255, 254, ... 0).
XMP_TRAILER = b"\x01" + bytes(range(255, -1, -1)) + b"\x00"


def _gif_texts(data: bytes) -> Iterable[bytes]:
    """The sub-blocks of every extension of a GIF (comment, application, plain text, graphic
    control), each alone and all joined (a comment can run past 255 bytes). The XMP packet of Adobe
    (an application extension, 'XMP Data' and 'XMP', ended by a trailer of 258 bytes) is raw XML
    after its header, not sub-blocks: cut every 255 bytes it would start words in the middle, so it
    is left to the runs of the whole file. Any other extension, whatever its first sub-block says,
    is read as sub-blocks."""
    if len(data) < 14:
        return
    flags = data[10]
    pos = 13 + (3 * (1 << ((flags & 7) + 1)) if flags & 0x80 else 0)
    while pos < len(data):
        block = data[pos]
        if block == 0x21:
            label = data[pos + 1] if pos + 1 < len(data) else 0
            pos += 2
            parts = []
            while pos < len(data) and data[pos]:
                parts.append(data[pos + 1:pos + 1 + data[pos]])
                pos += 1 + data[pos]
            pos += 1
            adobe_xmp = (label == 0xFF and bool(parts) and parts[0] == b"XMP DataXMP"
                         and pos >= len(XMP_TRAILER) and data[pos - len(XMP_TRAILER):pos] == XMP_TRAILER)
            if not adobe_xmp:
                yield from parts
                yield b"".join(parts)
        elif block == 0x2C and pos + 10 <= len(data):
            local = data[pos + 9]
            pos += 10 + (3 * (1 << ((local & 7) + 1)) if local & 0x80 else 0) + 1
            while pos < len(data) and data[pos]:
                pos += 1 + data[pos]
            pos += 1
        else:
            return


def _webp_texts(data: bytes) -> Iterable[bytes]:
    """The payload of every chunk of a WebP: EXIF, XMP, the colour profile, the picture's own chunks
    (bytes that are no text, of which only the runs are read) and anything else."""
    pos = 12
    while pos + 8 <= len(data):
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        yield data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)


IMAGE_TEXT_READERS = {".png": _png_texts, ".jpg": _jpeg_texts, ".jpeg": _jpeg_texts,
                      ".gif": _gif_texts, ".webp": _webp_texts}


def _image_text_findings(rel: str, data: bytes) -> list[Finding]:
    """The text of an image, judged as a text is.

    The portal says that an image it lets through unread has its printable text screened. The
    owner's rules forbid commands in hidden places, and an image is one: a secret in an image is
    an error here, and a command that downloads and runs code is a warning, as the same command is
    in a text (our pattern, not the portal's). The text is the runs of text (PRINTABLE_RUN) of the
    whole file and of every place of a PNG, a JPEG, a GIF and a WebP that can hold a message, each
    place cut exactly: the bytes that frame it (a length, a chunk type, a checksum) are printable
    one time in three and then stick to its text, and the patterns keep their word boundaries.
    Only the runs of a place are read, never its raw bytes: compressed or random bytes spell short
    words (npx, uvx) by chance. A heuristic: a text of fewer than 8 characters, UTF-16 text, a
    compressed chunk and a text broken by any byte that is not text (a NUL or another control byte,
    an accented or CJK letter) are not read as one text, and a token inside a binary record (an IPTC
    caption, an EXIF value) that sticks to the bytes that frame the record is found only when the
    byte before it is not a letter, a digit or '_'. A word of a GIF comment that a cut of 255 bytes
    falls in can be read as a token ('ta' and 'sk-...'): the price of finding one that starts a
    sub-block. A noisy picture can raise a warning by chance (about 2 percent of 5 MiB of random
    bytes).
    """
    out: list[Finding] = []
    reader = IMAGE_TEXT_READERS.get(PurePosixPath(rel).suffix.lower())
    texts = [run.decode("ascii") for run in PRINTABLE_RUN.findall(data)]
    for piece in reader(data) if reader else ():
        texts.extend(run.decode("ascii") for run in PRINTABLE_RUN.findall(piece))
    text = "\n".join(texts)
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            out.append(Finding("SECRET_IN_FILE", ERROR, rel, f"the text of this image holds "
                               f"{label}: keep real credentials out of every file", CHECKLIST))
    for label, number in _fetch_exec(text):
        out.append(Finding("RUNTIME_FETCH_EXEC", WARNING, rel, f"the text of this image holds "
                           f"{label} (our pattern; the portal's own heuristic is not public)",
                           CAUTION))
        break
    return out


def check_file(base: Path, rel: str) -> tuple[list[Finding], str | None]:
    """The type, size and content findings of one file, and its text when it is text."""
    out: list[Finding] = []
    path = base / rel
    if path.is_symlink():
        out.append(Finding("INVENTORY_GAPS", ERROR, rel, "a symbolic link: a scan cannot be "
                           "assumed to follow it, so ship the file itself", CAUTION))
        return out, None
    try:
        info = path.stat()
    except OSError as exc:
        out.append(Finding("INVENTORY_GAPS", ERROR, rel, f"cannot be read ({exc.strerror})",
                           PORTAL))
        return out, None
    size = info.st_size
    if not stat.S_ISREG(info.st_mode):
        if stat.S_ISDIR(info.st_mode):
            out.append(Finding("INVENTORY_GAPS", ERROR, rel, "a folder where a file was expected: "
                               f"a tree more than {MAX_DEPTH} levels deep, which this check does "
                               "not walk, or a submodule. Nothing below it was inspected: "
                               "flatten the tree or ship plain files", CHECKLIST))
        else:
            out.append(Finding("INVENTORY_GAPS", ERROR, rel, "not a regular file (a pipe or a "
                               "device): ship regular files only", CHECKLIST))
        return out, None
    if info.st_mode & 0o111:
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "has the executable bit set: a "
                           "document, a data file or an image is never executable", CAUTION))
    kind = classify(rel)
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix in HELD_SUFFIXES:
        # The portal's own list of images allows ICO; the checklist holds it as a binary.
        outside = (" (the portal's own list of images allows ICO)" if suffix == ".ico"
                   else ", outside the portal's allowed types")
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel,
                           f"a {suffix} file: held by the public checklist as a binary"
                           f"{outside}, and refused by product rule 1", CHECKLIST))
    if _is_package_config(rel) and PurePosixPath(rel).name.lower() == "package.json":
        # The portal names "a package manager configuration file such as pnpm-workspace.yaml",
        # and in the same text lists the fields a package.json may hold and asks for "a plain JSON
        # object": it expects some package.json to pass. So this is a strict reading, not a
        # statement of the portal's, and the fields are judged by LOCAL_CODE_UNKNOWN_KEY.
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel,
                           "a package.json, read strictly as 'a package manager configuration "
                           "file'. The portal's own list of the fields a package.json may hold "
                           "(LOCAL_CODE_UNKNOWN_KEY) and the public checklist, which holds and "
                           "does not block one beside a lockfile, suggest that a plain one is "
                           "accepted, but this is not known", CAUTION))
    elif _is_package_config(rel):
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel,
                           "a package manager configuration file", PORTAL))
    elif kind == "other" and suffix not in HELD_SUFFIXES:
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel,
                           "a type outside Markdown, text, JSON, YAML and the allowed images "
                           "(read strictly: the portal does not define 'text')", PORTAL))
    elif kind == "svg":
        out.append(Finding("LOCAL_CODE_FILE_TYPE", WARNING, rel,
                           "SVG is not in the portal's list of images (PNG, JPEG, GIF, WebP, "
                           "ICO). The checklist lists SVG among text files, the portal did not "
                           "list the SVG icon of v1.6.3 for UNREAD_ASSET_REFERENCED (and names no "
                           "file for this finding), and Claude Code's validator says that SVG is "
                           "not accepted as the listing icon: a PNG is unambiguous", CAUTION))
    elif kind == "ambiguous":
        out.append(Finding("LOCAL_CODE_FILE_TYPE", WARNING, rel,
                           "a text file without a suffix that the portal does not name; give "
                           "it a .md suffix", CAUTION))
    if size >= MAX_READ_BYTES:
        out.append(Finding("DIR_LIMITS", ERROR, rel, "5 MiB or more: the directory stops "
                           "validating a plugin that holds a file this large", CHECKLIST))
        return out, None
    data = path.read_bytes()
    is_image = kind == "image"
    if size >= MAX_TEXT_BYTES and not is_image:
        out.append(Finding("DIR_LIMITS", ERROR, rel, "a non-image file of 256 KiB or more is "
                           "held for a reviewer and refused by product rule 1", CHECKLIST))
    # A byte order mark, a blank line or a space in front of #! does not make a script a
    # document: look at the first meaningful bytes, not the first two.
    lead = data.lstrip(b"\xef\xbb\xbf \t\r\n\x0b\x0c")
    if lead.startswith(b"#!"):
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel,
                           "starts with #! (after a byte order mark or blank space at most), "
                           "so it is a script whatever its name says", PORTAL,
                           data[:len(data) - len(lead)].count(b"\n") + 1))
    for magic, what in BINARY_MAGIC:
        if not data.startswith(magic):
            continue
        if magic in WEAK_MAGIC and b"\x00" not in data[:1024]:
            continue  # the letters MZ or BZh can start a plain text file
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel,
                           f"its content is {what}, whatever its name says", PORTAL))
        return out, None
    if is_image:
        problem = _image_problem(suffix, data)
        if problem:
            out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, f"named {suffix} but it is "
                               f"not a complete image of that type: {problem}", CHECKLIST))
        else:
            out.extend(_image_text_findings(rel, data))
            if suffix not in HELD_SUFFIXES:  # a held type already has its own, opposite, finding
                out.append(Finding("ASSETS_PASSED_UNREAD", INFO, rel, "a well-formed image: the "
                                   "portal lets it through without reading it as code (its "
                                   "printable text is still screened; this tool screens it too). "
                                   "A note; no action needed", PORTAL))
        return out, None
    if b"\x00" in data:
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "holds a NUL byte", PORTAL))
        return out, None
    text = _decode(data)
    if text is None:
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "is not UTF-8 text", PORTAL))
        return out, None
    if kind == "svg" and SVG_ACTIVE.search(text):
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "an SVG with a script, an "
                           "event handler, a foreignObject or a javascript: link: active "
                           "content, not an image", CHECKLIST))
    return out, text


def check_names(files: list[str]) -> list[Finding]:
    """The public checklist's rules on file and folder names (validation stops on them)."""
    out: list[Finding] = []
    seen: dict[str, str] = {}
    for rel in files:
        parts = rel.split("/")
        try:
            rel.encode("utf-8")
        except UnicodeEncodeError:
            out.append(Finding("INVENTORY_GAPS", ERROR, rel, "a name that is not valid UTF-8: "
                               "macOS and Windows cannot hold it", CHECKLIST))
        if len(rel) > MAX_PATH_CHARS:
            out.append(Finding("INVENTORY_GAPS", WARNING, rel, f"a path of more than "
                               f"{MAX_PATH_CHARS} characters: Windows stops at 260", CAUTION))
        for part in parts:
            stem = part.split(".")[0]
            if part.endswith((".", " ")) or re.search(r'[<>:"|?*\\\x00-\x1f]', part):
                out.append(Finding("INVENTORY_GAPS", ERROR, rel, f"'{part}' is not a name that "
                                   "is valid on Windows and macOS (a colon, a trailing dot or "
                                   "space, or another reserved character)", CHECKLIST))
                if re.search(r'[<>:"|?*\\\x00-\x1f]', part):
                    out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, f"'{part}' has a "
                                       "character that not every computer keeps (such as : or "
                                       "\\): the portal's v1.6.3 text asks to rename each such "
                                       "file. Change the characters of the name and nothing "
                                       "else: never the type or the content", PORTAL))
            elif WINDOWS_DEVICES.match(stem):
                out.append(Finding("INVENTORY_GAPS", ERROR, rel, f"'{part}' is a Windows device "
                                   "name", CHECKLIST))
            if part.lower() in SYSTEM_FILES or part.lower() == "__macosx":
                out.append(Finding("INVENTORY_GAPS", ERROR, rel, f"'{part}' is an operating "
                                   "system file or folder: the directory blocks it", CHECKLIST))
            if not part.isascii():
                out.append(Finding("INVENTORY_GAPS", WARNING, rel, f"'{part}' has non-ASCII "
                                   "letters; look-alike names are a disguise", CAUTION))
        if len(parts) > 1 and parts[0].lower() in COMPONENT_FOLDERS and parts[0] != parts[0].lower():
            out.append(Finding("MANIFEST", ERROR, rel, "a component folder with the wrong "
                               "capitalization", CHECKLIST))
        if len(parts) == 3 and parts[0] == "skills" and parts[2].lower() == "skill.md" \
                and parts[2] != "SKILL.md":
            out.append(Finding("MANIFEST", ERROR, rel, "a skill file must be spelled SKILL.md",
                               CHECKLIST))
        key = unicodedata.normalize("NFC", rel).lower()
        if key in seen and seen[key] != rel:
            out.append(Finding("INVENTORY_GAPS", ERROR, rel, f"differs only by capitalization "
                               f"from {seen[key]}", CHECKLIST))
        seen.setdefault(key, rel)
    return out


def check_local_code_paths(files: list[str]) -> list[Finding]:
    """Files that Claude Code loads by default and that declare or start a program."""
    out: list[Finding] = []
    for rel in files:
        low = rel.lower()
        for pattern, what in LOCAL_CODE_PATHS:
            hit = low.startswith(pattern) if pattern.endswith("/") else low == pattern
            if hit:
                out.append(Finding("LOCAL_CODE_OTHER", ERROR, rel, what + " (Claude Code's "
                                   "plugin reference, 'Standard layout')", CAUTION))
                break
    return out


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """The lines of ``text`` with their numbers, a backslash-newline (or backslash, carriage return,
    line feed) joining two of them."""
    out: list[tuple[int, str]] = []
    pending, start = "", 0
    for number, line in enumerate(text.split("\n"), start=1):
        if not pending:
            start = number
        body = line.removesuffix("\r")  # a file written on Windows ends its lines in CR LF
        if body.endswith("\\") and len(line) < 2000:
            pending += body[:-1] + " "
            continue
        out.append((start, pending + line))
        pending = ""
    if pending:
        out.append((start, pending))
    return out


def _fetch_exec(text: str) -> list[tuple[str, int]]:
    """(label, line) of every command that downloads code and runs it at once."""
    found: list[tuple[str, int]] = []
    for number, line in _logical_lines(text):
        down = DOWNLOADER.search(line)
        if down:
            tail = line[down.start():]
            for segment in tail.split("|")[1:]:
                words = segment.split()
                first = 0  # an index, not a slice: a long run of wrappers must stay linear
                while first < len(words) and posixpath.basename(words[first]).lower() in WRAPPERS:
                    first += 1
                word = re.match(r"[`'\"(]*([\w./\\-]+)", words[first]) if first < len(words) else None
                if word and posixpath.basename(word.group(1)).lower().removesuffix(".exe") in RUNNERS:
                    found.append(("a download piped to a shell or an interpreter", number))
                    break
            for label, then in FETCH_THEN:
                if then.search(line, down.end()):
                    found.append((label, number))
        for label, pattern in FETCH_SINGLE:
            match = pattern.search(line)
            if not match:
                continue
            if label.startswith("python -c") and not re.search(
                    r"urlopen|requests\.get", line[match.end():]):
                continue
            found.append((label, number))
        first, then = INSTALL_FROM_URL
        match = first.search(line)
        if match and then.search(line, match.end()):
            found.append(("an install from a URL or a git source", number))
    return found


def _visible(text: str, kind: str) -> str:
    """The text as a reader or a parser sees it: escapes decoded, HTML entities resolved."""
    seen = text
    if kind in ("json", "yaml", "markdown", "exempt", "ambiguous", "text"):
        seen = re.sub(r"\\u(d[89ab][0-9a-fA-F]{2})\\u(d[c-fC-F][0-9a-fA-F]{2})",
                      lambda m: chr(0x10000 + ((int(m.group(1), 16) - 0xD800) << 10)
                                    + (int(m.group(2), 16) - 0xDC00)), seen, flags=re.IGNORECASE)
        seen = re.sub(r"\\U([0-9a-fA-F]{8})",
                      lambda m: chr(min(int(m.group(1), 16), 0x10FFFF)), seen)
        seen = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), seen)
        seen = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), seen)
        seen = html.unescape(seen)
    return seen


def _unicode_findings(rel: str, seen: str) -> list[Finding]:
    """The repository's ASCII rule, on the text as it is read."""
    out: list[Finding] = []
    flagged: set[str] = set()
    for offset, ch in enumerate(seen):
        if ch.isascii() and (ch >= " " or ch in "\t\n\r"):
            continue
        category = unicodedata.category(ch)
        if ch.isascii():
            label, severity = "a control character", ERROR
        elif category == "Pd" or ch in "\u2212\u2e3a\u2e3b":
            label, severity = "a dash that is not ASCII", ERROR
        elif category in ("So", "Cf", "Cs", "Co", "Cc") or category == "Zs" or category == "Zl" \
                or category == "Zp" or is_emoji(ch):
            label, severity = "an emoji, a symbol or an invisible character", ERROR
        elif category.startswith(("P", "S")) and ch not in "\u00bf\u00a1":
            label, severity = "punctuation that is not ASCII", WARNING
        else:
            continue
        if label in flagged:
            continue
        flagged.add(label)
        out.append(Finding("TEXT_RULE", severity, rel, f"{label} (U+{ord(ch):04X}): public text "
                           "uses plain ASCII punctuation", REPO, _line_of(seen, offset)))
    return out


def _credential_read(text: str) -> tuple[str, int] | None:
    """(name, offset) of the first read of a variable named like a credential, or None.

    The name has to be written as a variable is: in quotes or in capitals, and be a credential
    word by word. PATH (it holds the letters PAT), a loop variable called key and the word
    Secrets after a dot are not credentials.
    """
    for pattern in (ENV_READ, ENV_INDEX, SHELL_CRED_VAR):
        for match in pattern.finditer(text):
            name = match.group(1)
            if not _credential_like(name):
                continue
            quoted = match.start(1) > 0 and text[match.start(1) - 1] in "\"'"
            if pattern is not SHELL_CRED_VAR and not (quoted or name.isupper()):
                continue
            return name, match.start()
    return None


def check_text(rel: str, text: str) -> list[Finding]:
    """Findings that read the words of a text file."""
    out: list[Finding] = []
    kind = classify(rel)
    for label, number in _fetch_exec(text):
        out.append(Finding("RUNTIME_FETCH_EXEC", WARNING, rel,
                           f"{label}: a command that downloads code and runs it at once "
                           "(our pattern; the portal's own heuristic is not public)",
                           CAUTION, number))
    match = EVAL_WORD.search(text)
    if match:
        out.append(Finding("RUNTIME_FETCH_EXEC", INFO, rel,
                           "holds the word 'eval'. Every file the portal listed for this code "
                           "held it (4 of 4 on v1.6.1, 8 of 8 on v1.6.3), and one file it did "
                           "not list holds it too (.gitignore): the best fit we have, not "
                           "confirmed by Anthropic. Documentation only: no action needed, and no "
                           "document is rewritten to avoid the word (the portal's rule is not "
                           "known)",
                           CAUTION, _line_of(text, match.start())))
    read = _credential_read(text)
    if read:
        out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel,
                           f"reads {read[0]} from the user's environment; ask for a "
                           "credential through a sensitive userConfig option instead",
                           CHECKLIST, _line_of(text, read[1])))
    elif PurePosixPath(rel).suffix.lower() in PROGRAM_SUFFIXES:
        touch, word = ENV_TOUCH.search(text), CREDENTIAL_TEXT.search(text)
        if touch and word:
            out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel,
                               "reads, copies or sets the environment, or names an env file, and "
                               f"names a credential ('{word.group(0)}'): the portal listed files "
                               "of this shape on v1.6.1 and v1.6.3, so expect a hold for a "
                               "reviewer", CAUTION, _line_of(text, touch.start())))
    match = CRED_FILES.search(text)
    if match:
        out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel,
                           f"names {match.group(0)}, a file that holds a credential of the user",
                           CHECKLIST, _line_of(text, match.start())))
    for label, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            out.append(Finding("SECRET_IN_FILE", ERROR, rel, f"{label}: keep real credentials "
                               "out of every file, documentation and examples included",
                               CHECKLIST, _line_of(text, match.start())))
    if kind in ("markdown", "text", "json", "yaml", "exempt", "ambiguous"):
        out.extend(_unicode_findings(rel, _visible(text, kind)))
    if kind in ("markdown", "text", "exempt", "ambiguous", "json", "yaml"):
        out.extend(_disguised_code(rel, text, kind))
    return out


# One line that is code and not prose, in the languages a document can hide. The lines are
# stripped before they get here, and only the first CODE_LINE_HEAD characters are matched, so the
# patterns that read to the end of a line cost the length of that head and not the length of the
# line. A call or a definition on a line longer than the head is told apart by its start and its
# end (LONG_CALL, LONG_DEF, in _is_code_line).
CODE_LINE_HEAD = 400
LONG_CALL = re.compile(r"[\w.]+\(")
LONG_DEF = re.compile(r"(?:async\s+)?def\s+\w+\s*\(|class\s+\w+")
CODE_LINE = re.compile(
    r"(?:"
    r"(?:import|from)\s+[\w.]+(?:\s+(?:import|as)\b.*)?;?\s*$|import\s+[\w.]+\s*;"
    r"|(?:async\s+)?def\s+\w+\s*\(.*\)\s*(?:->.*)?:\s*$|class\s+\w+\s*(?:\(.*\))?\s*:\s*$"
    r"|(?:const|let|var)\s+[\w${},\[\] ]+\s*=|function\s*\w*\s*\(|export\s+(?:default|const|function|class)\b"
    r"|module\.exports\s*=|exports\.\w+\s*="
    r"|require\s*[('\"]|use\s+strict|my\s+[$@%]\w+|sub\s+\w+\s*\{|print\s+['\"$]|puts\s+\S"
    r"|\$\w+\s*=|\$env:|(?:Invoke|Get|Set|New|Start|Remove)-[A-Z]\w+|\[Net\.|&\s+\$"
    r"|(?i:@?echo\s+off|setlocal|rem\s|set\s+\w+=)|::\s|<\?php|<\?="
    r"|(?i:DROP\s+\w+|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|CREATE\s+TABLE|ALTER\s+TABLE"
    r"|TRUNCATE\s+TABLE)\b"
    r"|(?:for|while)\s.*;\s*do\b|if\s+\[.*\]\s*;\s*then|fi\s*$|done\s*$|set\s+-[a-z]+\b|export\s+\w+="
    r"|(?:curl|wget|sudo|chmod|rm|cp|mv|mkdir|ls|cat|nc|ssh|scp|tar|kill|find|bash|sh|powershell|"
    r"certutil|python3?|node)\s+(?:-\S|[~./$'\"]|https?://)"
    r"|(?:git|docker|npm|npx|pip3?)\s+(?:clone|install|run|exec|push|pull|add|commit|-\S)"
    r"|[\w.]+\(.*\)(?:\s*;)?\s*$)")


def _is_code_line(line: str) -> bool:
    """True for a stripped line that is code: its head matches a pattern, it ends like a statement,
    or, when it is longer than the head, it starts and ends like a call or a definition."""
    if CODE_LINE.match(line[:CODE_LINE_HEAD]) or line.endswith((";", "{", "}")):
        return True
    if len(line) > CODE_LINE_HEAD:
        return (line.endswith(")") and bool(LONG_CALL.match(line))) \
            or (line.endswith(":") and bool(LONG_DEF.match(line)))
    return False


def _prose_lines(text: str) -> list[str]:
    """The lines of a document outside code fences, headings, lists, quotes and tables, stripped
    and with their inline code removed (a line that was only inline code is an empty line)."""
    lines: list[str] = []
    fenced = False
    for raw in text.lstrip("\ufeff").splitlines():
        line = raw.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or not line or line.startswith(("#", ">", "|", "<!--", "- ", "* ", "+ ")) \
                or re.match(r"\d+[.)]\s", line):
            continue
        lines.append(re.sub(r"`[^`]*`", "", line).strip())
    return lines


def _disguised_code(rel: str, text: str, kind: str = "markdown") -> list[Finding]:
    """A document that is really a program is a disguised executable, whatever its name."""
    body = text.lstrip("\ufeff")
    if kind == "json":
        try:
            data = json.loads(body, object_pairs_hook=_no_duplicates)
        except ValueError as exc:
            return [Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, f"named .json but not valid JSON "
                            f"({exc}): a data file must be what its name says", PORTAL)]
        if text.startswith("\ufeff"):
            return [Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "JSON with a byte order mark",
                            PORTAL, 1)]
        if isinstance(data, dict) and rel != ".claude-plugin/plugin.json" and (
                {"scripts", "dependencies", "devDependencies", "workspaces", "postinstall"}
                & set(data)):
            if PurePosixPath(rel).name == "package.json":
                # Not "by another name": the fields of a package.json are judged by
                # LOCAL_CODE_UNKNOWN_KEY, and the file by check_file.
                return []
            return [Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "a package manifest by another "
                            "name (scripts or dependencies)", PORTAL)]
        for key, value in _walk_json(data):
            if isinstance(value, str) and STRONG_CODE.search(value):
                return [Finding("DISGUISED_CODE", ERROR, rel, f"'{key}' holds a command or a "
                                "program in a string: a data file holds no code", CAUTION)]
            if _credential_like(key) and isinstance(value, str) and len(value) >= 6 \
                    and not re.search(r"\$\{|^<|^\{\{|your|example|placeholder|xxx", value, re.IGNORECASE):
                return [Finding("SECRET_IN_FILE", ERROR, rel, f"'{key}' holds a literal value: "
                                "keep real credentials out of every file", CHECKLIST)]
        return []
    if kind == "markdown" and ACTIVE_HTML.search(re.sub(r"(?s)(```|~~~).*?(?:\1|\Z)", " ", body)):
        return [Finding("LOCAL_CODE_FILE_TYPE", WARNING, rel, "a script tag, an event handler or "
                        "a javascript:/data: link: active content in a document", CHECKLIST)]
    if kind == "yaml" and (re.search(r"(?m)(?:^|[\s:\[{,-])!{1,2}[\w<]", body)
                           or re.search(r"(?m)^\t", body)):
        return [Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "YAML with a tag (!!python/..., "
                        "!!js/...) or a tab indent: a data file holds no code", PORTAL)]
    if "<?php" in body:
        return [Finding("DISGUISED_CODE", ERROR, rel, "holds a PHP tag, so it is a program, "
                        "not a document", CAUTION, _line_of(body, body.index("<?php")))]
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    if LOOKS_LIKE_SHELL.match(first) or first.startswith(("<?php", "@echo off")):
        return [Finding("DISGUISED_CODE", ERROR, rel, "starts like a shell script or a "
                        "program, not like a document", CAUTION, 1)]
    lines = _prose_lines(body)
    if not lines:
        return []
    code = sum(1 for ln in lines if ln and _is_code_line(ln))
    if code >= min(2, len(lines)) and code * 2 >= len(lines):
        return [Finding("DISGUISED_CODE", ERROR, rel, "reads like a program or a shell script, "
                        "not like a document", CAUTION, 1)]
    return []


STRONG_CODE = re.compile(
    r"child_process|execSync|os\.system|subprocess\.|Invoke-Expression|\biex\b|FromBase64String|"
    r"base64\s+-d|powershell(?:\.exe)?\s+-e|\beval\(|\bexec\(|\brequire\(|\|\s*(?:ba|z)?sh\b|"
    r"\bcurl\s|\bwget\s", re.IGNORECASE)
# The tag is read as a run of plain characters and quoted values ('<' may sit inside a value), so
# it stops at the next '<' outside a value: with [^>]* a text of many '<a' that never closes is
# read to its end from every '<'. The three ways to read a character start with different
# characters, so the pattern cannot backtrack in many ways.
# A handler in a tag is read two ways: a quote opens a value that can hold '<' or '>' (the first),
# and a quote that sits in an unquoted value or right after the tag name is only a character, as in
# HTML5, so that a stray quote before the handler hides nothing (the second). Each is linear. The
# price: the second reads a quote as a plain character, so a word that looks like a handler inside a
# quoted value (' onx=') is flagged as well, and a stray quote followed by a quoted '>' can still
# hide a handler. It is not a tokenizer: a warning here is a reason to look, and a clean file is not
# proof that no handler is there.
ACTIVE_HTML = re.compile(
    r"<script\b|<[a-z](?:[^<>\"']|\"[^\"]*\"|'[^']*')*\son[a-z]+\s*="
    r"|<[a-z][^<>]*\son[a-z]+\s*=|\]\(\s*(?:javascript|data):",
    re.IGNORECASE)


def _walk_json(data: object) -> Iterable[tuple[str, object]]:
    if isinstance(data, dict):
        for key, value in data.items():
            yield key, value
            yield from _walk_json(value)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_json(item)


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("a key appears twice")
    return dict(pairs)


def split_frontmatter(text: str) -> list[tuple[int, str]] | None:
    """The lines (with their numbers) between the leading --- fences, or None."""
    lines = text.lstrip("\U0000FEFF").splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return None
    block: list[tuple[int, str]] = []
    for number, line in enumerate(lines[1:], start=2):
        if line.strip() == FRONTMATTER_FENCE:
            return block
        block.append((number, line))
    return None


def _balanced(value: str) -> bool:
    """Brackets of a flow collection close, ignoring what is inside quotes."""
    depth, quote = 0, ""
    for ch in value:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quote


def _quoted_problem(value: str) -> str | None:
    quote, i = value[0], 1
    while i < len(value):
        ch = value[i]
        if quote == '"' and ch == "\\":
            i += 2
            continue
        if ch == quote:
            if quote == "'" and value[i + 1:i + 2] == "'":  # '' is an escaped quote
                i += 2
                continue
            rest = value[i + 1:].strip()
            return None if not rest or value[i + 1:i + 2] == " " and rest.startswith("#") else \
                f"text after the closing {quote} (an unescaped {quote} inside the value?)"
        i += 1
    return f"a quoted value that is not closed with {quote}"


def _plain_scalar_problem(value: str, key: str = "") -> str | None:
    """Why a YAML value would not parse (or is not a text value), or None."""
    if not value or value[0] in "|>":
        return None
    if value[0] in "\"'":
        return _quoted_problem(value)
    if value[0] in "[{":
        if key == "description":
            return "a list or a mapping, and the checklist wants one text value"
        return None if _balanced(value) else "a list or mapping whose brackets do not close"
    if value[0] in "&*!%@`":
        return f"a value that starts with {value[0]!r}, which YAML reserves"
    if value[:2] in ("- ", "? ", ": ") or value in ("-", "?"):
        return f"a value that starts with {value[:1]!r} and a space, which YAML reads as a " \
               "collection entry; quote the value"
    if ": " in value or value.endswith(":"):
        return "an unquoted value that holds ': ' (a colon and a space), so a strict YAML " \
               "parser reads it as a mapping; quote the value"
    if " #" in value:
        return "an unquoted value that holds ' #', which YAML reads as a comment; quote it"
    return None


HOOKS_KEY = re.compile(r"""(?im)(?:^[ \t]*|[{,][ \t]*)["']?hooks["']?[ \t]*:""")
SHELL_TOOL = re.compile(r"\b(?:Bash|PowerShell|Shell)\b")
# allowed-tools: "*" pre-approves every tool, the shell included.
WILDCARD_TOOL = re.compile(r"""(?m)(?::[ \t]*|^[ \t]*-[ \t]*|[\[,][ \t]*)["']?\*["']?[ \t]*(?:$|[,\]])""")


def _is_component(rel: str, extra: Iterable[str] = ()) -> bool:
    """A skill (SKILL.md), a command or an agent file: the files that need a frontmatter.

    A supporting document inside a skill's folder is not one (the checklist asks for a
    frontmatter in each skill, command and agent file).
    """
    return (bool(re.fullmatch(r"skills/[^/]+/SKILL\.md", rel)) or rel == "SKILL.md"
            or (rel.startswith(("commands/", "agents/")) and rel.lower().endswith(".md"))
            or rel in extra)


def _loads_instructions(rel: str, extra: Iterable[str] = ()) -> bool:
    """Any Markdown file under a component folder: inline shell syntax is judged in all of them."""
    return rel.startswith(COMPONENT_DIRS) or rel == "SKILL.md" or rel in extra


def _field_text(block: list[tuple[int, str]], name: str) -> str:
    """The text of one top-level frontmatter field: its own line, and the indented
    or list lines under it (a YAML list may sit at the same indent as its key). Other fields,
    a description for one, are not part of it."""
    parts: list[str] = []
    inside = False
    for _, line in block:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in " \t-":
            if inside:
                parts.append(line)
            continue
        key, sep, _ = line.partition(":")
        inside = bool(sep) and key.strip().strip("\"'").strip().lower() == name
        if inside:
            parts.append(line)  # the colon stays: the wildcard test looks for it
    return "\n".join(parts)


def check_frontmatter(rel: str, text: str, extra: Iterable[str] = ()) -> list[Finding]:
    """YAML sanity of the frontmatter of a skill, a command or an agent."""
    out: list[Finding] = []
    block = split_frontmatter(text)
    is_component = _is_component(rel, extra)
    if block is None:
        if is_component and PurePosixPath(rel).suffix == ".md":
            out.append(Finding("FRONTMATTER", WARNING, rel, "has no frontmatter, so it has "
                               "no description", CAUTION))
        return out
    keys: dict[str, str] = {}
    for number, line in block:
        if line.startswith("\t"):
            out.append(Finding("FRONTMATTER", ERROR, rel, "a tab indent: YAML forbids tabs",
                               CAUTION, number))
        if not line.strip() or line.lstrip().startswith("#") or line[:1] in " \t-":
            continue
        key, sep, value = line.partition(":")
        if line.startswith("{"):  # a flow mapping on one line: judged by the hooks scan below
            continue
        if line.startswith("? "):
            key, sep, value = line[2:], ":", ""
        if not sep:
            out.append(Finding("FRONTMATTER", ERROR, rel, "a frontmatter line that is not "
                               "'key: value'", CAUTION, number))
            continue
        key, value = key.strip().strip("\"'").strip().lower(), value.strip()
        if key in keys:
            out.append(Finding("FRONTMATTER", ERROR, rel, f"'{key}' appears twice, which a "
                               "strict YAML parser rejects", CAUTION, number))
        keys[key] = value
        problem = _plain_scalar_problem(value, key)
        if problem:
            out.append(Finding("FRONTMATTER", ERROR, rel, f"'{key}' is {problem}. A strict "
                               "parser cannot read the component, which the portal may "
                               "report as INVENTORY_GAPS", CAUTION, number))
    if is_component and not keys.get("description"):
        out.append(Finding("FRONTMATTER", WARNING, rel, "no description in the frontmatter",
                           CAUTION))
    if not _loads_instructions(rel, extra):
        return out  # a Markdown file that Claude does not load (an eval prompt, a design note)
    raw = "\n".join(line for _, line in block)
    if HOOKS_KEY.search(raw):
        out.append(Finding("LOCAL_CODE_HOOK_COMMAND", ERROR, rel, "a hooks key in the "
                           "frontmatter (quoted, in any case or in a flow mapping too): the "
                           "portal's rule covers hooks of every type", PORTAL))
    for key in ("allowed-tools", "allowed_tools", "allowedtools", "tools"):
        if key in keys:
            granted = _field_text(block, key) or raw  # a form that cannot be located is judged whole
            if SHELL_TOOL.search(granted) or WILDCARD_TOOL.search(granted):
                out.append(Finding("LOCAL_EXEC_PREAPPROVED", ERROR, rel, "the frontmatter "
                                   "grants a shell: it would run commands on the user's "
                                   "computer without asking", CAUTION))
            break
    else:
        if rel.startswith("agents/"):
            out.append(Finding("AGENT_TOOLS_INHERITED", WARNING, rel, "an agent without a "
                               "tools list inherits every tool, a shell included", CAUTION))
    return out


def check_inline_shell(rel: str, text: str, extra: Iterable[str] = ()) -> list[Finding]:
    if not _loads_instructions(rel, extra):
        return []
    match = INLINE_SHELL.search(text)
    if not match:
        return []
    return [Finding("LOCAL_EXEC_INLINE_SHELL", ERROR, rel, "inline shell execution syntax: "
                    "it runs a command on the user's computer without asking, which is a "
                    "hook by another name", CAUTION, _line_of(text, match.start()))]


_MISSING = object()


def _load_json(base: Path, rel: str, out: list[Finding]) -> object:
    """The parsed JSON of ``rel``; ``_MISSING`` when there is no such file. A file that cannot
    be read, is not a regular file, is over 1 MiB or is not JSON adds a finding and gives None,
    like a JSON ``null`` (which adds none, so the caller must tell them apart)."""
    path = base / rel
    try:
        info = path.lstat()
    except FileNotFoundError:
        return _MISSING
    except OSError as exc:
        out.append(Finding("MANIFEST", ERROR, rel, f"cannot be read ({exc.strerror})", CHECKLIST))
        return None
    if not stat.S_ISREG(info.st_mode):
        out.append(Finding("MANIFEST", ERROR, rel, "is not a regular file (a link, a pipe or a "
                           "folder): ship the file itself", CHECKLIST))
        return None
    if info.st_size > MAX_JSON_BYTES:
        out.append(Finding("MANIFEST", ERROR, rel, "is larger than 1 MiB", CHECKLIST))
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except RecursionError:
        out.append(Finding("MANIFEST", ERROR, rel, "is nested too deeply to be read", CHECKLIST))
    except OSError as exc:
        out.append(Finding("MANIFEST", ERROR, rel, "cannot be read "
                           f"({exc.strerror or type(exc).__name__})", CHECKLIST))
    except ValueError as exc:
        out.append(Finding("MANIFEST", ERROR, rel, f"is not valid JSON ({exc})", CHECKLIST))
    return None


def check_hooks(base: Path, files: Iterable[str]) -> list[Finding]:
    out: list[Finding] = []
    for rel in files:
        if PurePosixPath(rel).name != "hooks.json" and not rel.startswith("hooks/"):
            continue
        data = _load_json(base, rel, out) if rel.endswith(".json") else None
        entries = 0
        if isinstance(data, dict):
            hooks = data.get("hooks", {})
            if "modules" in data:
                out.append(Finding("LOCAL_CODE_HOOK_COMMAND", ERROR, rel, "a mod (modules): "
                                   "code that runs in the app (the checklist's row on mods)",
                                   CHECKLIST))
            if isinstance(hooks, dict):
                for event, groups in hooks.items():
                    for group in groups if isinstance(groups, list) else []:
                        for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                            entries += 1
                            kind = hook.get("type", "command") if isinstance(hook, dict) else "?"
                            out.append(Finding(
                                "LOCAL_CODE_HOOK_COMMAND", ERROR, rel,
                                f"a {kind} hook on {event}: the portal refuses command hooks "
                                "from an organization that is not Verified, and its rule "
                                "covers hooks of every type", PORTAL))
        if not entries:
            out.append(Finding("LOCAL_CODE_HOOK_COMMAND", ERROR, rel, "a hooks file: the "
                               "folder holds hooks, which the portal's rule covers", PORTAL))
    return out


PRIVATE_SUFFIXES = ("localhost", "local", "internal", "lan", "home.arpa", "localdomain", "intranet",
                    "corp", "private", "test", "invalid", "example", "ts.net")
WILDCARD_DNS = ("nip.io", "sslip.io", "xip.io", "localtest.me", "lvh.me", "vcap.me", "traefik.me",
                "local.gd")
NUMERIC_HOST = re.compile(r"(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+)){0,3}", re.IGNORECASE)


def _public_url_problem(url: str) -> str | None:
    """Why ``url`` is not an https or wss URL to a host on the public Internet, or None."""
    if re.search(r"[\x00-\x20\x7f-\U0010ffff\\]", url):
        return "the URL holds a space, a control character, a backslash or a non-ASCII character"
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for a port that is not a number
    except ValueError:
        return "the URL does not parse"
    if parts.scheme.lower() not in ("https", "wss") or not parts.netloc:
        return "a remote server needs an absolute https:// or wss:// URL"
    if "@" in parts.netloc:
        return "the URL holds user information (user@host): a credential, or a host that is " \
               "not the one it looks like"
    host = (parts.hostname or "").rstrip(".")
    if not host or "%" in host:
        return "the host is empty or percent-encoded"
    if NUMERIC_HOST.fullmatch(host):
        return "the host is a number (decimal, hex, octal or short IPv4): a public URL uses a name"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        probe = getattr(address, "ipv4_mapped", None) or address
        if not probe.is_global:
            return "the host is a local or private address, so it is not a public URL"
        return None
    if "." not in host:
        return "the host has a single label (a local or intranet name), so it is not a public URL"
    if any(host == s or host.endswith("." + s) for s in PRIVATE_SUFFIXES):
        return "the host is local or private, so it is not a public URL"
    if any(host == s or host.endswith("." + s) for s in WILDCARD_DNS):
        return "a wildcard DNS name that resolves to the address written inside it"
    return None


def _check_server(rel: str, name: str, server: object, options: dict[str, object],
                  ) -> list[Finding]:
    out: list[Finding] = []
    label = f"MCP server '{name}'"
    if not isinstance(server, dict):
        return [Finding("LOCAL_CODE_MCP_SERVER", ERROR, rel, f"{label} is not an object",
                        CHECKLIST)]
    local = "command" in server or str(server.get("type")).lower() == "stdio"
    if local:
        out.append(Finding("LOCAL_CODE_MCP_SERVER", ERROR, rel, f"{label} starts as a "
                           "command on the user's computer; the portal accepts only a "
                           "server at a public URL from an organization that is not "
                           "Verified", PORTAL))
        out.append(Finding("LOCAL_MCP_SERVER", INFO, rel, f"{label} runs a local program (a "
                           "note in the portal)", PORTAL))
        out.append(Finding("STDIO_WEB_UNSUPPORTED", INFO, rel, f"{label} is a local (stdio) MCP "
                           "server: it runs in Claude Code and Cowork, not on claude.ai (a note "
                           "in the portal)", PORTAL))
    if "headersHelper" in server:
        out.append(Finding("LOCAL_MCP_SERVER", ERROR, rel, f"{label} builds its headers with "
                           "a helper command, which is a program on the user's computer (the "
                           "portal lists LOCAL_MCP_SERVER as a note and blocks a server that "
                           "starts as a command: this is our reading)", CAUTION))
    if not local:
        for key in server:
            if key not in REMOTE_SERVER_KEYS:
                out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, f"{label} has the field "
                                   f"'{key}', which is not on the portal's v1.6.3 list for a "
                                   "remote server's entry (type, url, headers, timeout, "
                                   "alwaysLoad, oauth, and name, title, displayName, "
                                   "description as text)", PORTAL))
        for key in sorted(REMOTE_SERVER_TEXT_KEYS & set(server)):
            if not isinstance(server[key], str):
                out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, f"{label}: '{key}' "
                                   "must be text", PORTAL))
        if "oauth" in server:
            oauth = server["oauth"]
            if str(server.get("type")).lower() not in OAUTH_SERVER_TYPES:
                out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, f"{label} has oauth "
                                   "on a server that is not http or sse", PORTAL))
            if not isinstance(oauth, dict):
                out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, f"{label}: oauth is "
                                   "not an object", PORTAL))
            else:
                for key in oauth:
                    if key not in OAUTH_KEYS:
                        out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, f"{label}: "
                                           f"oauth has the field '{key}', which is not on the "
                                           "portal's list (clientId, callbackPort, "
                                           "authServerMetadataUrl, scopes)", PORTAL))
    if "command" not in server and str(server.get("type")).lower() != "stdio":
        url = server.get("url")
        if server.get("type") not in ("http", "sse", "ws") or not isinstance(url, str):
            out.append(Finding("LOCAL_CODE_MCP_SERVER", ERROR, rel, f"{label} needs a type "
                               "of http, sse or ws and a url", CHECKLIST))
        else:
            for qkey, _ in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query):
                if _credential_like(qkey):
                    out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel, f"{label} "
                                       f"puts {qkey} in the URL query: a credential belongs in "
                                       "a sensitive userConfig option and a header", CHECKLIST))
            authority = re.split(r"[/?#]", url.split("://", 1)[-1], maxsplit=1)[0]
            if "${" in authority or url.lstrip().startswith("${"):
                out.append(Finding("LOCAL_CODE_MCP_SERVER", WARNING, rel, f"{label} takes "
                                   "its URL from an option, so it cannot be checked as a public "
                                   "URL; ask Anthropic before relying on it", CAUTION))
            else:  # a placeholder in the path or query leaves the host visible: judge it
                problem = _public_url_problem(ENV_REF.sub("x", url))
                if problem:
                    out.append(Finding("LOCAL_CODE_MCP_SERVER", ERROR, rel, f"{label}: "
                                       f"{problem}", PORTAL))
    for section in ("env", "headers"):
        values = server.get(section)
        for key, value in (values.items() if isinstance(values, dict) else []):
            text = str(value)
            foreign = [ref for ref in ENV_REF.findall(text)
                       if not ref.startswith("user_config.") and ref not in OWN_VARIABLES]
            if foreign:
                out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel,
                                   f"{label} passes ${{{foreign[0]}}} from the user's "
                                   "environment in its " + section, CHECKLIST))
            literal = ENV_REF.sub("", text).strip()
            looks_secret = any(p.search(text) for _, p in SECRET_PATTERNS) or bool(
                re.fullmatch(r"(?:Bearer|Basic|Token)\s+\S{8,}", literal)
                or (re.fullmatch(r"[A-Za-z0-9_-]{24,}", literal) and re.search(r"\d", literal)
                    and re.search(r"[A-Za-z]", literal)))
            if not (_credential_like(str(key)) or looks_secret):
                continue
            # The value is made of references and at most an authentication scheme in front
            # ("Bearer ${user_config.api_key}"), and every option it names is sensitive.
            refs = USER_CONFIG_ANY.findall(text)
            from_sensitive = bool(refs) and AUTH_SCHEME.fullmatch(literal) is not None and all(
                isinstance(options.get(name), dict) and options[name].get("sensitive") is True
                for name in refs)
            if not from_sensitive:
                out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel,
                                   f"{label} passes {key} that does not come from a sensitive "
                                   "userConfig option", CHECKLIST))
            elif section == "env" and local:
                out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel,
                                   f"{label} puts {key} in the environment of a program on the "
                                   "user's computer: the portal's v1.6.3 advice accepts a "
                                   "${user_config.KEY} value there only from Verified "
                                   "organizations, and a remote server's headers otherwise",
                                   PORTAL))
    return out


# What a guard against a deep nesting leaves behind: a finding about the manifest, never silence
# (a file that defeats a check is a finding about that file).
TOO_DEEP_PATH = "<nested too deeply>"
_TOO_DEEP_SERVER = object()


def _server_entries(data: object, depth: int = 0) -> Iterable[tuple[str, object]]:
    """Every (name, server) of an MCP map: the map, a mcpServers wrapper, or a list of either."""
    if depth > 5:
        yield TOO_DEEP_PATH, _TOO_DEEP_SERVER
        return
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, str):
                yield from _server_entries(item, depth + 1)
    elif isinstance(data, dict):
        for name, value in data.items():
            if name == "mcpServers":
                yield from _server_entries(value, depth + 1)
            elif not (name == "$schema" and isinstance(value, str)):
                yield name, value


def _path_problem(rel: str, files: list[str]) -> str | None:
    """Why a path of the manifest does not name something inside the folder, or None."""
    if not rel.startswith(("./", "../")) and rel not in (".", ""):
        return "a path must start with ./"
    norm = posixpath.normpath(rel)
    if norm == ".." or norm.startswith("../") or posixpath.isabs(norm) or ".." in rel.split("/"):
        return "a path that climbs out of the plugin folder"
    if norm != "." and not any(f == norm or f.startswith(norm + "/") for f in files):
        return "a path to nothing in the folder"
    return None


def _too_deep(where: str, out: list[Finding], seen: set[object]) -> None:
    """The finding for an mcpServers nested too deeply: one for a file, however wide the nesting."""
    if ("deep", where) not in seen:
        seen.add(("deep", where))
        out.append(Finding("MANIFEST", ERROR, where, "mcpServers is nested more than 5 levels "
                           "deep: nothing below that was inspected", CHECKLIST))


def _collect_mcp(base: Path, value: object, where: str, out: list[Finding], options: dict[str, object],
                 files: list[str], depth: int = 0, seen: set[object] | None = None) -> None:
    """Judge every MCP server a manifest value declares, however it is spelled. A file that a path
    names is judged once, and a nesting that is too deep is one finding for the file."""
    seen = set() if seen is None else seen
    if depth > 5:
        _too_deep(where, out, seen)
        return
    if isinstance(value, list):
        for item in value:
            _collect_mcp(base, item, where, out, options, files, depth + 1, seen)
    elif isinstance(value, str):
        if value.lower().endswith((".mcpb", ".dxt")):
            out.append(Finding("LOCAL_CODE_MCP_SERVER", ERROR, where, "an MCP server declared "
                               "as a bundle", PORTAL))
        elif re.match(r"^[a-z]+://", value, re.IGNORECASE):
            out.append(Finding("LOCAL_CODE_MCP_SERVER", ERROR, where, "an MCP server config "
                               "fetched from a URL", CHECKLIST))
        else:
            problem = _path_problem(value, files)
            if problem:
                out.append(Finding("MANIFEST", ERROR, where, f"mcpServers: {problem} ({value})",
                                   CHECKLIST))
            else:
                rel = posixpath.normpath(value)
                if rel not in seen:
                    seen.add(rel)
                    _collect_mcp(base, _load_json(base, rel, out), rel, out, options, files,
                                 depth + 1, seen)
    elif isinstance(value, dict):
        for sname, server in _server_entries(value):
            if server is _TOO_DEEP_SERVER:
                _too_deep(where, out, seen)
            else:
                out.extend(_check_server(where, sname, server, options))


def _manifest_paths(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    """(key, path) of every component path the manifest names."""
    found: list[tuple[str, str]] = []

    too_deep: set[str] = set()

    def walk(key: str, value: object, depth: int = 0) -> None:
        if depth > 8:
            # A path list is never nested this deep: stop before the interpreter does, and say so
            # (once for a key, however wide the nesting is).
            if key not in too_deep:
                too_deep.add(key)
                found.append((key, TOO_DEEP_PATH))
            return
        if isinstance(value, str):
            found.append((key, value))
        elif isinstance(value, list):
            for item in value:
                walk(key, item, depth + 1)
        elif isinstance(value, dict) and key == "commands":
            for entry in value.values():
                if isinstance(entry, dict) and isinstance(entry.get("source"), str):
                    found.append((key, entry["source"]))

    for key in ("skills", "commands", "agents", "outputStyles", "workflows", "lspServers",
                "hooks", "types"):
        walk(key, manifest.get(key))
    experimental = manifest.get("experimental")
    if isinstance(experimental, dict):
        for key in ("themes", "monitors"):
            walk("experimental." + key, experimental.get(key))
    return found


def _manifest_components(manifest: dict[str, Any], files: list[str]) -> set[str]:
    """The Markdown files that the manifest makes components, wherever they are."""
    extra: set[str] = set()
    for key, path in _manifest_paths(manifest):
        if key not in ("skills", "commands", "agents"):
            continue
        norm = posixpath.normpath(path)
        for name in files:
            inside = name == norm or name.startswith(norm.rstrip("/") + "/") or norm == "."
            if inside and name.lower().endswith((".md", ".markdown")):
                extra.add(name)
    return extra


def _one_script(text: str) -> bool:
    """True when every letter of ``text`` is from one writing system."""
    scripts = {unicodedata.name(c, "X").split(" ")[0] for c in text
               if unicodedata.category(c).startswith("L")}
    return len(scripts) <= 1


ICON_MAX_BYTES = 2 * 1024 * 1024  # the validator reports ICON_INVALID above this (read on 2.1.325)


def _size_of(path: Path) -> int:
    """The size of a file in bytes, 0 when it cannot be read (check_file says why)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def check_manifest(base: Path, files: list[str]) -> list[Finding]:
    out: list[Finding] = []
    rel = ".claude-plugin/plugin.json"
    if rel not in files:
        return [Finding("MANIFEST", ERROR, rel, "the folder has no .claude-plugin/plugin.json: "
                        "the plugin path of a submission is the folder that holds it", CHECKLIST)]
    before = len(out)
    manifest = _load_json(base, rel, out)
    if not isinstance(manifest, dict):
        if len(out) == before:  # valid JSON that is not an object: null, a list, a number
            out.append(Finding("MANIFEST", ERROR, rel, "must be a JSON object", CHECKLIST))
        return out
    name = manifest.get("name")
    if not isinstance(name, str) or not KEBAB.match(name):
        out.append(Finding("MANIFEST", ERROR, rel, "'name' must be kebab-case", CHECKLIST))
    else:
        if name in RESERVED_NAMES or "official" in name.split("-"):
            out.append(Finding("MANIFEST", ERROR, rel, "a reserved word as the whole name, or a "
                               "name that presents the plugin as official", CHECKLIST))
        elif re.search(r"anthropic|claude", name):
            out.append(Finding("MANIFEST", WARNING, rel, "a name that reads as Anthropic's may "
                               "be reserved", CAUTION))
        if len(name) > 64:
            out.append(Finding("MANIFEST", WARNING, rel, "a name of more than 64 characters",
                               CHECKLIST))
    for field, value in (("displayName", manifest.get("displayName")),
                         ("author.name", (manifest.get("author") or {}).get("name")
                          if isinstance(manifest.get("author"), dict) else None)):
        if isinstance(value, str) and (
                not _one_script(value) or any(unicodedata.category(c) in ("Cf", "Cc", "Zs", "Zl", "Zp")
                                              and c != " " for c in value)):
            out.append(Finding("MANIFEST", ERROR, rel, f"{field} mixes writing systems or holds "
                               "an invisible character (look-alike letters)", CHECKLIST))
        if isinstance(value, str) and re.search(r"anthropic|claude", value, re.IGNORECASE):
            out.append(Finding("MANIFEST", WARNING, rel, f"{field} reads as a known brand; the "
                               "directory holds such a name for a reviewer", CHECKLIST))
    if not isinstance(manifest.get("version"), str) or not SEMVER.match(manifest["version"]):
        out.append(Finding("MANIFEST", WARNING, rel, "'version' is missing or not semver",
                           CHECKLIST))
    for key in ("description", "author"):
        if not manifest.get(key):
            out.append(Finding("MANIFEST", WARNING, rel, f"no '{key}'", CHECKLIST))
    for key in sorted(manifest):
        if key == "mcpServers":
            continue  # judged server by server below
        if key in LOCAL_CODE_KEYS:
            code, source = LOCAL_CODE_KEYS[key]
            out.append(Finding(code, ERROR, rel, f"'{key}' declares code that runs on the "
                               "user's computer", source))
        elif key in LISTING_FIELDS:
            out.append(Finding("UNKNOWN_KEY_CROSS_TOOL" if key == "icon" else "UNKNOWN_KEY", INFO,
                               rel, f"'{key}' is a directory listing field; Claude Code ignores "
                               "it and the directory reads it: no action needed (the portal's "
                               "words). Whether the portal's blocking rule on config fields "
                               "leaves the five listing fields out is unconfirmed", PORTAL))
        elif key not in KNOWN_KEYS:
            out.append(Finding("UNKNOWN_KEY", WARNING, rel, f"'{key}' is not a key of the "
                               "official manifest reference", REFERENCE))
            out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, f"'{key}' is a field that "
                               "Claude Code does not read: the portal's v1.6.3 rule refuses each "
                               "one from an organization that is not Verified (it names no file; "
                               "the five listing fields are left out in our reading, which "
                               "Anthropic has not confirmed)", PORTAL))
    settings = manifest.get("settings")
    if isinstance(settings, dict) and set(settings) - {"agent"}:
        out.append(Finding("LOCAL_CODE_OTHER", ERROR, rel, "'settings' holds more than 'agent': "
                           "subagentStatusLine, statusLine and hooks run a command", CAUTION))
    experimental = manifest.get("experimental")
    if isinstance(experimental, dict):
        for key in ("hooks", "mcpServers", "skills", "commands", "agents", "lspServers",
                    "outputStyles", "workflows"):
            if key in experimental:
                out.append(Finding("MANIFEST", ERROR, rel, f"'{key}' inside 'experimental': the "
                                   "checklist asks to keep component keys out of it", CHECKLIST))
    if isinstance(experimental, dict) and "monitors" in experimental:
        out.append(Finding("LOCAL_CODE_OTHER", ERROR, rel, "'experimental.monitors' declares shell "
                           "commands that Claude Code runs in the background", CAUTION))
    for key, path in _manifest_paths(manifest):
        if path == TOO_DEEP_PATH:
            out.append(Finding("MANIFEST", ERROR, rel, f"'{key}' is a list nested more than 8 "
                               "levels deep: the paths below that were not inspected", CHECKLIST))
            continue
        problem = _path_problem(path, files) if key != "types" else None
        if problem:
            out.append(Finding("MANIFEST", ERROR, rel, f"'{key}': {problem} ({path})", CHECKLIST))
    commands = manifest.get("commands")
    for cname, entry in (commands.items() if isinstance(commands, dict) else []):
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if isinstance(content, str):
            virtual = f"{rel}#commands.{cname}"
            out.extend(check_inline_shell(virtual, content, extra=(virtual,)))
            out.extend(check_text(virtual + ".md", content))
        tools = entry.get("allowedTools")
        if isinstance(tools, list) and SHELL_TOOL.search(" ".join(map(str, tools))):
            out.append(Finding("LOCAL_EXEC_PREAPPROVED", ERROR, rel, f"command '{cname}' "
                               "pre-approves a shell", CAUTION))
    if "dependencies" in manifest:
        out.append(Finding("MANIFEST", WARNING, rel, "depends on other plugins, which this "
                           "folder does not control", CAUTION))
    options = manifest.get("userConfig")
    options = options if isinstance(options, dict) else {}
    for key, option in options.items():
        described = " ".join(str(option.get(f, "")) for f in ("title", "description")) \
            if isinstance(option, dict) else ""
        if (_credential_like(key) or re.search(
                r"password|passphrase|secret|token|api key|credential", described, re.IGNORECASE)) \
                and not (isinstance(option, dict) and option.get("sensitive") is True):
            out.append(Finding("MCP_FORWARDS_CREDENTIAL_ENV", WARNING, rel, f"the option "
                               f"'{key}' looks like a credential and is not sensitive",
                               CHECKLIST))
    if options and not manifest.get("mcpServers"):
        out.append(Finding("MANIFEST", WARNING, rel, "userConfig options that no component "
                           "uses", CAUTION))
    _collect_mcp(base, manifest.get("mcpServers"), rel, out, options, files)
    if ".mcp.json" in files:
        before = len(out)
        mcp = _load_json(base, ".mcp.json", out)
        if not isinstance(mcp, dict) and len(out) == before:
            out.append(Finding("MANIFEST", ERROR, ".mcp.json", "must be a JSON object",
                               CHECKLIST))
        _collect_mcp(base, mcp, ".mcp.json", out, options, files)
    homepage = manifest.get("homepage")
    if isinstance(homepage, str) and not re.match(r"^https?://[^\s/]+", homepage):
        out.append(Finding("MANIFEST", ERROR, rel, "homepage is not a URL: Claude Code refuses "
                           "to load the plugin", CHECKLIST))
    icon = manifest.get("icon")
    if isinstance(icon, str) and icon.startswith("https://"):
        pass  # the validator passes an https URL (read on 2.1.325): no file to look for
    elif isinstance(icon, str):
        # posixpath on every platform: os.path.normpath makes a backslash path on Windows
        icon_rel = posixpath.normpath(icon.replace("\\", "/"))
        if icon_rel not in files:
            out.append(Finding("MANIFEST", ERROR, rel, f"the icon {icon} is not in the folder "
                               "(the validator reports ICON_INVALID and only warns: this tool "
                               "counts it as an error because the listing would have no icon)",
                               CAUTION))
        elif not icon_rel.lower().endswith((".png", ".jpg", ".jpeg")):
            out.append(Finding("MANIFEST", WARNING, rel, "an icon that is not a PNG or JPEG. The "
                               "validator advises a square PNG or JPEG of 512 to 2048 pixels, "
                               "under 2 MB, and says that SVG and WebP are not accepted (its own "
                               "check passes a clean SVG)", VALIDATOR))
        elif _size_of(base / icon_rel) > ICON_MAX_BYTES:
            out.append(Finding("MANIFEST", WARNING, rel, "an icon of more than 2 MiB: the "
                               "validator advises a square PNG or JPEG of 512 to 2048 pixels under "
                               "2 MB and reports ICON_INVALID above 2,097,152 bytes (it only "
                               "warns)", VALIDATOR))
    else:
        out.append(Finding("MANIFEST", WARNING, rel, "no icon (the validator reports "
                           "ICON_MISSING). The first icon saved or submitted in the portal may "
                           "become the listing icon for good", VALIDATOR))
    for key in ("documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"):
        value = manifest.get(key)
        if not value:
            if key != "termsOfServiceUrl":
                out.append(Finding("MANIFEST", WARNING, rel, f"no {key}: the directory's "
                                   "policy expects privacy, support and documentation links",
                                   CHECKLIST))
        elif not str(value).startswith("https://") and not (
                key == "supportUrl" and str(value).startswith("mailto:")):
            out.append(Finding("MANIFEST", WARNING, rel, f"{key} is not an https URL; the "
                               "directory drops it from the listing", CHECKLIST))
    return out


def check_plugin_folders(files: list[str], manifest: dict[str, Any]) -> list[Finding]:
    """The portal's v1.6.3 clauses on where files may sit (LOCAL_CODE_FILE_TYPE).

    Each .claude-plugin folder but the plugin's own, each .claude/skills folder, each JSON or YAML
    file in egress/, each file in the plugin's own .claude-plugin that is not plugin.json, an
    image or marketplace.json, a .mcp.json, .lsp.json, hooks.json or monitors.json that Claude Code
    does not read, and each file in output-styles/ that plugin.json leaves out. A path is judged
    case-insensitively, like a file system that ignores case.
    """
    out: list[Finding] = []
    nested: set[str] = set()
    skills: set[str] = set()
    styles = {posixpath.normpath(path).rstrip("/").lower()
              for key, path in _manifest_paths(manifest) if key == "outputStyles"}
    # The paths that plugin.json gives to Claude Code for these four kinds of file: a file there
    # is read, wherever it is.
    listed: set[str] = set()
    monitors = manifest.get("experimental")
    for value in (manifest.get("mcpServers"), manifest.get("lspServers"), manifest.get("hooks"),
                  monitors.get("monitors") if isinstance(monitors, dict) else None):
        for item in (value if isinstance(value, list) else [value]):
            if isinstance(item, str):
                listed.add(posixpath.normpath(item).lower())
    for rel in files:
        parts = rel.split("/")
        low = [part.lower() for part in parts]
        name, suffix = low[-1], PurePosixPath(low[-1]).suffix
        for index, part in enumerate(low[:-1]):
            if part == ".claude-plugin" and index > 0:
                nested.add("/".join(parts[:index + 1]))
            if part == "skills" and index > 0 and low[index - 1] == ".claude":
                skills.add("/".join(parts[:index + 1]))
        if "egress" in low[:-1] and suffix in (".json", ".yml", ".yaml"):
            out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "a JSON or YAML file in "
                               "egress/: the portal's v1.6.3 text refuses each one", PORTAL))
        if low[0] == ".claude-plugin" and len(low) >= 2:
            allowed = len(low) == 2 and (name in ("plugin.json", "marketplace.json")
                                         or suffix in IMAGE_SUFFIXES or suffix == ".svg")
            if not allowed:
                out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "a file in .claude-plugin "
                                   "that is not plugin.json, an image or marketplace.json: the "
                                   "portal's v1.6.3 text refuses it", PORTAL))
        standard = {".mcp.json", ".lsp.json", "monitors/monitors.json", "hooks/hooks.json"}
        if name in (".mcp.json", ".lsp.json", "monitors.json", "hooks.json") \
                and "/".join(low) not in standard and posixpath.normpath(rel).lower() not in listed:
            # The portal's remedy has three options. A file that declares hooks, monitors or a
            # server is never renamed to get past a check: it is listed where Claude Code reads
            # it, or removed.
            advice = ("list it in plugin.json or remove it"
                      if name in (".mcp.json", ".lsp.json") else "remove it")
            out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, f"a {name} that Claude Code "
                               f"does not read at that place: {advice} (the portal's v1.6.3 text "
                               "also allows renaming it; a file that declares hooks, monitors or "
                               "a server is not renamed to hide it)", PORTAL))
        lowered = "/".join(low)
        if low[0] == "output-styles" and not any(
                path == "." or lowered == path or lowered.startswith(path + "/")
                for path in styles):
            out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, rel, "a file in output-styles/ "
                               "that plugin.json's outputStyles list leaves out: the portal's "
                               "v1.6.3 text asks to list it or remove it", PORTAL))
    for folder in sorted(nested):
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, folder, "a .claude-plugin folder that "
                           "is not the plugin's own: the portal's v1.6.3 text refuses each one. "
                           "A plugin in a subfolder is submitted with that folder as its plugin "
                           "path, and the folder that holds it is then the plugin's own",
                           PORTAL))
    for folder in sorted(skills):
        out.append(Finding("LOCAL_CODE_FILE_TYPE", ERROR, folder, "a .claude/skills folder: the "
                           "portal's v1.6.3 text refuses each one. Ship skills in skills/, or put "
                           "the plugin in a subfolder and submit that folder", PORTAL))
    return out


def check_package_json(base: Path, files: Iterable[str]) -> list[Finding]:
    """The portal's closed list for package.json (v1.6.3, LOCAL_CODE_UNKNOWN_KEY).

    Each package.json has to be a plain JSON object with fields from the list only, and
    ``engines`` with plain versions. The portal names no file for this finding; a package.json
    with scripts or dependencies is the one that fits its list in this repository.
    """
    out: list[Finding] = []
    for rel in files:
        if PurePosixPath(rel).name != "package.json":
            continue
        problems: list[Finding] = []
        data = _load_json(base, rel, problems)
        if problems or not isinstance(data, dict):
            out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, "a package.json that is not "
                               "a plain JSON object the directory can read", PORTAL))
            continue
        for key in sorted(data):
            if key not in PACKAGE_JSON_KEYS:
                out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, f"package.json has the "
                                   f"field '{key}', which is not on the portal's v1.6.3 list "
                                   "(name, displayName, version, description, keywords, homepage, "
                                   "bugs, license, author, contributors, maintainers, funding, "
                                   "repository, private, type, files, engines, $schema). The "
                                   "portal names no file for this finding: this is our reading "
                                   "of its list", PORTAL))
        engines = data.get("engines")
        if "engines" in data and not (isinstance(engines, dict) and all(
                isinstance(v, str) and PLAIN_VERSION.fullmatch(v) for v in engines.values())):
            out.append(Finding("LOCAL_CODE_UNKNOWN_KEY", ERROR, rel, "package.json 'engines' "
                               "holds more than plain versions", PORTAL))
    return out


def _assets_in(files: list[str]) -> dict[str, str]:
    """Lower-case file name -> path of every image (SVG apart) and font in the folder."""
    found: dict[str, str] = {}
    for rel in files:
        name = PurePosixPath(rel).name.lower()
        if name.endswith(ASSET_SUFFIXES):
            found.setdefault(name, rel)
    return found


def _in_name(char: str) -> bool:
    """True for a character that makes a name part of a longer one (favicon.png, icon.pngx): a
    letter, a digit, a combining mark, '_' or '-'."""
    return char in "_-" or unicodedata.category(char)[0] in "LNM"


AssetIndex = tuple[dict[str, tuple[int, ...]], dict[str, str]]


def _asset_index(assets: dict[str, str]) -> AssetIndex:
    """What the asset check looks up: by suffix, the distinct lengths of the names that end with
    it, and the names it can look for (one with a space, a quote or another character that ends a
    name in a text is reported once, in run(), and never looked for)."""
    checkable = {name: path for name, path in assets.items()
                 if not ASSET_NAME_STOP.search(name) and len(name) <= MAX_ASSET_NAME}
    sizes: dict[str, set[int]] = {}
    for name in checkable:
        suffix = next((s for s in ASSET_SUFFIXES if name.endswith(s)), None)
        if suffix:
            sizes.setdefault(suffix, set()).add(len(name))
    return {suffix: tuple(sorted(found)) for suffix, found in sizes.items()}, checkable


def _code_spans(line: str) -> tuple[list[int], list[int]]:
    """Where the inline code spans of one line of Markdown start and end, as two sorted lists.

    A span starts after its opening run of backticks and ends where its closing run starts: the
    next run of exactly as many backticks on the line (CommonMark reads a span over several lines
    too: not here). An opening run that no later run of its length matches is read as opening a
    span that lasts to the end of the line, where CommonMark reads it as plain text: a name after
    it is inside, and the check warns rather than stays silent. Linear in the line: one pass from
    the right finds, for each run, the next run of its length, and one pass from the left pairs
    them and goes on after the closing run, so that what a span holds is not read again.
    """
    runs = [run.span() for run in BACKTICK_RUN.finditer(line)]
    partner = [-1] * len(runs)
    nearest: dict[int, int] = {}  # a length -> the nearest run of that length to the right
    for index in range(len(runs) - 1, -1, -1):
        begin, end = runs[index]
        partner[index] = nearest.get(end - begin, -1)
        nearest[end - begin] = index
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    while index < len(runs):
        starts.append(runs[index][1])
        closing = partner[index]
        if closing < 0:
            ends.append(len(line))  # nothing of its length follows: the span lasts to the end
            break
        ends.append(runs[closing][0])
        index = closing + 1  # on after the closing run: what the span holds is not read again
    return starts, ends


def check_asset_references(rel: str, text: str, assets: dict[str, str],
                           skip: frozenset[str] = frozenset(),
                           index: AssetIndex | None = None) -> list[Finding]:
    """UNREAD_ASSET_REFERENCED: a text that names, by file name, an image or font of the folder.

    In Markdown only a name in an inline code span or in a fenced code block counts (the
    checklist's wording: a bundled image is shown with Markdown image syntax). Anywhere else any
    mention counts. A span is read on one line, as CommonMark reads it: a run of n backticks
    opens a span that the next run of exactly n backticks closes, and a name counts when its
    suffix starts between the two (so ``name.png`` and ```name.png``` count, ``a ` b`` name.png
    does not). A run that no later run of its length matches is read as opening a span to the end
    of the line: the check warns rather than stays silent, which over-warns on ``a `b` name.png
    (a name that CommonMark puts outside). Not read: a span that goes on in the next line, a
    backslash before a backtick, an indented code block, and a line that starts with three
    backticks or tildes and holds more text (a fence line, as the fence rule reads it). A name
    is a name when the character before it and the character after it are not a letter, a digit,
    '_' or '-' (or a combining mark): favicon.png and icon.pngx are other names than icon.png,
    while @icon.png, a.icon.png and a name that ends a sentence (icon.png.) are that name. The
    plugin's own ``icon`` is the
    documented way to name an image; the caller passes it in ``skip``, and it is reported as a
    note and not as a warning, because nothing in the portal's reviews shows that it is exempt
    (the only manifest that named an image and was listed was a nested one, which is not the
    plugin's own). Calibrated on one tree (v1.6.3: 4 files named the only PNG, 8 others named
    images that do not exist and were not listed), so it is a reading of that, not a rule.
    ``index`` is what _asset_index made of ``assets``, for a caller that checks many texts.
    """
    out: list[Finding] = []
    markdown = PurePosixPath(rel).suffix.lower() in (".md", ".markdown")
    if not assets:
        return out
    by_suffix, checkable = index if index is not None else _asset_index(assets)
    reported: set[str] = set()
    fenced = False
    for number, line in enumerate(text.split("\n"), start=1):
        if markdown and line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if markdown and not fenced and "`" not in line:
            continue  # no backtick, no code span: no name of this line counts
        low = line.lower()
        span_starts: list[int] | None = None  # where the code spans of this line start, found once
        span_ends: list[int] = []
        stops: list[int] | None = None  # where a character that ends a name sits, once per line
        for hit in ASSET_SUFFIX_IN_TEXT.finditer(low):
            sizes = by_suffix.get(hit.group(0))
            if not sizes:
                continue
            if markdown and not fenced:
                if span_starts is None:
                    span_starts, span_ends = _code_spans(low)
                # the last span that starts at or before the hit holds it if it ends after it
                last = bisect_right(span_starts, hit.start()) - 1
                if last < 0 or hit.start() >= span_ends[last]:
                    continue  # in Markdown only a name in a code span or a code block counts
            end = hit.end()
            if end < len(low) and _in_name(low[end]):
                continue
            if stops is None:
                stops = [stop.start() for stop in ASSET_NAME_STOP.finditer(low)]
            before = bisect_left(stops, hit.start())
            room = end - (stops[before - 1] + 1 if before else 0)  # no name is longer than this
            # a look-up per length that fits: one per distinct length, 255 at the very most, which
            # is the case of a line with no character that ends a name
            for size in sizes[:bisect_right(sizes, room)]:
                begin = end - size
                name = low[begin:end]
                path = checkable.get(name)
                if path is None or path == rel or name in reported:
                    continue
                if begin and _in_name(low[begin - 1]):
                    continue
                reported.add(name)
                if name in skip:
                    out.append(Finding(
                        "UNREAD_ASSET_REFERENCED", INFO, rel, f"names {name}, the "
                        "plugin's own icon: the documented way to name an image. Nothing "
                        "in the portal's reviews shows that the plugin's own icon is "
                        "exempt from this finding; if it is not, expect a hold for a "
                        "reviewer", PORTAL, number))
                else:
                    out.append(Finding(
                        "UNREAD_ASSET_REFERENCED", WARNING, rel, f"names {name}, an "
                        "image or font file of this folder: a command, script or "
                        "setting that names one is held for a reviewer (checklist: show "
                        "a bundled image with Markdown image syntax and do not name it "
                        "elsewhere)", PORTAL, number))
    return out


def check_layout(files: list[str], readme: str | None) -> list[Finding]:
    """The layout findings. ``readme`` is the text that check_file read (None when it refused
    the file: it has said why, and a second read here could block on a pipe)."""
    out: list[Finding] = []
    if len(files) > MAX_FILES:
        out.append(Finding("DIR_LIMITS", ERROR, ".", f"{len(files)} files: more than {MAX_FILES} "
                           "is held for a reviewer", CHECKLIST))
    if "README.md" not in files:
        out.append(Finding("MANIFEST", ERROR, "README.md", "no README.md", CHECKLIST))
    elif readme is not None:
        readme = re.sub(r"(?s)(```|~~~).*?(?:\1|\Z)", " ", readme)  # code blocks do not count
        readme = re.sub(r"(?s)<!--.*?-->", " ", readme)
        words = len([w for w in readme.split() if re.search(r"\w", w)])
        if words < 40:
            out.append(Finding("MANIFEST", ERROR, "README.md", f"{words} words outside code "
                               "blocks: the directory's own check asks for at least 40",
                               CHECKLIST))
    if "LICENSE" not in files:
        out.append(Finding("MANIFEST", WARNING, "LICENSE", "no LICENSE file", CHECKLIST))
    if ".claude-plugin/marketplace.json" in files:
        out.append(Finding("MANIFEST", WARNING, ".claude-plugin/marketplace.json",
                           "a marketplace manifest in the plugin folder: the directory treats "
                           "the folder as one plugin and checks only that plugin", CHECKLIST))
    return out


def _capped(findings: list[Finding]) -> list[Finding]:
    """At most MAX_PER_KIND findings of one code in one file, then one line that counts the rest
    (a crafted file must not turn the report into a million lines)."""
    kept: list[Finding] = []
    count: dict[tuple[str, str], int] = {}
    first_dropped: dict[tuple[str, str], Finding] = {}
    dropped: dict[tuple[str, str], int] = {}
    for finding in findings:
        key = (finding.code, finding.path)
        count[key] = count.get(key, 0) + 1
        if count[key] <= MAX_PER_KIND:
            kept.append(finding)
        else:
            first_dropped.setdefault(key, finding)
            dropped[key] = dropped.get(key, 0) + 1
    for key, number in dropped.items():
        shown = first_dropped[key]
        kept.append(Finding(shown.code, shown.severity, shown.path,
                            f"and {number} more findings of this kind in this file", shown.source))
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    kept.sort(key=lambda f: (order[f.severity], f.code, f.path, f.line))
    return kept


def run(base: Path, tracked: bool = False) -> Report:
    """Inspect ``base`` and return the report as a dict."""
    files = list_files(base, tracked)
    findings: list[Finding] = []
    extra: set[str] = set()
    readme: str | None = None
    manifest_data: dict[str, Any] = {}
    if ".claude-plugin/plugin.json" in files:
        # Read once more by check_manifest, which reports what is wrong with it; the findings
        # of this first read are dropped so that none is said twice.
        loaded = _load_json(base, ".claude-plugin/plugin.json", [])
        if isinstance(loaded, dict):
            manifest_data = loaded
            extra = _manifest_components(loaded, files)
    assets = _assets_in(files)
    asset_index = _asset_index(assets)
    for name, path in assets.items():
        if ASSET_NAME_STOP.search(name) or len(name) > MAX_ASSET_NAME:
            findings.append(Finding(
                "UNREAD_ASSET_REFERENCED", INFO, path, "its name holds a space, a quote or "
                "another character that ends a name in a text (or is longer than "
                f"{MAX_ASSET_NAME} characters): the check for texts that name an image does not "
                "look for this one", CAUTION))
    icon = manifest_data.get("icon")
    own_icon = frozenset({PurePosixPath(icon).name.lower()}) if isinstance(icon, str) \
        else frozenset()
    for rel in files:
        # One file that cannot be read, or that defeats a check, is a finding about that file:
        # it must not end the run and lose every other finding.
        try:
            found, text = check_file(base, rel)
            findings.extend(found)
            if rel == "README.md":
                readme = text
            if text is not None:
                findings.extend(check_text(rel, text))
                if assets:
                    findings.extend(check_asset_references(
                        rel, text, assets,
                        own_icon if rel == ".claude-plugin/plugin.json" else frozenset(),
                        asset_index))
                if PurePosixPath(rel).suffix.lower() in (".md", ".markdown"):
                    findings.extend(check_frontmatter(rel, text, extra))
                    findings.extend(check_inline_shell(rel, text, extra))
        except (OSError, RecursionError, MemoryError) as exc:
            findings.append(Finding("INVENTORY_GAPS", ERROR, rel, "cannot be checked "
                                    f"({getattr(exc, 'strerror', None) or type(exc).__name__})",
                                    PORTAL))
    findings.extend(check_names(files))
    findings.extend(check_local_code_paths(files))
    findings.extend(check_plugin_folders(files, manifest_data))
    findings.extend(check_package_json(base, files))
    for rel in files:
        if rel.lower().startswith("bin/") and rel.lower().endswith(ASSET_SUFFIXES):
            findings.append(Finding("UNREAD_ASSET_REFERENCED", WARNING, rel, "an image or font "
                                    "file in bin/: the portal holds it for a reviewer", PORTAL))
    findings.extend(check_hooks(base, files))
    findings.extend(check_manifest(base, files))
    findings.extend(check_layout(files, readme))
    hooked = next((f for f in findings if f.code == "LOCAL_CODE_HOOK_COMMAND"), None)
    if hooked:
        findings.append(Finding("USES_HOOKS", INFO, hooked.path, "the folder ships hooks, which "
                                "Claude Code runs on events such as tool calls (a note in the "
                                "portal)", PORTAL))
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    findings.sort(key=lambda f: (order[f.severity], f.code, f.path, f.line))
    findings = _capped(findings)
    counts = {severity: sum(1 for f in findings if f.severity == severity)
              for severity in (ERROR, WARNING, INFO)}
    return {"disclaimer": DISCLAIMER, "equivalent_to_anthropic_scanner": False,
            "path": str(base), "files": len(files), "summary": counts,
            "sources": SOURCES, "findings": [f.as_dict() for f in findings]}


def render(report: Report) -> str:
    summary = report["summary"]
    lines = [DISCLAIMER, f"Folder: {report['path']} ({report['files']} files)", ""]
    for item in report["findings"]:
        lines.append(Finding(**item).format())
    lines.append("")
    lines.append(f"{summary[ERROR]} errors, {summary[WARNING]} warnings, "
                 f"{summary[INFO]} notes.")
    return "\n".join(lines)


def _tolerate_any_console() -> None:
    """Let the report be written to any console or pipe.

    A report names paths, and a path can hold a character that the code page of the console or
    the pipe (a Windows default) cannot encode: it is written out as an escape, and the exit
    status stays the checker's (1 for findings, never a traceback that reads the same).
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH),
                        help="the plugin folder (default: distribution/directory)")
    parser.add_argument("--tracked", action="store_true",
                        help="inspect the files git tracks in PATH instead of walking it; they "
                             "are read from the work tree, not from the commit")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--fail-on", choices=(ERROR, WARNING), default=ERROR,
                        help="the lowest severity that makes the exit status 1")
    args = parser.parse_args(argv)
    _tolerate_any_console()
    base = Path(args.path)
    if not base.is_dir():
        print(f"directory_preflight: {base} is not a folder", file=sys.stderr)
        return 2
    try:
        report = run(base, args.tracked)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"directory_preflight: cannot read {base}: {_printable(str(exc))}", file=sys.stderr)
        return 2
    except Exception as exc:  # a gate that crashes must not read as "errors were found"
        print(f"directory_preflight: internal error ({type(exc).__name__}); this is a bug of "
              "the checker and says nothing about the folder", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if args.json else render(report))
    summary = report["summary"]
    failed = summary[ERROR] or (args.fail_on == WARNING and summary[WARNING])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
