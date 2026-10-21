# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""``run_stdio.py --check-policy FILE``: the offline check of a policy file (design 5.7).

It prints the profile, the digest, the rules, the openings, the warnings, the hidden
tools and one line per ``--explain``, and exits 0 (valid), 1 (an E-code: the server
would start locked) or 2 (bad usage). It never contacts Odoo.
"""

from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp.__main__ import main

ROOT = Path(__file__).resolve().parents[2]
RUN_STDIO = ROOT / "server" / "run_stdio.py"
EXAMPLES = ROOT / "docs" / "policy-examples"

FILE = {
    "version": 1,
    "comment": "sales: confirm only",
    "models": {
        "*": {"call": False},
        "sale.order": {"call": ["action_confirm", "action_cancel"]},
        "account.invoice": {"read": False},
        "res.partner.bank": {"create": True, "write": True,
                             "reason": "Ticket 4312: supplier onboarding",
                             "expires": "2999-12-31"},
    },
    "tools": {"disabled": ["odoo_import"]},
}


def _file(tmp_path: Path, document: Any = FILE, name: str = "policy.json") -> Path:
    path = tmp_path / name
    path.write_text(document if isinstance(document, str) else json.dumps(document),
                    encoding="utf-8")
    path.chmod(0o600)
    return path


def _run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    stdout = sys.stdout
    sys.stdout = out
    try:
        code = main(argv)
    finally:
        sys.stdout = stdout
    return code, out.getvalue()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    # Offline by construction: any socket the check opened would fail the test.
    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("--check-policy opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_a_valid_file_prints_the_report_and_exits_0(tmp_path: Path) -> None:
    path = _file(tmp_path)
    code, out = _run(["--check-policy", str(path)])
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == f"policy file: {path}"
    assert "profile: standard" in lines
    assert any(line.startswith("digest: ") and len(line) == len("digest: ") + 12
               for line in lines)
    assert "  *: call false" in lines
    assert "  sale.order: call [action_cancel, action_confirm]" in lines
    assert ("  res.partner.bank: create true, write true; expires 2999-12-31; reason: "
            "Ticket 4312: supplier onboarding") in lines
    assert ("  res.partner.bank: create, write (security tier) until 2999-12-31: "
            "Ticket 4312: supplier onboarding") in lines  # the opening
    assert any(line.startswith("  W2 models['res.partner.bank'] opens") for line in lines)
    assert "disabled tools: odoo_import" in lines
    hidden = next(line for line in lines if line.startswith("hidden tools"))
    assert "odoo_unlink" in hidden and "odoo_import" in hidden
    assert lines[-1] == "result: valid"


def test_explain_lines(tmp_path: Path) -> None:
    path = _file(tmp_path)
    code, out = _run(["--check-policy", str(path),
                      "--explain", "res.users:write",
                      "--explain", "sale.order:call:action_confirm",
                      "--explain", "sale.order:call:write",
                      "--explain", "account.move:read",
                      "--explain", "website.page:write",
                      "--explain", "res.partner:inspect"])
    assert code == 0
    explained = [line[len("explain: "):] for line in out.splitlines()
                 if line.startswith("explain: ")]
    assert explained == [
        "res.users write: REFUSED (tier:security)",
        "sale.order call action_confirm: ALLOWED (file:sale.order)",
        "sale.order call write: REFUSED (file:sale.order)",
        "account.move read: REFUSED (file:account.invoice, alias of account.move)",
        ("website.page write: REFUSED (tier:customization, through ir.ui.view, which "
         "website.page delegates to)"),
        "res.partner inspect: ALLOWED (profile:standard)",
    ]


def test_the_profile_option(tmp_path: Path) -> None:
    path = _file(tmp_path)
    code, out = _run(["--check-policy", str(path), "--profile", " Builder ",
                      "--explain", "ir.ui.view:write"])
    assert code == 0
    assert "profile: builder" in out.splitlines()
    assert "  W6 profile 'builder'" in out
    assert "explain: ir.ui.view write: ALLOWED (profile:builder)" in out


def test_an_empty_file_argument_checks_the_profile_alone() -> None:
    code, out = _run(["--check-policy", "", "--profile", "readonly",
                      "--explain", "res.partner:write"])
    assert code == 0
    assert out.splitlines()[0] == "policy file: none (the profile alone)"
    assert "explain: res.partner write: REFUSED (profile:readonly)" in out
    assert "hidden tools (9):" in out


def test_a_relative_path_is_checked_from_the_current_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _file(tmp_path)
    monkeypatch.chdir(tmp_path)
    code, out = _run(["--check-policy", "policy.json"])
    assert code == 0
    assert out.splitlines()[0] == f"policy file: {tmp_path / 'policy.json'}"


@pytest.mark.parametrize(("document", "code_text"), [
    ({"version": 1, "modelz": {}}, "E8 "),
    ('{"version": 1, "models": {"a": {}, "a": {}}}', "E6 "),
    ({"version": 1, "models": {"res.users": {"write": True}}}, "E15 "),
    ({"version": 1, "models": {"res.users.apikeys": {"unlink": True, "reason": "x" * 20}}},
     "E18 "),
    ("{not json", "E5 "),
])
def test_an_invalid_file_exits_1_with_its_code(tmp_path: Path, document: Any,
                                               code_text: str) -> None:
    path = _file(tmp_path, document)
    code, out = _run(["--check-policy", str(path), "--explain", "res.partner:read"])
    assert code == 1
    error = next(line for line in out.splitlines() if line.startswith("error: "))
    assert error.startswith("error: " + code_text)
    assert "explain: res.partner read: REFUSED (locked)" in out
    assert out.splitlines()[-1].startswith("result: INVALID. The server would start locked")


def test_an_unknown_profile_and_a_missing_file_exit_1(tmp_path: Path) -> None:
    code, out = _run(["--check-policy", "", "--profile", "readonyl"])
    assert code == 1 and "error: E1 unknown permission profile 'readonyl'" in out
    code, out = _run(["--check-policy", str(tmp_path / "missing.json")])
    assert code == 1 and "error: E3 " in out


def test_json_output(tmp_path: Path) -> None:
    path = _file(tmp_path)
    code, out = _run(["--check-policy", str(path), "--json", "--explain", "res.users:write"])
    assert code == 0
    report = json.loads(out)
    assert report["valid"] is True and report["profile"] == "standard"
    assert report["file"] == str(path) and len(report["digest"]) == 12
    assert report["disabled_tools"] == ["odoo_import"]
    assert {"key": "sale.order", "call": ["action_cancel", "action_confirm"], "reason": None,
            "expires": None} in report["rules"]
    assert report["opened_sensitive"][0]["model"] == "res.partner.bank"
    assert report["explain"] == [{"model": "res.users", "op": "write", "method": None,
                                  "allowed": False, "rule": "tier:security",
                                  "line": "res.users write: REFUSED (tier:security)"}]
    bad = _file(tmp_path, {"version": 2}, "bad.json")
    code, out = _run(["--check-policy", str(bad), "--json"])
    report = json.loads(out)
    assert code == 1 and report["valid"] is False and report["error_code"] == "E7"


def test_the_digest_is_the_one_the_server_reports(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from odoo_mcp.policy import Policy
    from odoo_mcp.registry import registry

    path = _file(tmp_path)
    settings = SimpleNamespace(policy_profile="standard", policy_file=str(path), readonly=False)
    expected = Policy.from_settings(settings, [tool.name for tool in registry.all()]).digest
    code, out = _run(["--check-policy", str(path)])
    assert code == 0 and f"digest: {expected}" in out.splitlines()


@pytest.mark.parametrize("argv", [
    ["--explain", "res.users:write"],  # needs --check-policy
    ["--profile", "full"],
    ["--json"],
    ["--check-policy", "", "--explain", "res.users"],  # MODEL:OP
    ["--check-policy", "", "--explain", "res.users:delete"],  # not an operation
    ["--check-policy", "", "--verify-audit", "x.jsonl"],
])
def test_bad_usage_exits_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(argv)
    assert raised.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_through_run_stdio_with_the_exit_codes(tmp_path: Path) -> None:
    # As a team's CI would run it: the shipped entry point, standard library only.
    good = subprocess.run([sys.executable, "-I", str(RUN_STDIO), "--check-policy",
                           str(EXAMPLES / "production-hardened.json"), "--explain",
                           "res.partner:call:message_post"],
                          capture_output=True, text=True, timeout=60, check=False)
    assert good.returncode == 0, good.stderr
    assert "explain: res.partner call message_post: ALLOWED (file:res.partner)" in good.stdout
    assert good.stderr == ""
    bad = subprocess.run([sys.executable, "-I", str(RUN_STDIO), "--check-policy",
                          str(_file(tmp_path, "[]"))],
                         capture_output=True, text=True, timeout=60, check=False)
    assert bad.returncode == 1 and "error: E7 " in bad.stdout
    usage = subprocess.run([sys.executable, "-I", str(RUN_STDIO), "--explain", "a:read"],
                           capture_output=True, text=True, timeout=60, check=False)
    assert usage.returncode == 2 and usage.stdout == ""
