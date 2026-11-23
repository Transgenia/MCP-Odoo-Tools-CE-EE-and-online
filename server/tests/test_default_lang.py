# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The default read language (ODOO_DEFAULT_LANG).

Without a ``lang`` in the context Odoo answers translatable fields in en_US, whatever
the user's own language. The session asks Odoo once per sign-in for the user's
language (``res.users.context_get``; JSON-2 already calls it to sign in) and adds it
to the context of read methods only. An explicit ``lang`` wins, writes are sent as
written, ``off`` restores the previous behaviour and a language code fixes one.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo, json_reply

from odoo_mcp.compat import EnvFacts
from odoo_mcp.config import Settings, default_lang_setting
from odoo_mcp.registry import ToolContext
from odoo_mcp.session import LANG_READ_METHODS, Credentials, OdooSession
from odoo_mcp.tenancy import ConnectionManager
from odoo_mcp.tools.crud import odoo_read
from odoo_mcp.tools.i18n import odoo_translate_get, odoo_translate_set

KEY = "k" * 40
ODOO_VERSIONS = list(range(10, 20))


class _Transport:
    """A legacy transport (XML-RPC/JSON-RPC shape) that records every ORM call."""

    def __init__(self, lang: Any = "es_MX", *, fail: Exception | None = None,
                 active: int = 1) -> None:
        self.lang = lang
        self.fail = fail
        self.active = active
        self.calls: list[tuple[str, str, list[Any], dict[str, Any]]] = []

    def authenticate(self, db: str, login: str, secret: str) -> int:
        return 7

    def execute_kw(self, db: str, uid: int, secret: str, model: str, method: str,
                   args: list[Any], kwargs: dict[str, Any] | None = None,
                   ids: Any = None, *, transports: Any = None) -> Any:
        self.calls.append((model, method, args, kwargs or {}))
        if method == "context_get":
            if self.fail is not None:
                raise self.fail
            return {"lang": self.lang, "tz": "America/Mexico_City", "uid": uid}
        if (model, method) == ("res.lang", "search_count"):
            return self.active
        if method == "read":
            return [{"id": 178, "name": "Viático Prospección"}]
        if method == "fields_get":
            return {"name": {"type": "char", "string": "Name"}}
        return []

    def data_calls(self) -> list[tuple[str, str, list[Any], dict[str, Any]]]:
        return [c for c in self.calls
                if c[1] != "context_get" and c[0:2] != ("res.lang", "search_count")]

    def count(self, method: str) -> int:
        return sum(1 for c in self.calls if c[1] == method)


def _session(transport: _Transport, mode: str = "user", version: int | None = 19) -> OdooSession:
    session = OdooSession(Credentials("https://odoo.example", "db", "api@example.com", KEY,
                                      secret_kind="api_key"), default_lang=mode)
    session.transport = transport  # type: ignore[assignment]
    if version is not None:
        session._facts = EnvFacts(version, "community", "onprem")
    return session


# -- reads without lang get the user's language ----------------------------------


@pytest.mark.parametrize("method", sorted(LANG_READ_METHODS))
def test_every_read_method_gets_the_users_language(method: str) -> None:
    transport = _Transport()
    _session(transport).execute("product.template", method, [[]], {})
    assert transport.data_calls() == [
        ("product.template", method, [[]], {"context": {"lang": "es_MX"}})]


@pytest.mark.parametrize("version", ODOO_VERSIONS)
def test_a_read_gets_the_language_on_every_supported_version(version: int) -> None:
    transport = _Transport()
    _session(transport, version=version).execute(
        "product.template", "search_read", [[["sale_ok", "=", True]]], {"fields": ["name"]})
    assert transport.data_calls()[-1][3] == {"fields": ["name"], "context": {"lang": "es_MX"}}


def test_the_language_is_asked_once_per_sign_in() -> None:
    transport = _Transport()
    session = _session(transport)
    for _ in range(3):
        session.execute("product.template", "read", [[1]], {"fields": ["name"]})
    assert transport.count("context_get") == 1
    assert session.default_lang == "es_MX"


