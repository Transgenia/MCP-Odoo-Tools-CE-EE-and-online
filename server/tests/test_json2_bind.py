# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""JSON-2 signature mismatches (HTTP 422 from Odoo's bind check) and unreachable hosts.

The fake controller below does what Odoo's JSON-2 controller does before it
calls a method: ``inspect.signature(func).bind(records, **body)``, answering
``werkzeug.exceptions.UnprocessableEntity`` with the TypeError text when that
fails. The stand-in methods use the parameter names of the saas~18.4 overrides
the plugin's base-name table does not know (``write(self, values)`` on
``product.pricelist``/``res.company``, ``res.partner.default_get(self,
default_fields)``).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fake_odoo_http import FakeOdoo, json_reply, jsonrpc_result, odoo_error, version_payload

from odoo_mcp.config import Settings
from odoo_mcp.errors import OdooFault, TransportError
from odoo_mcp.registry import ToolContext
from odoo_mcp.tenancy import ConnectionManager
from odoo_mcp.tools.crud import odoo_execute, odoo_write
from odoo_mcp.transport.fallback import FallbackTransport
from odoo_mcp.transport.json2 import (
    Json2SignatureMismatch,
    Json2Transport,
    Json2Unavailable,
    Json2Unreachable,
)
from odoo_mcp.transport.json2_signatures import Signature
from odoo_mcp.transport.jsonrpc import JsonRpcUnavailable

KEY = "K3Y-DO-NOT-LEAK-0123456789abcdef01234567"
SAAS_184 = {"server_version": "saas~18.4", "server_version_info": ["saas~18", 4, 0, "final", 0, ""]}


def _pricelist_write(self: Any, values: Any) -> bool:
    return True


def _partner_default_get(self: Any, default_fields: Any) -> dict:
    return {name: "x" for name in default_fields}


def _addon_method(self: Any, amount: Any, currency: Any) -> str:
    return f"{amount} {currency}"


METHODS: dict[tuple[str, str], Callable[..., Any]] = {
    ("product.pricelist", "write"): _pricelist_write,
    ("res.company", "write"): _pricelist_write,
    ("res.partner", "default_get"): _partner_default_get,
    ("res.partner", "search_read"): lambda self, domain=None, fields=None, offset=0,
    limit=None, order=None: [],
}


class BindingOdoo:
    """A JSON-2 endpoint that binds each body like Odoo's controller."""

    def __init__(self, fake: FakeOdoo, methods: dict[tuple[str, str], Callable[..., Any]],
                 *, version: dict | None = None) -> None:
        self.ran: list[tuple[str, str, dict[str, Any]]] = []
        fake.on("POST", "/web/webclient/version_info",
                jsonrpc_result(version or SAAS_184))

        def dispatch(request: dict[str, Any]) -> Any:
            _, _, _, model, method = request["path"].split("/", 4)
            body = dict(request["body"] or {})
            if (model, method) == ("res.users", "context_get"):
                return json_reply(200, {"uid": 2})
            if (model, method) == ("res.users", "read"):
                return json_reply(200, [{"id": 2, "login": "admin"}])
            func = methods[(model, method)]
            ids = body.pop("ids", [])
            body.pop("context", None)
            try:
                inspect.signature(func).bind(ids, **body)
            except TypeError as exc:
                return odoo_error(422, "werkzeug.exceptions.UnprocessableEntity", exc.args[0])
            self.ran.append((model, method, body))
            return json_reply(200, func(ids, **body))

        fake.on_prefix("POST", "/json/2/", dispatch)


@pytest.fixture
def fake() -> Iterator[FakeOdoo]:
    server = FakeOdoo()
    try:
        yield server
    finally:
        server.close()


def _j2(fake: FakeOdoo, series: tuple[int, int] = (18, 4)) -> Json2Transport:
    transport = Json2Transport(fake.url, timeout=5)
    transport.series = series
    return transport


def _bodies(fake: FakeOdoo, path: str) -> list[Any]:
    return [r["body"] for r in fake.seen if r["path"] == path]


# --- the bind error is recognised --------------------------------------------


def test_a_bind_422_is_a_signature_mismatch_that_never_ran(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/write", odoo_error(
        422, "werkzeug.exceptions.UnprocessableEntity", "missing a required argument: 'values'"))
    transport = _j2(fake)
    with pytest.raises(Json2SignatureMismatch) as info:
        transport._call("db", KEY, "res.partner", "write", {"ids": [1], "vals": {}})
    assert info.value.missing == "values"
    assert isinstance(info.value, JsonRpcUnavailable)  # safe to send again


@pytest.mark.parametrize("message", [
    "cannot call res.partner.create with ids",  # also 422, but a caller error
    "went wrong",
])
def test_other_422_replies_stay_faults(fake: FakeOdoo, message: str) -> None:
    fake.on("POST", "/json/2/res.partner/write",
            odoo_error(422, "werkzeug.exceptions.UnprocessableEntity", message))
    with pytest.raises(OdooFault):
        _j2(fake).execute_kw("db", 2, KEY, "res.partner", "write", [[1], {"name": "x"}])
    assert len(fake.seen) == 1


