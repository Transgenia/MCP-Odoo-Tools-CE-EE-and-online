# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""1.6.0: the admin API key of the local sandbox (``scripts/deploy_local.py``), without Docker.

On Odoo 14.0+ ``sandbox up`` has Odoo create an API key for the admin user with
``odoo shell`` and keeps it in the owner-only ``.env`` for the plugin's "Odoo API key"
option; 10.0-13.0 have no API keys and keep the password. These tests run the script
``odoo shell`` executes against stand-ins for both signatures of
``res.users.apikeys._generate``, parse what it prints, and drive ``sandbox up`` with a
scripted Docker and Odoo: the key is created once, reused, replaced when Odoo no
longer takes it, never printed or raised, and the sandbox falls back to the password
when it cannot be made. The sandbox matrix workflow runs the real thing on 10.0-19.0.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import secrets
import subprocess
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "deploy_local_api_key", ROOT / "scripts" / "deploy_local.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dl = _load()

# What Odoo's shell may print around the key: log lines, a warning, blank lines.
NOISE = ("2026-10-30 03:58:00,761 1 INFO sandbox odoo.modules.loading: loading 1 modules...\n"
         "\n"
         "/usr/lib/python3/dist-packages/odoo/http.py:1: DeprecationWarning: something\n")


# --------------------------------------------------- the script odoo shell runs

ADMIN = object()  # the record env.ref("base.user_admin") returns


class Keys14:
    """``res.users.apikeys`` on Odoo 14.0-17.0: ``_generate(scope, name)``."""

    def __init__(self, log: list[Any], made: list[str]) -> None:
        self.log, self.made = log, made

    def with_user(self, user: Any) -> Keys14:
        self.log.append(("with_user", user))
        return self

    def _generate(self, scope: Any, name: str) -> str:
        return self.make(scope=scope, name=name)

    def make(self, **values: Any) -> str:
        key = secrets.token_hex(20)  # what Odoo returns: 40 hex characters
        self.log.append(("generate", values))
        self.made.append(key)
        return key


class Keys18(Keys14):
    """Odoo 18.0+: ``_generate(scope, name, expiration_date)``."""

    def _generate(self, scope: Any, name: str, expiration_date: Any) -> str:  # type: ignore[override]
        return self.make(scope=scope, name=name, expiration_date=expiration_date)


class KeysOwner(Keys14):
    """A series whose ``_generate`` would need a parameter the script does not know."""

    def _generate(self, scope: Any, name: str, owner: Any) -> str:  # type: ignore[override]
        return self.make(scope=scope, name=name, owner=owner)


class KeysOptional(Keys14):
    """Extra parameters with defaults are left to Odoo."""

    def _generate(self, scope: Any, name: str, expiration_date: Any = None,  # type: ignore[override]
                  note: str = "") -> str:
        return self.make(scope=scope, name=name, expiration_date=expiration_date, note=note)


class Env:
    """Just enough of the ``env`` that ``odoo shell`` gives a script."""

    def __init__(self, keys: Keys14, log: list[Any]) -> None:
        self.keys, self.log = keys, log
        self.cr = types.SimpleNamespace(commit=lambda: log.append(("commit",)))

    def ref(self, xmlid: str) -> Any:
        self.log.append(("ref", xmlid))
        return ADMIN

    def __getitem__(self, model: str) -> Keys14:
        self.log.append(("model", model))
        return self.keys


def run_in_shell(script: str, keys: type[Keys14] = Keys18,
                 made: list[str] | None = None) -> tuple[str, list[Any], list[str]]:
    """What ``odoo shell`` does with a script read from stdin: exec it with ``env``."""
    log: list[Any] = []
    made = [] if made is None else made
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        # The script deploy_local.py sends to `odoo shell`, run as that shell runs it.
        exec(compile(script, "<stdin>", "exec"),  # noqa: S102
             {"env": Env(keys(log, made), log), "__name__": "__main__"})
    return out.getvalue(), log, made


