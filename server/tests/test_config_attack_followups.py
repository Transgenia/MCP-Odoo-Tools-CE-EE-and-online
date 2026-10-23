# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Second-round (adversarial) review fixes on the config and audit surface.

  * odoo_connections handed back ODOO_URL with its user:password@ (a gateway
    credential) under every profile: now stripped, as the transport and the
    guard's CredsView already strip it;
  * a policy file whose only content is the JSON value ``null`` loaded unlocked
    as the profile alone while the server reported a file in force: now E7;
  * session_key() collided for different url/db/login splits containing ``|``:
    the HMAC now covers the whole connection identity, fingerprint() unchanged;
  * the audit start line was lost when a path/db/login carried non-UTF-8 bytes
    (surrogates): surrogates are dropped like the other control categories;
  * a pre-existing daily audit file with loose permissions was appended to as
    is: it is tightened to 0600 first;
  * the plugin pins ODOO_AUDIT_RETENTION_DAYS like it pins ODOO_AUDIT_DIR, so an
    inherited value cannot prune the trail.
"""

from __future__ import annotations

import datetime
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from odoo_mcp import tools as _tools  # noqa: F401 - registers the tools
from odoo_mcp.audit import AuditLog, file_name
from odoo_mcp.config import Settings
from odoo_mcp.policy.loader import load_policy
from odoo_mcp.registry import registry
from odoo_mcp.server import McpServer
from odoo_mcp.session import Credentials
from odoo_mcp.tenancy import ConnectionManager

ROOT = Path(__file__).resolve().parents[2]
NOON = datetime.datetime(2026, 10, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)
NAMES = [t.name for t in registry.all()]


class Clock:
    def __init__(self, now: datetime.datetime = NOON) -> None:
        self.now = now

    def __call__(self) -> datetime.datetime:
        return self.now


# --- odoo_connections never returns the URL password --------------------------------


@pytest.mark.parametrize("profile", ["readonly", "standard", "full"])
def test_odoo_connections_strips_the_url_userinfo(profile: str) -> None:
    canary = "GatewayPw-CANARY-9931"
    settings = Settings(url=f"https://gateway:{canary}@odoo.example", db="db",
                        login="bot@example.com", api_key="k" * 40, policy_profile=profile)
    manager = ConnectionManager(settings)
    srv = McpServer(settings, manager=manager, audit=AuditLog("off"))
    manager.default()  # build the stdio session (no network)
    result = srv.call_tool({"name": "odoo_connections", "arguments": {}})
    text = result["content"][0]["text"]
    assert not result["isError"]
    assert canary not in text
    # the URL is still reported, without its user:password@ part (an exact match,
    # not a substring check, which CodeQL reads as URL sanitization)
    assert [c["url"] for c in json.loads(text)["connections"]] == ["https://odoo.example"]


# --- a null policy file locks, it is not read as "no file" ---------------------------


def test_a_null_policy_file_locks_with_e7(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("null\n")
    if os.name == "posix":
        path.chmod(0o600)
    p = load_policy(SimpleNamespace(policy_profile="standard", policy_file=str(path),
                                    readonly=False), NAMES)
    assert p.source == str(path)
    assert p.locked and p.error_code == "E7"


@pytest.mark.parametrize("body", ["null\n", "[]", "\"x\"", "42", "true"])
def test_a_non_object_top_level_locks_with_e7(tmp_path: Path, body: str) -> None:
    path = tmp_path / "policy.json"
    path.write_text(body)
    if os.name == "posix":
        path.chmod(0o600)
    p = load_policy(SimpleNamespace(policy_profile="standard", policy_file=str(path),
                                    readonly=False), NAMES)
    assert p.locked and p.error_code == "E7"


# --- the session key never collides for different tenants ----------------------------


def test_session_keys_of_different_tenants_never_collide() -> None:
    a = Credentials(url="https://odoo.example|db1", db="x", login="l", secret="s")
    b = Credentials(url="https://odoo.example", db="db1|x", login="l", secret="s")
    assert a.fingerprint() == b.fingerprint()  # the pipe-joined strings do collide
    assert a.session_key() != b.session_key()  # the key does not


def test_the_session_key_still_hides_the_secret_and_keeps_its_prefix() -> None:
    a = Credentials(url="https://o.example", db="d", login="l", secret="S3CRET",
                    secret_kind="api_key")
    key = a.session_key()
    assert key.startswith("https://o.example|d|l|api_key|")
    assert "S3CRET" not in key and len(key.rsplit("|", 1)[1]) == 32
    # the secret_kind is part of the material, so an api_key and a password differ
    b = Credentials(url="https://o.example", db="d", login="l", secret="S3CRET",
                    secret_kind="password")
    assert a.session_key() != b.session_key()


def test_a_secret_with_surrogate_bytes_keys_without_crashing() -> None:
    a = Credentials(url="u", db="d", login="l", secret=os.fsdecode(b"pw\xff"))
    assert a.session_key()


# --- the audit start line survives odd bytes, and tightens a loose file --------------


def test_a_policy_path_with_odd_bytes_still_writes_the_start_line(tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    odd = os.fsdecode(b"/etc/odoo-tools/pol\xe9.json")
    p = load_policy(SimpleNamespace(policy_profile="standard", policy_file=odd, readonly=False),
                    [])
    audit = AuditLog("file", str(folder), clock=Clock())
    audit.start(Settings(db="db", login="l"), p)
    files = list(folder.iterdir())
    assert files and files[0].read_bytes().count(b"\n") == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_a_preexisting_loose_daily_file_is_tightened_before_it_is_written(
        tmp_path: Path) -> None:
    folder = tmp_path / "audit"
    folder.mkdir(mode=0o700)
    path = folder / file_name(NOON.date())
    path.write_bytes(b"")
    path.chmod(0o666)
    AuditLog("file", str(folder), clock=Clock()).start(Settings(db="db", login="who@x"), None)
    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


# --- the plugin pins the retention like it pins the folder ---------------------------


def test_the_plugin_env_pins_the_audit_retention() -> None:
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    env = manifest["mcpServers"]["odoo"]["env"]
    assert "ODOO_AUDIT_DIR" in env
    assert "ODOO_AUDIT_RETENTION_DAYS" in env
    # the pinned value is a retention Settings accepts (1..3650, 0 keeps forever)
    assert int(env["ODOO_AUDIT_RETENTION_DAYS"]) >= 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
