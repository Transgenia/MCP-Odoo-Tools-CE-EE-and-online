# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Which copy of odoo-tools is installed, and whether its options are complete.

Two offline checks for Claude Code, run as ``run_stdio.py --check-copies`` and
``run_stdio.py --check-options``. Each reads, on stdin, the JSON that a Claude Code
command prints, so this module runs no program, opens no file of Claude Code's and
never contacts Odoo:

* ``claude plugin list --json | ... --check-copies`` lists the odoo-tools copies
  Claude Code knows in the current folder. It finds two copies active at once (for
  example one from the Claude plugin directory in a project folder and one from
  Transgenia's marketplace for the user) and copies older than 1.5.0, which have no
  permission policy. It prints the exact commands that leave one current copy.
* ``claude plugin configure <id> --json | ... --check-options`` checks the saved
  options of one copy: the required connection options, a credential, the URL
  (scheme and host only), and the permission options a copy older than 1.5.0 does
  not have. Claude Code never prints a ``sensitive`` value there; this module does
  not print one either, whatever the input holds.

Exit codes: 0 nothing to fix, 1 something to fix, 2 the input is not that JSON.

``plugin_identity`` also lives here: the server reports it in ``odoo_version`` so
that a user with several copies can tell which one answered.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, TextIO

from . import __version__

PLUGIN_NAME = "odoo-tools"
# The permission policy arrived in 1.5.0; an older copy runs every tool the Odoo
# user may run, with no profile, no policy file and no audit log.
POLICY_SINCE = (1, 5, 0)
MARKETPLACE = "transgenia-odoo-tools"
MARKETPLACE_SOURCE = "Transgenia/MCP-Odoo-Tools-CE-EE-and-online"
OUR_ID = f"{PLUGIN_NAME}@{MARKETPLACE}"
REQUIRED_OPTIONS = ("odoo_url", "odoo_db", "odoo_login")
CREDENTIAL_OPTIONS = ("odoo_api_key", "odoo_password")
# Under this many seconds, a report or an export of a few thousand records times out.
SHORT_TIMEOUT = 30
_SHADOWED = "synced-plugin-shadowed"
_VERSION = re.compile(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?")
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Of one plugin id's installations, the one for this folder applies before the user's.
_SCOPE_RANK = {"local": 3, "project": 2, "user": 1}
# A cd line: a path of these characters needs no quotes in bash or PowerShell.
_SAFE_CD = re.compile(r"[A-Za-z0-9._/:~-]+")
# Read by a shell even inside double quotes (bash: $ ` " and ! history expansion;
# PowerShell: $ ` "): no one quoting serves both shells.
_CD_BY_HAND = frozenset('"$`!')
_DRIVE = re.compile(r"^[A-Za-z]:\\")


class InputError(Exception):
    """The JSON on stdin is not what the check reads."""


def parse_version(text: Any) -> tuple[int, int, int] | None:
    """The leading ``X.Y.Z`` of a version such as ``1.4.0-26de374ed2c6``; ``None``
    when there is none (``unknown``, empty)."""
    if not isinstance(text, str):
        return None
    match = _VERSION.match(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def plugin_identity(diag_dir: str, audit_dir: str) -> dict[str, Any]:
    """This server's version and, in Claude Code, the copy it belongs to.

    Claude Code gives every installed copy its own data folder,
    ``~/.claude/plugins/data/<name>-<marketplace>``, and the plugin passes its
    ``diagnostics`` and ``audit`` subfolders to the server. The copy is read from
    that folder's name: ``odoo-tools-transgenia-odoo-tools`` is
    ``odoo-tools@transgenia-odoo-tools``. Outside Claude Code (a container, the
    desktop extension, a standalone run) there is no such folder and no copy."""
    identity: dict[str, Any] = {"name": PLUGIN_NAME, "version": __version__}
    for path, leaf in ((diag_dir, "diagnostics"), (audit_dir, "audit")):
        copy = _copy_from_data_path(path, leaf)
        if copy:
            identity["copy"] = copy
            break
    return identity


def _copy_from_data_path(path: str, leaf: str) -> str | None:
    if not path or path.strip().lower() == "off":
        return None
    parts = [p for p in re.split(r"[\\/]+", path.strip()) if p]
    # .../plugins/data/<folder>/<leaf>
    if len(parts) < 4 or parts[-1] != leaf or parts[-3] != "data" or parts[-4] != "plugins":
        return None
    folder = parts[-2]
    prefix = PLUGIN_NAME + "-"
    if not folder.startswith(prefix) or len(folder) == len(prefix):
        return None
    return f"{PLUGIN_NAME}@{folder[len(prefix):]}"


@dataclass
class Report:
    """What a check found: lines to show, problems to fix and the commands that fix them."""

    title: str
    lines: list[str] = field(default_factory=list)
    problems: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Two surfaces, never mixed: terminal commands (PowerShell, Terminal, bash)
    # and slash commands typed inside Claude Code.
    terminal: list[str] = field(default_factory=list)
    session: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def problem(self, code: str, text: str) -> None:
        self.problems.append({"code": code, "text": text})

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, **self.data, "problems": self.problems,
                "warnings": self.warnings, "terminal": self.terminal,
                "session": self.session}

    def render(self) -> str:
        out = [self.title, *("  " + line for line in self.lines)]
        if self.problems:
            out.append("To fix:")
            out.extend(f"  - {p['text']}" for p in self.problems)
        for warning in self.warnings:
            out.append(f"Note: {warning}")
        if self.terminal:
            out.append("In a terminal (PowerShell, Terminal or bash), not inside Claude Code:")
            out.extend("  " + command for command in self.terminal)
        if self.session:
            out.append("Inside Claude Code:")
            out.extend("  " + command for command in self.session)
        if self.terminal or self.session:
            out.append("Then restart Claude Code, or run /reload-plugins inside it.")
        out.append("Result: ok" if self.ok else f"Result: {len(self.problems)} to fix")
        return "\n".join(out) + "\n"


def _home_relative(path: str) -> str:
    """``path`` with the home folder written as ``~`` (no account name in a report)."""
    try:
        home = os.path.expanduser("~")
    except (KeyError, RuntimeError):
        return path
    if home and home != "~" and os.path.isabs(home):
        home = home.rstrip("/\\") or home
        if path == home:
            return "~"
        for sep in {os.sep, "/", "\\"}:
            if path.startswith(home + sep):
                return "~" + path[len(home):].replace("\\", "/")
    return path


def _cd(path: str) -> str:
    """A ``cd`` line that works in bash and PowerShell, for a home-relative path too
    (bash does not expand a quoted ``~``). A Windows path is written with ``/``, which
    both shells take. A path that no quoting serves in both shells becomes a comment
    line, and the user changes to that folder by hand."""
    shown = _home_relative(path)
    if _DRIVE.match(shown):
        shown = shown.replace("\\", "/")
    if _SAFE_CD.fullmatch(shown):
        return f"cd {shown}"
    if not shown.isprintable() or any(char in _CD_BY_HAND for char in shown):
        printable = "".join(char if char.isprintable() else "?" for char in shown)
        return f"# first change to this folder by hand: {printable}"
    if shown.startswith("~/"):
        return f'cd ~/"{shown[2:]}"'
    return f'cd "{shown}"'


def _copy_state(entry: dict[str, Any]) -> str:
    details = entry.get("noteDetails")
    if isinstance(details, list) and any(isinstance(d, dict) and d.get("type") == _SHADOWED
                                         for d in details):
        return "shadowed"
    if entry.get("scope") in ("project", "local"):
        # Claude Code reports `enabled` and `projectEnabled` per plugin id and folder,
        # not per installation: a project installation made in another folder shows
        # `enabled` true when the same id is active here through another scope, with
        # `projectEnabled` false. It is active here only when this folder enables it.
        if "projectEnabled" not in entry:  # an older Claude Code: `enabled` alone
            return "active" if entry.get("enabled") is True else "other folder"
        if entry.get("projectEnabled") is not True:
            return "other folder"
    return "active" if entry.get("enabled") is True else "disabled"


def _describe(entry: dict[str, Any]) -> str:
    where = entry.get("scope") or "?"
    if entry.get("scope") in ("project", "local") and isinstance(entry.get("projectPath"), str):
        where += ", " + _home_relative(entry["projectPath"])
    if entry.get("scope") == "synced":
        where = "synced from claude.ai"
    version = entry.get("version") or "unknown"
    return f"{entry['id']} {version} ({where})"


def _keep_rank(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Which active copy to keep: one with the permission policy, then Transgenia's
    marketplace, then the newest, then the user scope."""
    version = parse_version(entry.get("version")) or (0, 0, 0)
    marketplace = entry["id"].partition("@")[2]
    return (version >= POLICY_SINCE, marketplace == MARKETPLACE, version,
            entry.get("scope") == "user")


def _uninstall(entry: dict[str, Any]) -> list[str]:
    scope = entry.get("scope")
    if scope in ("project", "local") and isinstance(entry.get("projectPath"), str):
        return [_cd(entry["projectPath"]),
                f"claude plugin uninstall {entry['id']} --scope {scope}"]
    if scope == "user":
        return [f"claude plugin uninstall {entry['id']} --scope user"]
    return []


def _install_commands(known: bool) -> list[str]:
    """Commands that install a current copy from Transgenia's marketplace. When that
    marketplace is already known here, its local copy may be outdated, and
    ``install --marketplace`` reuses it as it is: update it first."""
    commands = [f"claude plugin marketplace update {MARKETPLACE}"] if known else []
    commands.append(f"claude plugin install {PLUGIN_NAME} --marketplace "
                    f"{MARKETPLACE_SOURCE} --scope user")
    return commands


def _update_commands(keep: dict[str, Any], known: bool) -> list[str]:
    """Commands that leave a current copy in place of ``keep``, older than 1.5.0."""
    if keep["id"] != OUR_ID:
        # Another marketplace's copy, such as the Claude plugin directory's: a current
        # copy from Transgenia's marketplace replaces a local one and takes precedence
        # over a synced one.
        return _uninstall(keep) + _install_commands(known)
    scope = keep.get("scope") if keep.get("scope") in ("user", "project", "local") else "user"
    commands = []
    if scope in ("project", "local") and isinstance(keep.get("projectPath"), str):
        commands.append(_cd(keep["projectPath"]))
    # Uninstalling and installing again would reuse the outdated local copy of the
    # marketplace and put the same version back: update the marketplace, then the plugin.
    return commands + [f"claude plugin marketplace update {MARKETPLACE}",
                       f"claude plugin update {OUR_ID} --scope {scope}"]


def check_copies(entries: Any) -> Report:
    """Check ``claude plugin list --json``: exactly one active odoo-tools copy, 1.5.0+."""
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise InputError("expected the JSON list that `claude plugin list --json` prints")
    copies = [e for e in entries
              if isinstance(e.get("id"), str) and e["id"].partition("@")[0] == PLUGIN_NAME]
    report = Report("odoo-tools copies Claude Code knows in this folder:")
    states = [_copy_state(e) for e in copies]  # per installation, not per id
    for entry, state in zip(copies, states):
        label = {"shadowed": "not loaded", "other folder": "other folder"}.get(state, state)
        line = f"{label:<12} {_describe(entry)}"
        if state == "shadowed":
            line += ": a copy on this computer has the same name and takes precedence"
        elif state == "other folder":
            line += ": installed for that folder only"
        report.lines.append(line)
    # One plugin id is one copy: one code, one set of options, one data folder. Of its
    # installations, the one for this folder applies, then the user's.
    installs: dict[str, list[dict[str, Any]]] = {}
    for entry, state in zip(copies, states):
        if state == "active":
            installs.setdefault(entry["id"], []).append(entry)
    active = [max(group, key=lambda e: _SCOPE_RANK.get(e.get("scope"), 0))
              for group in installs.values()]
    report.data = {"copies": [{"id": e["id"], "version": e.get("version"),
                               "scope": e.get("scope"), "state": state}
                              for e, state in zip(copies, states)]}
    known = any(e["id"] == OUR_ID for e in copies)
    if not copies:
        report.lines.append("(none)")
    if not active:
        report.problem("none", "odoo-tools is not active in this folder. Install it from "
                       "Transgenia's marketplace (user scope, every folder).")
        report.terminal.extend(_install_commands(known))
        return report
    keep = max(active, key=_keep_rank)
    report.data["keep"] = keep["id"]
    if len(active) > 1:
        report.problem("duplicates", f"{len(active)} copies are active at once, so Claude "
                       "Code may use the tools of one and the options of another. Keep one: "
                       f"{_describe(keep)}.")
    for entry in active:
        version = parse_version(entry.get("version"))
        if version is not None and version < POLICY_SINCE:
            report.problem("no-policy", f"{_describe(entry)} is older than 1.5.0: it has no "
                           "permission policy, profile or audit log.")
    for entry in active:
        if entry["id"] == keep["id"]:
            continue
        for install in installs[entry["id"]]:  # every installation active here
            commands = _uninstall(install)
            if commands:
                report.terminal.extend(commands)
            else:
                report.warnings.append(f"{install['id']} is managed on claude.ai: remove it "
                                       "there (Customize, Plugins).")
    keep_version = parse_version(keep.get("version"))
    if keep_version is None:
        report.warnings.append(f"the version of {keep['id']} is unknown; odoo_version names "
                               "the copy that answers.")
    elif keep_version < POLICY_SINCE:
        # Every active copy is old.
        report.terminal.extend(_update_commands(keep, known))
    return report


def _url_problems(url: str) -> tuple[list[str], list[str], str | None]:
    """(problems, warnings, the URL as shown) for the Odoo URL option.

    Only ``scheme://host[:port]`` is ever shown, or nothing when no host can be read:
    user info can hold a password and a path, query or fragment a token (a copied
    portal link), so none of them is repeated, in a problem either."""
    problems: list[str] = []
    warnings: list[str] = []
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return ["the Odoo URL cannot be read; use https://your-host"], [], None
    host = parts.hostname or ""
    shown = None
    if parts.scheme in ("http", "https") and host:
        shown = f"{parts.scheme}://{f'[{host}]' if ':' in host else host}"
        shown += f":{port}" if port is not None else ""
    if "@" in url:
        # User info, with or without "//" (admin:pw@host, https//admin:pw@host): an Odoo
        # address never holds an "@".
        problems.append("the Odoo URL holds a user name or password (an @); remove it from "
                        "the URL (the login and the key have their own options)")
    if shown is None:
        problems.append("the Odoo URL needs a scheme and a host, e.g. https://my-company.odoo.com")
    elif parts.path not in ("", "/") or parts.query or parts.fragment:
        problems.append(f"the Odoo URL must be the scheme and host only: use {shown}, "
                        "without its path, query or fragment")
    elif parts.path == "/":
        warnings.append("the trailing / of the Odoo URL is ignored")
    if parts.scheme == "http" and host and host.lower() not in _LOCAL_HOSTS:
        warnings.append("plain http sends the API key unencrypted; use https for any "
                        "Odoo that is not on this computer")
    return problems, warnings, shown


def check_options(doc: Any) -> Report:
    """Check ``claude plugin configure <id> --json`` for one odoo-tools copy."""
    if not isinstance(doc, dict) or not isinstance(doc.get("schema"), dict):
        raise InputError("expected the JSON object that `claude plugin configure <id> --json` "
                         "prints")
    plugin_id = doc.get("pluginId")
    if not isinstance(plugin_id, str) or plugin_id.partition("@")[0] != PLUGIN_NAME:
        raise InputError(f"expected the options of an {PLUGIN_NAME} copy, got {plugin_id!r}")
    schema: dict[str, Any] = doc["schema"]
    inputs = doc.get("inputs") if isinstance(doc.get("inputs"), dict) else {}
    configured_list = doc.get("configured") or []
    if not isinstance(configured_list, list) or not all(isinstance(key, str)
                                                        for key in configured_list):
        raise InputError("expected `configured` to be a list of option names")
    configured = set(configured_list)
    sensitive = {key for key, spec in schema.items()
                 if isinstance(spec, dict) and spec.get("sensitive")}

    def value(key: str) -> str:
        # Never a sensitive value, whatever the input holds.
        raw = inputs.get(key, "") if key not in sensitive else ""
        return raw if isinstance(raw, str) else str(raw)

    report = Report(f"Options of {plugin_id}:")
    report.data = {"plugin": plugin_id}
    if "odoo_policy" not in schema:
        report.problem("no-policy", f"{plugin_id} has no Permission profile option: it is "
                       "older than 1.5.0 and has no permission policy. Run --check-copies "
                       "and keep a current copy.")
    missing = [key for key in REQUIRED_OPTIONS if key not in configured or not value(key)]
    for key in missing:
        title = schema.get(key, {}).get("title", key) if isinstance(schema.get(key), dict) else key
        report.problem("missing", f"{title} ({key}) is not set")
    has_credential = any(key in configured for key in CREDENTIAL_OPTIONS)
    if not has_credential:
        report.problem("no-credential", "neither Odoo API key nor Odoo password is set "
                       "(Odoo 14+: an API key; Odoo 10-13: the password)")
    elif all(key in configured for key in CREDENTIAL_OPTIONS):
        report.warnings.append("both an API key and a password are set; the API key is used")
    url = value("odoo_url")
    if url:
        problems, warnings, shown = _url_problems(url)
        for text in problems:
            report.problem("url", text)
        report.warnings.extend(warnings)
        report.lines.append(f"Odoo URL: {shown}" if shown else
                            "Odoo URL: set, not shown (no scheme and host could be read)")
    if value("odoo_db"):
        report.lines.append(f"Database: {value('odoo_db')}")
    if value("odoo_login"):
        report.lines.append(f"Login: {value('odoo_login')}")
    report.lines.append("Credential: " + ("API key" if "odoo_api_key" in configured else
                                          "password" if "odoo_password" in configured else
                                          "none"))
    readonly = value("odoo_readonly").strip().lower() == "true"
    report.lines.append(f"Read-only mode: {'on' if readonly else 'off'}")
    report.data["readonly"] = readonly
    if "odoo_policy" in schema:
        profile = value("odoo_policy").strip() or "standard"
        report.lines.append(f"Permission profile: {profile}")
        report.data["profile"] = profile
        policy_file = value("odoo_policy_file").strip()
        report.lines.append("Permission policy file: "
                            + (_home_relative(policy_file) if policy_file else "none"))
    timeout = value("odoo_timeout").strip()
    if timeout:
        try:
            seconds = float(timeout)
        except ValueError:
            seconds = None
        if seconds is not None and seconds < SHORT_TIMEOUT:
            report.warnings.append(f"a request timeout of {timeout} s is short: reports and "
                                   "exports can take longer (default 120)")
    if missing or not has_credential or any(p["code"] == "url" for p in report.problems):
        # The key is typed into the options dialog, never into the chat.
        report.session.append(f"/plugin configure {plugin_id}")
    return report


def check_main(kind: str, stdin: TextIO, out: TextIO, as_json: bool = False) -> int:
    """``--check-copies`` / ``--check-options``: read the JSON on stdin, print the report."""
    command = ("claude plugin list --json" if kind == "copies"
               else "claude plugin configure <id> --json")
    usage = f"odoo-tools: --check-{kind} reads the output of `{command}` on stdin"
    raw = stdin.read()
    if not raw.strip():
        out.write(f"{usage}; nothing was piped in.\n")
        return 2
    try:
        doc = json.loads(raw)
    except ValueError:
        out.write(f"{usage}; the input is not JSON.\n")
        return 2
    try:
        report = check_copies(doc) if kind == "copies" else check_options(doc)
    except InputError as exc:
        out.write(f"{usage}: {exc}.\n")
        return 2
    except (TypeError, ValueError, AttributeError, KeyError):
        # Odd values inside valid JSON; nothing of them is repeated.
        out.write(f"{usage}; the input holds values of an unexpected type.\n")
        return 2
    if as_json:
        out.write(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n")
    else:
        out.write(report.render())
    return 0 if report.ok else 1