@pytest.mark.parametrize("keys,expiry", [(Keys14, False), (Keys18, True)])
def test_the_script_reads_the_signature_of_each_series(keys: type[Keys14],
                                                       expiry: bool) -> None:
    script = dl.api_key_script()
    assert script.isascii()
    out, log, made = run_in_shell(script, keys)
    values = {"scope": None, "name": "odoo-tools sandbox"}
    if expiry:  # 18.0+: no expiration date, which Odoo allows administrators
        values["expiration_date"] = None
    assert log == [("ref", "base.user_admin"), ("model", "res.users.apikeys"),
                   ("with_user", ADMIN), ("generate", values), ("commit",)]
    assert out == f"{dl.API_KEY_MARK}{made[0]}\n"  # one line, after the commit
    assert dl.parse_api_key(out) == made[0]


def test_an_unknown_required_parameter_stops_before_any_key_is_made() -> None:
    with pytest.raises(SystemExit, match="unknown parameters: owner"):
        run_in_shell(dl.api_key_script(), KeysOwner)
    out, log, made = run_in_shell(dl.api_key_script(), KeysOptional)
    assert ("generate", {"scope": None, "name": "odoo-tools sandbox",
                         "expiration_date": None, "note": ""}) in log
    assert dl.parse_api_key(out) == made[0]


# ------------------------------------------------------------- the stdout parser

def _key() -> str:
    return secrets.token_hex(20)


def test_the_parser_reads_the_marked_line_among_junk() -> None:
    key, other = _key(), _key()
    mark = dl.API_KEY_MARK
    assert dl.parse_api_key(f"{NOISE}{mark}{key}\n{NOISE}") == key
    assert dl.parse_api_key(f"{NOISE}\r\n  {mark} {key} \r\n") == key  # CRLF, spaces
    assert dl.parse_api_key(f"{mark}{other}\n{mark}{key}\n") == key  # the last one
    assert dl.parse_api_key(f"INFO quoting {mark}{key}\n") is None  # not at the start


@pytest.mark.parametrize("output", [
    None, "", NOISE, f"{NOISE}{dl.API_KEY_MARK}\n", f"{dl.API_KEY_MARK}   \n",
    f"{dl.API_KEY_MARK}short\n", f"{dl.API_KEY_MARK}two words in a line\n",
    f"{dl.API_KEY_MARK}{'a' * 300}\n", f"{dl.API_KEY_MARK}quote'or;semicolon$x\n",
], ids=["none", "empty", "junk", "mark-alone", "blank", "short", "spaces", "long", "odd"])
def test_the_parser_finds_no_key(output: str | None) -> None:
    assert dl.parse_api_key(output) is None


def test_an_error_line_never_shows_a_secret() -> None:
    key, password = _key(), secrets.token_urlsafe(18)
    stderr = (f"{NOISE}{dl.API_KEY_MARK}{key}\n"
              f"psycopg2.OperationalError: password {password} rejected, token {_key()}\n")
    shown = dl.last_line(stderr, [key, password])
    assert shown == "psycopg2.OperationalError: password <hidden> rejected, token <hidden>"
    assert dl.last_line(f"{dl.API_KEY_MARK}{key}\n", [key]) == ""  # never the marked line
    assert dl.last_line(None) == "" and len(dl.last_line("x" * 500)) == 200


# ------------------------------------------------ sandbox up, scripted end to end

class FakeOdoo:
    """The XML-RPC calls ``sandbox up`` makes, and the API keys this Odoo accepts."""

    def __init__(self) -> None:
        self.version = "18.0"
        self.databases: list[str] = []
        self.password = ""
        self.keys: list[str] = []

    def rpc(self, url: str, service: str, method: str, args: list[Any],
            timeout: float = 30) -> Any:
        if method == "version":
            return {"server_version": self.version}
        if method == "list":
            return list(self.databases)
        if method == "create_database":
            self.databases.append(args[1])
            self.password = args[4]
            return True
        if method == "authenticate":
            db, login, secret, _context = args
            ok = db in self.databases and login == "admin" and \
                (secret == self.password or secret in self.keys)
            return 2 if ok else False
        raise AssertionError(f"unexpected call {service}.{method}")


Shell = Callable[[Any, str, str, float], subprocess.CompletedProcess]


