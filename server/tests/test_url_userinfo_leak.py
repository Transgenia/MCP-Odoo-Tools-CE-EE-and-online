# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""A malformed ODOO_URL never puts its user:pass@ part in an error text or in a log.

``urllib.parse.urlsplit`` refuses a URL whose user information holds a character that
normalizes to a reserved one (a full-width @ or colon, for example) and quotes the whole
network location, password included, in its error. The password of a gateway placed in
ODOO_URL (``https://user:pass@host``, a documented feature) used to reach the model's
context and Claude Code's MCP log that way (product rule 5). The URL cannot be used, so
every transport reports a fixed text instead, and nothing that is left of the URL carries
the password. ASCII URLs were already covered by test_review_followups.py.

A second family needs no odd character: a password written with a raw ``#``, ``/`` or ``?``
(the usual mistake) is not refused by the parser, which just ends the network location
there, so the start of the password reads as a host or a port and http.client quotes it
("nonnumeric port"). Such a URL is unreadable too, and neither a message nor the
connection list (``odoo_connections``) may show any part of it.
"""

from __future__ import annotations

import http.client
import json
import logging
import socket
import traceback
import urllib.parse
from collections.abc import Callable
from typing import Any

import pytest

from odoo_mcp.audit import AuditLog
from odoo_mcp.config import Settings
from odoo_mcp.errors import OdooMcpError
from odoo_mcp.server import McpServer
from odoo_mcp.transport.base import URL_UNREADABLE, hides_user_info
from odoo_mcp.transport.fallback import FallbackTransport
from odoo_mcp.transport.json2 import Json2Transport
from odoo_mcp.transport.jsonrpc import JsonRpcTransport, split_userinfo
from odoo_mcp.transport.xmlrpc import XmlRpcTransport

CANARY = "PW-CANARY-DO-NOT-LEAK"
# Characters whose NFKC form is a reserved URL character, named so no escape is needed.
ODD = {
    "a full-width @": "\N{FULLWIDTH COMMERCIAL AT}",
    "a full-width colon": "\N{FULLWIDTH COLON}",
    "an account-of sign": "\N{ACCOUNT OF}",
}
# The same URLs written as the gateway's user would: the last (ASCII) @ separates the host.
# "only a full-width @" has no ASCII @ at all: normalization alone turns it into the separator.
FORMS = {
    **{name: "https://gateway:{canary}{char}x@odoo.example" for name in ODD},
    "only a full-width @": "https://gateway:{canary}{char}odoo.example",
}
# A password written with a raw reserved character: the parser accepts these URLs and finds
# no user information in them. "tail" is the part of the password after the raw character.
RAW_FORMS = {
    "a raw #": "https://gateway:{canary}#tail@odoo.example",
    "a raw /": "https://gateway:{canary}/tail@odoo.example",
    "a raw ?": "https://gateway:{canary}?tail@odoo.example",
    "no scheme": "gateway:{canary}@odoo.example",
    "no scheme and no user": "{canary}@odoo.example",
    "one slash only": "https:/gateway:{canary}@odoo.example",
    "no colon after the scheme": "https//gateway:{canary}@odoo.example",
}
TRANSPORTS: dict[str, Callable[..., Any]] = {
    "jsonrpc": JsonRpcTransport,
    "json2": Json2Transport,
    "xmlrpc": XmlRpcTransport,
    "fallback": FallbackTransport,
}


@pytest.fixture(params=sorted(FORMS), ids=sorted(FORMS))
def url(request: pytest.FixtureRequest) -> str:
    char = ODD.get(request.param, ODD["a full-width @"])
    candidate = FORMS[request.param].format(canary=CANARY, char=char)
    try:
        urllib.parse.urlsplit(candidate)
    except ValueError:
        return candidate
    pytest.skip("this Python accepts the URL, so its parser has no error text to quote")


@pytest.fixture(params=sorted(RAW_FORMS), ids=sorted(RAW_FORMS))
def raw_url(request: pytest.FixtureRequest) -> str:
    return RAW_FORMS[request.param].format(canary=CANARY)


def everything_shown(exc: BaseException) -> str:
    """Every text an exception can show: itself, its traceback and every exception chained to it."""
    texts: list[str] = []
    seen: set[int] = set()
    todo: list[BaseException | None] = [exc]
    while todo:
        current = todo.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        texts += [str(current), repr(current), repr(current.args)]
        todo += [current.__cause__, current.__context__]
    texts += traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "\n".join(texts)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The URL is refused before any request: a socket opened here is a failure."""
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a socket was opened for a URL that cannot be read")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_the_parser_really_quotes_the_user_info(url: str) -> None:
    # The premise of this file: without the fix, the standard parser's own text is the leak.
    with pytest.raises(ValueError) as info:
        urllib.parse.urlsplit(url)
    assert CANARY in str(info.value)


def test_a_url_the_parser_refuses_is_not_kept_and_cannot_be_requested(url: str) -> None:
    # Stripping the user information and carrying on would send a request to the host
    # without the gateway's credentials: an unreadable URL fails before any request.
    assert split_userinfo(url) == ("", None)
    assert split_userinfo("https://odoo.example") == ("https://odoo.example", None)
    # A malformed URL that cannot hold user information keeps its old behavior: it comes
    # back unchanged and fails later, with nothing secret in the parser's text.
    assert split_userinfo("http://[") == ("http://[", None)
    assert split_userinfo("https://u:p@odoo.example/")[1] is not None  # a readable one still works


@pytest.mark.parametrize("name", sorted(TRANSPORTS))
def test_a_transport_never_quotes_the_user_info(name: str, url: str) -> None:
    with pytest.raises(OdooMcpError) as info:
        TRANSPORTS[name](url, timeout=2).version()
    assert CANARY not in everything_shown(info.value)  # nor in anything chained to it
    assert URL_UNREADABLE in str(info.value) or name == "fallback"


@pytest.mark.parametrize("name", ["jsonrpc", "json2"])
def test_a_transport_object_never_holds_the_user_info(name: str, url: str) -> None:
    transport = TRANSPORTS[name](url, timeout=2)
    assert CANARY not in transport.base_url


def test_the_server_answers_with_a_fixed_error_and_logs_no_password(
        url: str, caplog: pytest.LogCaptureFixture) -> None:
    server = McpServer(Settings(url=url, db="db", login="admin", api_key="k", timeout=2),
                       audit=AuditLog("off"))
    with caplog.at_level(logging.DEBUG):
        result = server.call_tool({"name": "odoo_version", "arguments": {}})
    assert result["isError"] is True
    assert CANARY not in json.dumps(result)
    assert CANARY not in caplog.text
    assert "cannot be read" in result["content"][0]["text"]


# -- a password with a raw #, / or ? ------------------------------------------------------

@pytest.mark.parametrize("form", ["a raw #", "a raw /", "a raw ?"])
def test_http_client_really_quotes_the_start_of_such_a_password(form: str) -> None:
    # The premise: the parser keeps what comes before the raw character as the network
    # location, and http.client quotes it as a port. Without the fix that text was the leak.
    netloc = urllib.parse.urlsplit(RAW_FORMS[form].format(canary=CANARY)).netloc
    with pytest.raises(http.client.InvalidURL) as info:
        http.client.HTTPSConnection(netloc)
    assert CANARY in str(info.value)


def test_the_predicate_tells_unreadable_user_info_from_a_readable_url(raw_url: str) -> None:
    assert hides_user_info(raw_url) is True
    for readable in ("https://odoo.example", "https://odoo.example:8069/odoo",
                     "https://u:p@odoo.example", "https://u@odoo.example/", "http://[",
                     "https://u:p%23q@odoo.example", "https://u:p@q@odoo.example", ""):
        assert hides_user_info(readable) is False, readable


@pytest.mark.parametrize("name", sorted(TRANSPORTS))
def test_a_raw_reserved_character_never_reaches_an_error(name: str, raw_url: str) -> None:
    with pytest.raises(OdooMcpError) as info:
        TRANSPORTS[name](raw_url, timeout=2).version()
    assert CANARY not in everything_shown(info.value)
    assert "tail" not in everything_shown(info.value)
    assert URL_UNREADABLE in str(info.value) or name == "fallback"


def test_the_connection_list_and_the_logs_show_nothing_of_such_a_url(
        raw_url: str, caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(url=raw_url, db="db", login="admin", api_key="k", timeout=2)
    shown = [json.dumps(settings.redacted()), repr(settings), str(settings)]
    server = McpServer(settings, audit=AuditLog("off"))
    with caplog.at_level(logging.DEBUG):
        for tool, arguments in (("odoo_connections", {}), ("odoo_version", {}),
                                ("odoo_search", {"model": "res.partner"})):
            result = server.call_tool({"name": tool, "arguments": arguments})
            shown.append(json.dumps(result))
    shown.append(caplog.text)
    for text in shown:
        assert CANARY not in text
        assert "tail" not in text
        assert "gateway" not in text


@pytest.mark.parametrize("url", ["https://odoo.example/@me", "https://odoo.example/?next=a@b.example",
                                 "https://odoo.example/#a@b"])
def test_an_at_sign_after_the_host_is_refused_on_purpose(url: str) -> None:
    # The test is wide: with no readable user:pass@ part, an @ in the path, the query or the
    # fragment cannot be told from a password cut short by a raw /, ? or #. An Odoo base URL
    # has no use for one (SECURITY.md says so).
    assert hides_user_info(url) is True
    assert split_userinfo(url) == ("", None)
    assert Settings(url=url).redacted()["url"] == "<unparseable ODOO_URL>"


def test_a_readable_gateway_url_still_works_and_stays_hidden() -> None:
    # The fix must not take away the documented feature: https://user:pass@host in ODOO_URL.
    good = f"https://gateway:{CANARY}@odoo.example"
    assert hides_user_info(good) is False
    url, auth = split_userinfo(good)
    assert url == "https://odoo.example" and auth is not None
    settings = Settings(url=good, db="db", login="admin", api_key="k")
    assert settings.redacted()["url"] == "https://odoo.example"
    assert CANARY not in repr(settings)
    # A password with the reserved characters written as %XX, as the error text asks for.
    encoded = "https://gateway:p%23a%2Fb%3Fc@odoo.example"
    assert hides_user_info(encoded) is False
    assert split_userinfo(encoded)[0] == "https://odoo.example"