def test_other_context_keys_stay_and_the_callers_dict_is_not_changed() -> None:
    transport = _Transport()
    kwargs = {"fields": ["name"], "context": {"active_test": False}}
    _session(transport).execute("product.template", "search_read", [[]], kwargs)
    assert transport.data_calls()[-1][3] == {
        "fields": ["name"], "context": {"active_test": False, "lang": "es_MX"}}
    assert kwargs == {"fields": ["name"], "context": {"active_test": False}}


# -- an explicit lang always wins ------------------------------------------------


@pytest.mark.parametrize("explicit", ["en_US", "de_DE", False, None])
def test_an_explicit_lang_wins(explicit: Any) -> None:
    transport = _Transport()
    kwargs = {"fields": ["name"], "context": {"lang": explicit}}
    _session(transport).execute("product.template", "read", [[1]], kwargs)
    assert transport.data_calls()[-1][3] == {"fields": ["name"], "context": {"lang": explicit}}


# -- writes and every other method are sent as written ---------------------------


@pytest.mark.parametrize("method,args,kwargs", [
    ("write", [[1], {"name": "Nuevo"}], {}),
    ("create", [{"name": "Nuevo"}], {}),
    ("unlink", [[1]], {}),
    ("action_confirm", [[1]], {}),
    ("update_field_translations", [[1], "name", {"en_US": "New"}], {}),
    ("get_field_translations", [[1], "name"], {}),
    ("write", [[1], {"name": "x"}], {"context": {"tracking_disable": True}}),
])
def test_writes_and_other_methods_get_nothing(method: str, args: list[Any],
                                               kwargs: dict[str, Any]) -> None:
    transport = _Transport()
    _session(transport).execute("product.template", method, args, dict(kwargs))
    assert transport.data_calls()[-1] == ("product.template", method, args, kwargs)


# -- the switch ------------------------------------------------------------------


def test_off_is_the_previous_behaviour() -> None:
    transport = _Transport()
    session = _session(transport, "off")
    session.execute("product.template", "search_read", [[]], {"fields": ["name"]})
    assert transport.calls == [("product.template", "search_read", [[]], {"fields": ["name"]})]
    assert session.default_lang is None


def test_a_fixed_language_is_checked_once_and_skips_context_get() -> None:
    transport = _Transport()
    session = _session(transport, "de_DE")
    session.execute("product.template", "read", [[1]], {})
    session.execute("product.template", "read", [[1]], {})
    assert transport.count("context_get") == 0
    assert transport.count("search_count") == 1
    assert transport.data_calls()[-1][3] == {"context": {"lang": "de_DE"}}


def test_a_fixed_language_that_is_not_active_adds_nothing(
        caplog: pytest.LogCaptureFixture) -> None:
    transport = _Transport(active=0)
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.session"):
        _session(transport, "fr_FR").execute("product.template", "read", [[1]], {})
    assert transport.data_calls()[-1][3] == {}
    assert any("not an active language" in r.getMessage() for r in caplog.records)


def test_an_english_user_sees_no_change() -> None:
    transport = _Transport(lang="en_US")
    _session(transport).execute("product.template", "read", [[1]], {"fields": ["name"]})
    assert transport.data_calls()[-1][3] == {"fields": ["name"]}


@pytest.mark.parametrize("lang", [None, False, "", 0])
def test_a_user_without_language_sees_no_change(lang: Any) -> None:
    transport = _Transport(lang=lang)
    _session(transport).execute("product.template", "read", [[1]], {})
    assert transport.data_calls()[-1][3] == {}


def test_a_failed_context_get_keeps_the_sign_in_and_the_previous_behaviour(
        caplog: pytest.LogCaptureFixture) -> None:
    transport = _Transport(fail=RuntimeError("Access denied"))
    session = _session(transport)
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.session"):
        assert session.uid == 7
        session.execute("product.template", "read", [[1]], {})
    assert transport.data_calls()[-1][3] == {}
    assert any("default language not resolved" in r.getMessage() for r in caplog.records)


# -- Odoo 10 to 12 may take the context positionally -----------------------------


@pytest.mark.parametrize("version,expected", [
    *[(v, {}) for v in (10, 11, 12)],
    *[(v, {"context": {"lang": "es_MX"}}) for v in range(13, 20)],
    (None, {}),  # series not probed yet: left alone
])
def test_a_positional_object_is_left_alone_where_it_may_be_the_context(
        version: int | None, expected: dict[str, Any]) -> None:
    transport = _Transport()
    _session(transport, version=version).execute(
        "product.template", "read", [[1], ["name"], {"lang": "de_DE"}], {})
    assert transport.data_calls()[-1][3] == expected