class Harness:
    """``deploy_local.py sandbox up`` with Docker and Odoo scripted; no process is started."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                 capsys: pytest.CaptureFixture[str]) -> None:
        self.dir = tmp_path / "sbx"
        self.capsys = capsys
        self.odoo = FakeOdoo()
        self.keys: type[Keys14] = Keys18
        self.accept = True  # whether Odoo signs in with the keys the script makes
        self.made: list[str] = []  # every key a script created, accepted or not
        self.shell_calls: list[tuple[str, float]] = []
        self.shell: Shell | None = None  # None: run the real script
        monkeypatch.setattr(dl, "compose_command", lambda: ["docker", "compose"])
        monkeypatch.setattr(dl, "check_docker_running", lambda: None)
        monkeypatch.setattr(dl.Sandbox, "running", lambda box: True)
        monkeypatch.setattr(dl.Sandbox, "pull", lambda box, env, registry: env)
        monkeypatch.setattr(dl.Sandbox, "compose", lambda box, *a, **k:
                            subprocess.CompletedProcess(a, 0, "", ""))
        monkeypatch.setattr(dl, "rpc", self.odoo.rpc)
        monkeypatch.setattr(dl, "wait_for_odoo",
                            lambda url, timeout: {"server_version": self.odoo.version})
        def odoo_shell(box: Any, db: str, script: str,
                       timeout: float) -> subprocess.CompletedProcess:
            return self._odoo_shell(box, db, script, timeout)

        monkeypatch.setattr(dl.Sandbox, "odoo_shell", odoo_shell)

        def no_process(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(f"a test started a process: {args[0] if args else kwargs}")
        monkeypatch.setattr(dl.subprocess, "run", no_process)

    def _odoo_shell(self, box: Any, db: str, script: str,
                    timeout: float) -> subprocess.CompletedProcess:
        self.shell_calls.append((db, timeout))
        if self.shell is not None:
            return self.shell(box, db, script, timeout)
        out, _log, made = run_in_shell(script, self.keys)
        self.made.extend(made)
        if self.accept:
            self.odoo.keys.extend(made)
        return subprocess.CompletedProcess(["docker"], 0, NOISE + out, NOISE)

    @property
    def env_file(self) -> Path:
        return self.dir / ".env"

    def env(self) -> dict[str, str]:
        return dl.read_env(self.env_file)

    def up(self, *extra: str) -> tuple[str, str]:
        assert dl.main(["sandbox", "up", "--dir", str(self.dir), *extra]) == 0
        out, err = self.capsys.readouterr()
        self.assert_no_secret(out + err)
        return out, err

    def secret_values(self) -> list[str]:
        env = self.env()
        return [env[name] for name in dl.SECRET_NAMES if env.get(name)] + self.made

    def assert_no_secret(self, text: str) -> None:
        values = self.secret_values()
        assert values  # there is always at least the passwords to look for
        for value in values:
            assert value not in text


def summary(out: str) -> dict[str, Any]:
    return json.loads(out.split("Sandbox ready:\n", 1)[1].split("\n\n", 1)[0])


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
            capsys: pytest.CaptureFixture[str]) -> Harness:
    return Harness(tmp_path, monkeypatch, capsys)


@pytest.mark.parametrize("version,keys", [("14.0", Keys14), ("17.0", Keys14),
                                          ("18.0", Keys18), ("19.0", Keys18)])
def test_up_creates_the_key_once_and_reuses_it(harness: Harness, version: str,
                                               keys: type[Keys14]) -> None:
    harness.odoo.version, harness.keys = version, keys
    out, _err = harness.up("--odoo", version)
    assert harness.shell_calls == [("sandbox", 300.0)]
    key = harness.env()["ODOO_API_KEY"]
    assert key == harness.odoo.keys[0] and re.fullmatch(r"[0-9a-f]{40}", key)
    if os.name == "posix":
        assert (harness.env_file.stat().st_mode & 0o777) == 0o600
    assert "[5/5] API key: Odoo creates one for the admin user" in out
    ready = summary(out)
    assert ready["api_key"] == f"ODOO_API_KEY in {harness.env_file} (not printed)"
    assert ready["plugin_credential"] == "Odoo API key = ODOO_API_KEY, Odoo password empty"
    assert ready["password"] == f"ODOO_ADMIN_PASSWORD in {harness.env_file} (not printed)"

    out, _err = harness.up()  # a later run, as `sandbox up` with no options
    assert len(harness.shell_calls) == 1  # no second key
    assert harness.env()["ODOO_API_KEY"] == key and harness.odoo.keys == [key]
    assert "[5/5] API key: reusing the one in .env" in out
    assert summary(out)["plugin_credential"] == "Odoo API key = ODOO_API_KEY, Odoo password empty"


def test_a_key_odoo_no_longer_takes_is_replaced(harness: Harness) -> None:
    harness.up("--odoo", "17.0")
    old = harness.env()["ODOO_API_KEY"]
    harness.odoo.keys.clear()  # removed under Preferences > Account Security
    out, _err = harness.up()
    assert "the one in .env no longer signs in" in out
    new = harness.env()["ODOO_API_KEY"]
    assert new != old and harness.odoo.keys == [new] and len(harness.shell_calls) == 2


@pytest.mark.parametrize("version", ["10.0", "11.0", "12.0", "13.0"])
def test_odoo_13_and_older_keep_the_password(harness: Harness, version: str) -> None:
    harness.odoo.version = version
    out, _err = harness.up("--odoo", version)
    assert harness.shell_calls == []  # Odoo's shell is never run
    assert "ODOO_API_KEY" not in harness.env()
    assert f"[5/5] API key: none, Odoo {version} has no API keys (they start with 14.0)" in out
    ready = summary(out)
    assert ready["api_key"] == f"none: Odoo {version} has no API keys (they start with 14.0)"
    assert ready["plugin_credential"] == "Odoo password = ODOO_ADMIN_PASSWORD, Odoo API key empty"
    assert "Note: the sandbox has no API key" not in out  # nothing went wrong


def _exits(box: Any, db: str, script: str, timeout: float) -> subprocess.CompletedProcess:
    # A traceback that quotes every secret of the sandbox and a key-shaped value.
    env = dl.read_env(box.env_file)
    quoted = " ".join(env[name] for name in dl.SECRET_NAMES if env.get(name))
    return subprocess.CompletedProcess(
        ["docker"], 1, NOISE,
        f"{NOISE}Traceback (most recent call last):\nValueError: {quoted} {_key()}\n")


def _silent(box: Any, db: str, script: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["docker"], 0, NOISE, NOISE)


def _times_out(box: Any, db: str, script: str, timeout: float) -> subprocess.CompletedProcess:
    raise dl.SandboxError(f"Odoo's shell did not finish within {int(timeout)}s")


@pytest.mark.parametrize("shell,accept,reason", [
    (_exits, True, "none: Odoo's shell exited with code 1: ValueError: <hidden>"),
    (_silent, True, "none: Odoo's shell printed no API key"),
    (_times_out, True, "none: Odoo's shell did not finish within 300s"),
    (None, False, "none: Odoo created a key but does not sign in with it"),
], ids=["exit-code", "no-key-printed", "timeout", "key-refused"])
def test_a_key_that_cannot_be_made_leaves_the_password(harness: Harness, shell: Shell | None,
                                                       accept: bool, reason: str) -> None:
    harness.shell, harness.accept = shell, accept
    out, _err = harness.up("--odoo", "18.0")  # still a working sandbox (exit code 0)
    assert "ODOO_API_KEY" not in harness.env()
    ready = summary(out)
    assert ready["api_key"].startswith(reason)
    assert ready["plugin_credential"] == "Odoo password = ODOO_ADMIN_PASSWORD, Odoo API key empty"
    assert "Note: the sandbox has no API key (" in out
    assert "the next `sandbox up` tries again" in out
    # and it does: with a working shell the next run creates the key
    harness.shell, harness.accept = None, True
    out, _err = harness.up()
    assert harness.env()["ODOO_API_KEY"] in harness.odoo.keys
    assert summary(out)["plugin_credential"].startswith("Odoo API key")


def test_the_command_text_follows_the_summary(harness: Harness) -> None:
    # /odoo-tools:deploy-local tells Claude which plugin field to fill from the summary.
    text = " ".join((ROOT / "commands" / "deploy-local.md").read_text(encoding="utf-8").split())
    assert "the summary's `plugin_credential` says which" in text
    assert ("**Odoo 14.0 to 19.0**: **Odoo API key** = `ODOO_API_KEY` from the `.env`, and "
            "leave **Odoo password** empty") in text
    assert ("**Odoo 10.0 to 13.0**, which have no API keys: **Odoo password** = "
            "`ODOO_ADMIN_PASSWORD`, and leave **Odoo API key** empty") in text
    assert "(`api_key` starts with `none:`), use the password" in text
    assert "never ask for them in the chat" in text
    assert "(leave API key empty)" not in text  # the 1.5.1 instruction for every series
    out, _err = harness.up("--odoo", "17.0")
    assert {"api_key", "plugin_credential"} <= set(summary(out))


# --------------------------------------------------------- pieces, one by one

def test_prepare_keeps_the_key_of_the_database(tmp_path: Path) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    env = box.prepare("18.0", 8069, "sandbox", "en_US", True, "transgenia")
    env["ODOO_READY"], env["ODOO_API_KEY"] = "1", _key()
    box.write_env(env)
    again = box.prepare(None, 8070, None, None, None, "dockerhub")
    assert again["ODOO_API_KEY"] == env["ODOO_API_KEY"]
    assert dl.read_env(box.env_file)["ODOO_API_KEY"] == env["ODOO_API_KEY"]
    fresh = dl.Sandbox(tmp_path / "other").prepare("18.0", None, None, None, None,
                                                   "transgenia")
    assert "ODOO_API_KEY" not in fresh


def test_the_shell_runs_in_a_one_off_container_of_the_odoo_service(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    env = box.prepare("18.0", None, None, None, None, "transgenia")
    monkeypatch.setattr(dl, "compose_command", lambda: ["docker", "compose"])
    seen: list[tuple[list[str], dict[str, Any]]] = []

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "out", "err")

    monkeypatch.setattr(dl.subprocess, "run", run)
    assert box.odoo_shell("sandbox", "print(1)", 120).stdout == "out"
    (cmd, kwargs), = seen
    assert cmd == ["docker", "compose", "--project-name", box.project,
                   "--project-directory", str(box.dir), "-f", str(box.compose_file),
                   "--env-file", str(box.env_file),
                   "run", "--rm", "--no-deps", "-T", "odoo",
                   "odoo", "shell", "-d", "sandbox", "--no-http"]
    assert kwargs == {"input": "print(1)", "capture_output": True, "encoding": "utf-8",
                      "errors": "replace", "timeout": 120, "check": False}
    for name in dl.SECRET_NAMES:  # the entrypoint adds the database password inside
        assert not env.get(name) or env[name] not in " ".join(cmd)


def test_a_timeout_keeps_nothing_of_the_output(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    box.prepare("18.0", None, None, None, None, "transgenia")
    key = _key()
    monkeypatch.setattr(dl, "compose_command", lambda: ["docker", "compose"])

    def run(cmd: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"],
                                        output=f"{dl.API_KEY_MARK}{key}\n", stderr=key)

    monkeypatch.setattr(dl.subprocess, "run", run)
    with pytest.raises(dl.SandboxError) as info:
        box.odoo_shell("sandbox", dl.api_key_script(), 90)
    assert str(info.value) == "Odoo's shell did not finish within 90s"
    # no chained exception carries the captured output
    assert info.value.__context__ is None and info.value.__cause__ is None


def test_create_api_key_raises_without_any_secret(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    box = dl.Sandbox(tmp_path / "sbx")
    env = box.prepare("18.0", None, None, None, None, "transgenia")
    env["ODOO_API_KEY"] = _key()  # an older key, in .env
    box.write_env(env)
    values = [env[name] for name in dl.SECRET_NAMES]
    monkeypatch.setattr(dl.Sandbox, "odoo_shell", lambda self, db, script, timeout:
                        subprocess.CompletedProcess(["docker"], 2, " ".join(values),
                                                    "odoo: error: " + " ".join(values)))
    with pytest.raises(dl.SandboxError) as info:
        box.create_api_key("sandbox", 60)
    message = str(info.value)
    assert message.startswith("Odoo's shell exited with code 2: odoo: error: <hidden>")
    for value in values:
        assert value not in message
