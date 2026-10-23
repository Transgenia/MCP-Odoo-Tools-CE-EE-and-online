# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Session cache key: an HMAC of the secret, and no header-based session path."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from odoo_mcp.config import Settings
from odoo_mcp.session import Credentials
from odoo_mcp.tenancy import ConnectionManager

SRC = Path(__file__).resolve().parents[1] / "src"
SECRET_A = "S3CRET-A-DO-NOT-LEAK-0123456789abcdef"
SECRET_B = "S3CRET-B-DO-NOT-LEAK-0123456789abcdef"


def _creds(secret: str, kind: str = "api_key") -> Credentials:
    return Credentials(url="https://o.example", db="d", login="l", secret=secret,
                       secret_kind=kind)


def test_another_secret_is_another_session_and_the_same_secret_reuses_it() -> None:
    manager = ConnectionManager(Settings())
    first = manager.get(_creds(SECRET_A))
    assert manager.get(_creds(SECRET_A)) is first
    other = manager.get(_creds(SECRET_B))
    assert other is not first
    assert other.creds.secret == SECRET_B  # never another caller's authenticated session
    assert len(manager.connections()) == 2


def test_the_credential_kind_is_part_of_the_key() -> None:
    assert _creds(SECRET_A, "api_key").session_key() != _creds(SECRET_A, "password").session_key()


def test_the_key_holds_neither_the_secret_nor_its_plain_digest() -> None:
    key = _creds(SECRET_A).session_key()
    digest = hashlib.sha256(SECRET_A.encode()).hexdigest()
    assert SECRET_A not in key
    assert digest not in key and digest[:32] not in key and digest[:16] not in key
    assert key.startswith("https://o.example|d|l|api_key|")
    assert len(key.rsplit("|", 1)[1]) == 32
    assert SECRET_A not in repr(_creds(SECRET_A))


def test_the_fingerprint_is_unchanged() -> None:
    # SchemaCache is per session, so its keys keep using the fingerprint.
    assert _creds(SECRET_A).fingerprint() == "https://o.example|d|l"
    assert _creds(SECRET_A).fingerprint() == _creds(SECRET_B).fingerprint()


def _key_in_a_new_process() -> str:
    code = (
        "from odoo_mcp.session import Credentials\n"
        f"print(Credentials(url='https://o.example', db='d', login='l', secret={SECRET_A!r},"
        " secret_kind='api_key').session_key())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code],
        capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(SRC)},
        timeout=60,
        check=True,
    )
    return proc.stdout.decode().strip()


def test_the_key_differs_across_processes() -> None:
    here = _creds(SECRET_A).session_key()
    one, two = _key_in_a_new_process(), _key_in_a_new_process()
    prefix = "https://o.example|d|l|api_key|"
    assert one.startswith(prefix) and two.startswith(prefix)
    assert len({here, one, two}) == 3  # the salt is per process and never persisted


def test_from_headers_is_gone() -> None:
    # It had no caller, took the Odoo URL from a client header, passed the
    # client's bearer through to Odoo and fell back to the server's own secret.
    assert not hasattr(ConnectionManager, "from_headers")