# -- JSON-2 reuses the context_get of its own sign-in ----------------------------


@pytest.fixture
def fake() -> Iterator[FakeOdoo]:
    server = FakeOdoo()
    yield server
    server.close()


def test_json2_reuses_the_sign_in_context(fake: FakeOdoo) -> None:
    fake.serve_version()

    def dispatch(request: dict[str, Any]) -> Any:
        _, _, _, model, method = request["path"].split("/", 4)
        if (model, method) == ("res.users", "context_get"):
            return json_reply(200, {"lang": "es_MX", "tz": "UTC", "uid": 2})
        if (model, method) == ("res.users", "read"):
            return json_reply(200, [{"id": 2, "login": "admin"}])
        return json_reply(200, [{"id": 235, "name": "Consultoría funcional Odoo Jr - 2026"}])

    fake.on_prefix("POST", "/json/2/", dispatch)
    session = OdooSession(Credentials(url=fake.url, db="db", login="admin", secret=KEY,
                                      secret_kind="api_key"), timeout=5)
    session.execute("product.template", "read", [[235]], {"fields": ["name"]})
    paths = [r["path"] for r in fake.calls("/json/2/")]
    assert paths.count("/json/2/res.users/context_get") == 1
    read = next(r for r in fake.calls("/json/2/product.template/read"))
    body = read["body"] if isinstance(read["body"], dict) else json.loads(read["body"])
    assert body["context"] == {"lang": "es_MX"}
    assert session.default_lang == "es_MX"


# -- through the tools -----------------------------------------------------------


def _tool_calls(tool: Any, args: dict[str, Any], mode: str, version: int) -> list[Any]:
    transport = _Transport()
    tool(ToolContext(session=_session(transport, mode, version), manager=None), args)
    return transport.data_calls()


@pytest.mark.parametrize("version", ODOO_VERSIONS)
def test_odoo_read_reads_in_the_users_language(version: int) -> None:
    calls = _tool_calls(odoo_read, {"model": "product.template", "ids": [178]}, "user", version)
    assert calls[-1] == ("product.template", "read", [[178]], {"context": {"lang": "es_MX"}})


@pytest.mark.parametrize("version", ODOO_VERSIONS)
@pytest.mark.parametrize("tool,args", [
    (odoo_translate_get, {"model": "product.template", "id": 178, "field": "name",
                          "lang": "en_US"}),
    (odoo_translate_set, {"model": "product.template", "id": 178, "field": "name",
                          "lang": "en_US", "value": "Prospecting travel expense"}),
], ids=["odoo_translate_get", "odoo_translate_set"])
def test_the_translation_tools_send_the_same_calls_as_before(tool: Any, args: dict[str, Any],
                                                              version: int) -> None:
    assert _tool_calls(tool, args, "user", version) == _tool_calls(tool, args, "off", version)


# -- configuration ---------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("", "user"), ("user", "user"), ("USER", "user"), ("  ", "user"),
    ("off", "off"), ("OFF", "off"), ("none", "off"), ("false", "off"), ("0", "off"),
    ("es_MX", "es_MX"), (" de_DE ", "de_DE"), ("es_419", "es_419"), ("sr@latin", "sr@latin"),
    ("es-MX", "user"), ("Spanish", "user"), ("es_MX;rm", "user"),
])
def test_the_setting(raw: str, expected: str) -> None:
    assert default_lang_setting(raw) == expected


def test_settings_read_odoo_default_lang(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODOO_DEFAULT_LANG", "off")
    assert Settings.from_env().default_lang == "off"
    monkeypatch.setenv("ODOO_DEFAULT_LANG", "${user_config.odoo_default_lang}")
    assert Settings.from_env().default_lang == "user"
    monkeypatch.delenv("ODOO_DEFAULT_LANG")
    assert Settings.from_env().default_lang == "user"


@pytest.mark.parametrize("mode", ["user", "off", "es_MX"])
def test_the_connection_manager_passes_the_setting_on(mode: str) -> None:
    manager = ConnectionManager(Settings(default_lang=mode))
    session = manager.get(Credentials("https://odoo.example", "db", "me", KEY))
    assert session.default_lang_mode == mode