def test_a_bind_message_under_another_error_name_is_a_fault(fake: FakeOdoo) -> None:
    fake.on("POST", "/json/2/res.partner/write",
            odoo_error(422, "odoo.exceptions.ValidationError",
                       "missing a required argument: 'values'"))
    with pytest.raises(OdooFault):
        _j2(fake).execute_kw("db", 2, KEY, "res.partner", "write", [[1], {"name": "x"}])


# --- saas~18.4 overrides with other names are corrected -----------------------


@pytest.mark.parametrize("model", ["product.pricelist", "res.company"])
def test_write_with_an_override_named_values_is_retried_with_that_name(
        fake: FakeOdoo, model: str) -> None:
    odoo = BindingOdoo(fake, METHODS)
    transport = _j2(fake)
    assert transport.execute_kw("db", 2, KEY, model, "write", [[1], {"name": "X"}]) is True
    path = f"/json/2/{model}/write"
    assert _bodies(fake, path) == [{"ids": [1], "vals": {"name": "X"}},
                                   {"ids": [1], "values": {"name": "X"}}]
    assert odoo.ran == [(model, "write", {"values": {"name": "X"}})]  # ran once
    # learned for this (db, model, method): the next call is one request
    transport.execute_kw("db", 2, KEY, model, "write", [[2], {"name": "Y"}])
    assert _bodies(fake, path)[-1] == {"ids": [2], "values": {"name": "Y"}}
    assert len(_bodies(fake, path)) == 3


def test_default_get_on_saas_18_4_res_partner(fake: FakeOdoo) -> None:
    BindingOdoo(fake, METHODS)
    result = _j2(fake).execute_kw("db", 2, KEY, "res.partner", "default_get", [["name"]])
    assert result == {"name": "x"}
    assert _bodies(fake, "/json/2/res.partner/default_get") == [
        {"fields_list": ["name"]}, {"default_fields": ["name"]}]


def _addon_name_search(self: Any, name: str = "", args: Any = None, operator: str = "ilike",
                       limit: int = 100) -> list:
    return [[1, name]]


def test_on_19_the_doc_bearer_signature_corrects_several_names(fake: FakeOdoo) -> None:
    # an installed addon keeps a pre-19 name_search(name, args, ...) override: the
    # table's 'domain' is refused (unexpected keyword), /doc-bearer has the real names
    odoo = BindingOdoo(fake, {("res.partner", "name_search"): _addon_name_search},
                       version=version_payload())
    fake.on("GET", "/doc-bearer/res.partner.json", json_reply(200, {"methods": {
        "name_search": {"parameters": {"name": {}, "args": {}, "operator": {}, "limit": {}},
                        "api": ["model", "readonly"]}}}))
    transport = _j2(fake, (19, 0))
    assert transport.execute_kw("db", 2, KEY, "res.partner", "name_search",
                                ["Az", [], "ilike", 5]) == [[1, "Az"]]
    assert _bodies(fake, "/json/2/res.partner/name_search") == [
        {"name": "Az", "domain": [], "operator": "ilike", "limit": 5},
        {"name": "Az", "args": [], "operator": "ilike", "limit": 5}]
    assert odoo.ran == [("res.partner", "name_search",
                         {"name": "Az", "args": [], "operator": "ilike", "limit": 5})]


def test_the_learned_signature_is_used_first_and_corrected_again(fake: FakeOdoo) -> None:
    odoo = BindingOdoo(fake, {("res.partner", "x_convert"): _addon_method},
                       version=version_payload())
    transport = _j2(fake, (19, 0))
    transport._learned[("db", "res.partner", "x_convert")] = Signature(False, ("value", "unit"))
    fake.on("GET", "/doc-bearer/res.partner.json", json_reply(200, {"methods": {
        "x_convert": {"parameters": {"amount": {}, "currency": {}}, "api": []}}}))
    assert transport.execute_kw("db", 2, KEY, "res.partner", "x_convert",
                                [[1], 5, "EUR"]) == "5 EUR"
    assert odoo.ran == [("res.partner", "x_convert", {"amount": 5, "currency": "EUR"})]
    assert transport._learned[("db", "res.partner", "x_convert")].params == (
        "amount", "currency")


def test_names_the_caller_chose_are_reported_not_corrected(fake: FakeOdoo) -> None:
    BindingOdoo(fake, METHODS)
    with pytest.raises(OdooFault, match="check the names in kwargs"):
        _j2(fake).execute_kw("db", 2, KEY, "product.pricelist", "write", [],
                             {"vals": {"name": "X"}}, ids=[1])
    assert len(fake.calls("/json/2/")) == 1


