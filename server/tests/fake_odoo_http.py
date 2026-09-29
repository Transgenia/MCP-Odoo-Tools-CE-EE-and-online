# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""A scripted Odoo HTTP server for transport tests (JSON-2, JSON-RPC, web probes).

Routes map ``(verb, path)`` (exact) or ``(verb, prefix)`` to a reply, or to a
handler that gets the recorded request and returns ``(status, headers, body)``.
Every request is recorded, so tests can assert what was sent, and that nothing
was sent to ``/jsonrpc`` or ``/xmlrpc``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Union

Reply = tuple[int, dict[str, str], bytes]
Handler = Callable[[dict[str, Any]], Reply]
Route = Union[Reply, Handler]

NOT_FOUND_NODB = (b"<!DOCTYPE html>\n<title>404 Not Found</title>\n<h1>Not Found</h1>\n"
                  b"<p>No database is selected and the requested URL was not found in the "
                  b"server-wide controllers.</p>")

DEBUG_MARKER = "/srv/odoo/secret/traceback_path.py"


def json_reply(status: int, payload: Any, **headers: str) -> Reply:
    return (status, {"Content-Type": "application/json; charset=utf-8", **headers},
            json.dumps(payload).encode())


def html_reply(status: int, text: bytes = b"<html>page</html>", **headers: str) -> Reply:
    return status, {"Content-Type": "text/html; charset=utf-8", **headers}, text


def odoo_error(status: int, name: str, message: str) -> Reply:
    return json_reply(status, {
        "name": name, "message": message, "arguments": [message], "context": {},
        "debug": f"Traceback (most recent call last):\n  File \"{DEBUG_MARKER}\"\n"
                 f"{name}: {message}",
    })


def version_payload(version: str = "19.0-20260926", info: list[Any] | None = None) -> dict:
    info = info if info is not None else [19, 0, 0, "final", 0, ""]
    return {"server_version": version, "server_version_info": info,
            "server_serie": f"{info[0]}.{info[1]}", "protocol_version": 1}


def jsonrpc_result(result: Any) -> Reply:
    return json_reply(200, {"jsonrpc": "2.0", "id": 1, "result": result})


class FakeOdoo:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Route] = {}
        self.prefixes: list[tuple[str, str, Route]] = []
        self.seen: list[dict[str, Any]] = []
        fake = self

        class _H(BaseHTTPRequestHandler):
            def _serve(self, verb: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw
                request = {"verb": verb, "path": self.path, "headers": dict(self.headers),
                           "body": body}
                fake.seen.append(request)
                status, headers, payload = fake._reply(request)
                self.send_response(status)
                for key, value in {"Content-Length": str(len(payload)), **headers}.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                self._serve("POST")

            def do_GET(self) -> None:
                self._serve("GET")

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()

    def _reply(self, request: dict[str, Any]) -> Reply:
        route = self.routes.get((request["verb"], request["path"]))
        if route is None:
            route = next((r for verb, prefix, r in self.prefixes
                          if verb == request["verb"] and request["path"].startswith(prefix)),
                         None)
        if route is None:
            return html_reply(404, b"<html>no route</html>")
        return route(request) if callable(route) else route

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    # -- convenience ------------------------------------------------------
    def on(self, verb: str, path: str, route: Route) -> None:
        self.routes[(verb, path)] = route

    def on_prefix(self, verb: str, prefix: str, route: Route) -> None:
        self.prefixes.append((verb, prefix, route))

    def paths(self) -> list[str]:
        return [r["path"] for r in self.seen]

    def calls(self, prefix: str) -> list[dict[str, Any]]:
        return [r for r in self.seen if r["path"].startswith(prefix)]

    def serve_version(self, version: str = "19.0-20260926",
                      info: list[Any] | None = None) -> None:
        self.on("POST", "/web/webclient/version_info",
                jsonrpc_result(version_payload(version, info)))

    def serve_json2(self, orm: Callable[[str, str, dict[str, Any]], Any] | None = None, *,
                    login: str = "admin", uid: int = 2) -> None:
        """JSON-2 sign-in plus an ORM handler for every other /json/2 call."""

        def dispatch(request: dict[str, Any]) -> Reply:
            _, _, _, model, method = request["path"].split("/", 4)
            body = request["body"] or {}
            if (model, method) == ("res.users", "context_get"):
                return json_reply(200, {"lang": "en_US", "tz": "UTC", "uid": uid})
            if (model, method) == ("res.users", "read") and body.get("fields") == ["login"]:
                return json_reply(200, [{"id": uid, "login": login}])
            result = orm(model, method, body) if orm else None
            return json_reply(200, result)

        self.on_prefix("POST", "/json/2/", dispatch)

    def serve_jsonrpc(self, orm: Callable[[str, str, list[Any], dict[str, Any]], Any] | None
                      = None, *, uid: int = 2, version: dict | None = None) -> None:
        """A legacy /jsonrpc endpoint (common.version/authenticate, object.execute_kw)."""

        def dispatch(request: dict[str, Any]) -> Reply:
            params = request["body"]["params"]
            if params["service"] == "common" and params["method"] == "version":
                return jsonrpc_result(version or version_payload())
            if params["service"] == "common" and params["method"] == "authenticate":
                return jsonrpc_result(uid)
            _db, _uid, _secret, model, method, args, kwargs = params["args"]
            return jsonrpc_result(orm(model, method, args, kwargs) if orm else None)

        self.on("POST", "/jsonrpc", dispatch)