def test_an_uncorrectable_mismatch_asks_for_kwargs(fake: FakeOdoo) -> None:
    BindingOdoo(fake, {("res.partner", "search_read"): _addon_method})  # two names differ
    with pytest.raises(Json2SignatureMismatch, match="pass them by name in kwargs"):
        _j2(fake).execute_kw("db", 2, KEY, "res.partner", "search_read", [[], ["name"]])
    assert len(fake.calls("/json/2/res.partner/")) == 1  # no guess for two names


# --- the fallback: a legacy transport for that call only -----------------------


def _session(fake: FakeOdoo, pref: str = "auto") -> Any:
    settings = Settings(url=fake.url, db="db", login="admin", api_key=KEY,
                        transport_pref=pref, timeout=5)
    return ConnectionManager(settings).default()


def test_odoo_write_on_saas_18_4_goes_through_json2(fake: FakeOdoo) -> None:
    odoo = BindingOdoo(fake, METHODS)
    session = _session(fake)
    out = odoo_write(ToolContext(session=session, manager=None),
                     {"model": "product.pricelist", "ids": [1], "values": {"name": "X"}})
    assert out == {"model": "product.pricelist", "ok": True}
    assert odoo.ran == [("product.pricelist", "write", {"values": {"name": "X"}})]
    assert not fake.calls("/jsonrpc") and not fake.calls("/xmlrpc")


def test_auto_sends_an_uncorrectable_call_over_jsonrpc_and_keeps_json2(
        fake: FakeOdoo, caplog: pytest.LogCaptureFixture) -> None:
    BindingOdoo(fake, {**METHODS, ("res.partner", "search_read"): _addon_method})
    legacy: list[tuple[str, str, list[Any]]] = []

    def jsonrpc(request: dict[str, Any]) -> Any:
        params = request["body"]["params"]
        _db, _uid, _secret, model, method, args, _kwargs = params["args"]
        legacy.append((model, method, args))
        return jsonrpc_result([{"id": 1}])

    fake.on("POST", "/jsonrpc", jsonrpc)
    session = _session(fake)
    with caplog.at_level(logging.WARNING, logger="odoo_mcp.transport"):
        out = session.execute("res.partner", "search_read", [[], ["name"]])
    assert out == [{"id": 1}]
    assert legacy == [("res.partner", "search_read", [[], ["name"]])]
    assert any("did not run" in r.getMessage() for r in caplog.records)
    assert session.transport.active == "json2"  # still pinned
    session.execute("res.company", "write", [[1], {"name": "Y"}])
    assert len(legacy) == 1  # the next call is JSON-2 again


def test_caller_named_kwargs_are_never_sent_to_legacy(fake: FakeOdoo) -> None:
    BindingOdoo(fake, {("res.partner", "x_two"): _addon_method})
    calls: list[Any] = []

    def jsonrpc(request: dict[str, Any]) -> Any:
        calls.append(request["body"]["params"]["args"][4])
        return jsonrpc_result("ok")

    fake.on("POST", "/jsonrpc", jsonrpc)
    session = _session(fake)
    with pytest.raises(OdooFault, match="check the names in kwargs"):
        odoo_execute(ToolContext(session=session, manager=None),
                     {"model": "res.partner", "method": "x_two", "ids": [1],
                      "kwargs": {"value": 1, "unit": "EUR"}})
    assert calls == []  # names chosen by the caller: reported, never sent anywhere else


def test_json2_pref_reports_the_mismatch_without_blaming_the_version(fake: FakeOdoo) -> None:
    BindingOdoo(fake, {("res.partner", "search_read"): _addon_method})
    session = _session(fake, pref="json2")
    with pytest.raises(Json2SignatureMismatch) as info:
        session.execute("res.partner", "search_read", [[], ["name"]])
    assert "saas~18.4 / 19.0 or newer" not in str(info.value)
    assert not fake.calls("/jsonrpc")


# --- an unreachable host is not a version or proxy problem (F5) ----------------


def test_connect_errors_are_unreachable() -> None:
    transport = Json2Transport("http://127.0.0.1:9", timeout=2)
    with pytest.raises(Json2Unreachable) as info:
        transport.execute_kw("db", 2, KEY, "res.partner", "search_count", [[]])
    assert isinstance(info.value, Json2Unavailable)


def test_json2_pref_on_a_down_host_points_at_odoo_url() -> None:
    fb = FallbackTransport("http://127.0.0.1:9", timeout=2, pref="json2", secret_kind="api_key")
    with pytest.raises(TransportError) as info:
        fb.version()
    message = str(info.value)
    assert "ODOO_URL" in message and "reached" in message
    assert "saas~18.4" not in message and "proxy" not in message
    assert KEY not in message


def test_json2_pref_on_a_pre_json2_server_still_gets_the_version_hint(fake: FakeOdoo) -> None:
    fake.on("POST", "/web/webclient/version_info", json_reply(404, {}))
    fake.on("GET", "/json/version", json_reply(404, {}))
    fb = FallbackTransport(fake.url, timeout=5, pref="json2", secret_kind="api_key")
    with pytest.raises(Json2Unavailable, match="saas~18.4 / 19.0 or newer"):
        fb.version()
