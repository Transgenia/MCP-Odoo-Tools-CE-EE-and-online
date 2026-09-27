# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""MCP server wiring (stdio), built on the Python standard library only.

The plugin runs ``python3 ${CLAUDE_PLUGIN_ROOT}/server/run_stdio.py`` directly:
no package launcher, no install step and no third-party runtime dependency, so
the code that runs is exactly the readable code shipped in the plugin folder.

The MCP surface this server needs is small, and implemented here: newline-
delimited JSON-RPC 2.0 over stdin/stdout with ``initialize``, ``ping``,
``tools/list`` and ``tools/call`` (plus the ``initialized`` and ``cancelled``
notifications). Tool calls run on one worker thread, in arrival order, so the
reader keeps answering ``ping`` and honouring cancellations while Odoo works,
and sessions/transports never see concurrent use.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, BinaryIO

from . import tools as _tools  # noqa: F401  (import registers all tools)
from .config import Settings
from .errors import CompatError, OdooMcpError
from .observability import Observability
from .registry import ToolContext, ToolDef, registry, validate_arguments
from .telemetry import PLUGIN_VERSION
from .tenancy import ConnectionManager

log = logging.getLogger("odoo_mcp.server")

SERVER_NAME = "odoo-mcp-tools"

# Newest first. A client's version is echoed back when it is supported;
# otherwise the newest one is offered, as the MCP lifecycle spec requires.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def check_readonly(settings: Settings, tool: ToolDef) -> None:
    """Enforce the ODOO_READONLY kill-switch centrally (demos, safe exploration).

    Read-only tools always pass; anything flagged ``read_only=False`` is
    refused before any session or transport is touched.
    """
    if settings.readonly and not tool.read_only:
        raise CompatError(
            f"tool '{tool.name}' is disabled: the server runs with ODOO_READONLY=1",
            remediation="unset ODOO_READONLY and restart for writes, "
            "or use a read-only tool (search/read/fields_get/export/report/preview)",
        )


class _RpcError(Exception):
    """A request that must be answered with a JSON-RPC ``error`` object."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_result(text: str, *, is_error: bool) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _valid_id(value: Any) -> bool:
    """MCP ids are strings or integers (never null, never a bool)."""
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def _is_tool_call(msg: Any) -> bool:
    return isinstance(msg, dict) and msg.get("method") == "tools/call" and "id" in msg


class McpServer:
    """MCP request handling plus the stdio read/write loop."""

    def __init__(
        self,
        settings: Settings,
        manager: ConnectionManager | None = None,
        obs: Observability | None = None,
    ) -> None:
        self.settings = settings
        self.manager = manager or ConnectionManager(settings)
        self.obs = obs or Observability(
            metrics=settings.metrics,
            metrics_port=settings.metrics_port,
            otel_endpoint=settings.otel_endpoint,
        )
        self._out: BinaryIO | None = None
        self._write_lock = threading.Lock()
        self._cancelled: set[Any] = set()
        self._cancel_lock = threading.Lock()

    # ------------------------------------------------------------------ MCP

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": PLUGIN_VERSION},
        }

    def list_tools(self) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                    "annotations": {"readOnlyHint": t.read_only},
                }
                for t in registry.all()
            ]
        }

    def call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments")
        if not isinstance(name, str) or not name:
            raise _RpcError(INVALID_PARAMS, "tools/call requires a tool name")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise _RpcError(INVALID_PARAMS, "tools/call arguments must be an object")
        try:
            tool = registry.get(name)
        except KeyError:
            raise _RpcError(INVALID_PARAMS, f"unknown tool: {name}") from None

        try:
            check_readonly(self.settings, tool)  # disabled tools say so, whatever the args
        except OdooMcpError as exc:
            return _tool_result(str(exc), is_error=True)
        problem = validate_arguments(tool.input_schema, arguments)
        if problem:
            return _tool_result(f"Input validation error: {problem}", is_error=True)

        started = time.monotonic()
        status = "ok"
        try:
            session = self.manager.default()  # stdio = single-tenant from env
            ctx = ToolContext(session=session, manager=self.manager)
            with self.obs.span(name):
                result = tool.handler(ctx, arguments)
            text = json.dumps(result, default=str, ensure_ascii=False)
            return _tool_result(text, is_error=False)
        except OdooMcpError as exc:
            status = "error"
            # Clean, actionable message; the client shows it as a tool error.
            return _tool_result(str(exc), is_error=True)
        except Exception as exc:
            status = "error"
            log.exception("tool %s failed unexpectedly", name)
            return _tool_result(f"internal error in {name}: {exc}", is_error=True)
        finally:
            self.obs.record(name, status, time.monotonic() - started)
            try:
                self.manager.record_tool_call(name)
            except Exception:  # noqa: S110 - counters must never fail a tool call
                pass

    # ------------------------------------------------------------- dispatch

    def handle(self, msg: Any) -> dict[str, Any] | None:
        """Answer one JSON-RPC message; ``None`` for notifications and responses."""
        if not isinstance(msg, dict):
            return _error(None, INVALID_REQUEST, "a JSON-RPC message must be an object")
        if "method" not in msg:
            return None  # a response to a request we never send: ignore
        method = msg["method"]
        is_request = "id" in msg
        msg_id = msg.get("id")
        if is_request and not _valid_id(msg_id):
            return _error(None, INVALID_REQUEST, "id must be a string or an integer")
        if msg.get("jsonrpc") != "2.0" or not isinstance(method, str):
            if is_request:
                return _error(msg_id, INVALID_REQUEST, "invalid JSON-RPC 2.0 message")
            return None
        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            if is_request:
                return _error(msg_id, INVALID_PARAMS, "params must be an object")
            return None

        if not is_request:
            self._notification(method, params)
            return None
        try:
            result = self._request(method, params)
        except _RpcError as exc:
            return _error(msg_id, exc.code, exc.message)
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self.initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return self.list_tools()
        if method == "tools/call":
            return self.call_tool(params)
        raise _RpcError(METHOD_NOT_FOUND, f"method not found: {method}")

    def _notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "notifications/cancelled":
            request_id = params.get("requestId")
            if _valid_id(request_id):
                with self._cancel_lock:
                    self._cancelled.add(request_id)
        # notifications/initialized and anything else need no action.

    # ---------------------------------------------------------------- stdio

    def _write(self, obj: Any) -> None:
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
        # "replace": a lone surrogate echoed back from the input must not kill
        # the write; every valid character is encoded unchanged.
        payload = data.encode("utf-8", "replace") + b"\n"
        with self._write_lock:
            assert self._out is not None
            self._out.write(payload)
            self._out.flush()

    def _was_cancelled(self, msg_id: Any) -> bool:
        if not _valid_id(msg_id):
            return False
        with self._cancel_lock:
            if msg_id in self._cancelled:
                self._cancelled.discard(msg_id)
                return True
            return False

    def _safe_handle(self, msg: Any) -> dict[str, Any] | None:
        """``handle()`` that turns an unexpected exception into -32603."""
        try:
            return self.handle(msg)
        except Exception:
            log.exception("unexpected error while handling a message")
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            if isinstance(msg, dict) and "id" in msg and _valid_id(msg_id):
                return _error(msg_id, INTERNAL_ERROR, "internal error")
            return None

    def _run_tool_call(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if self._was_cancelled(msg_id):
            return  # cancelled while queued: skip the work entirely
        response = self._safe_handle(msg)
        if response is not None and not self._was_cancelled(msg_id):
            self._write_quietly(response)

    def _run_batch(self, batch: list[Any]) -> None:
        replies = []
        for msg in batch:
            if _is_tool_call(msg) and self._was_cancelled(msg.get("id")):
                continue
            reply = self._safe_handle(msg)
            if reply is None or (_is_tool_call(msg) and self._was_cancelled(msg.get("id"))):
                continue
            replies.append(reply)
        if replies:
            self._write_quietly(replies)

    def _write_quietly(self, obj: Any) -> None:
        """Worker-side write: a client that already went away is not an error."""
        try:
            self._write(obj)
        except (BrokenPipeError, ValueError):  # ValueError: stdout already closed
            pass

    def _dispatch(self, raw: bytes, worker: ThreadPoolExecutor) -> None:
        line = raw.strip()
        if not line:
            return
        try:
            msg = json.loads(line.decode("utf-8"))
        except (ValueError, RecursionError) as exc:  # ValueError covers bad UTF-8
            self._write(_error(None, PARSE_ERROR, f"parse error: {type(exc).__name__}"))
            return
        if isinstance(msg, list):  # JSON-RPC batch (MCP 2025-03-26)
            if msg:
                # On the worker, so batched tool calls stay serialized with the rest.
                worker.submit(self._run_batch, msg)
            else:
                self._write(_error(None, INVALID_REQUEST, "empty batch"))
        elif _is_tool_call(msg):
            worker.submit(self._run_tool_call, msg)
        else:
            response = self._safe_handle(msg)
            if response is not None:
                self._write(response)

    def run(self, inp: BinaryIO, out: BinaryIO) -> None:
        """Serve newline-delimited JSON-RPC from ``inp`` to ``out`` until EOF."""
        self._out = out
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="odoo-tool")
        try:
            for raw in inp:
                try:
                    self._dispatch(raw, worker)
                except BrokenPipeError:
                    break  # the client closed our stdout: nothing left to answer
                except Exception:  # one bad message must never stop the server
                    log.exception("unexpected error in the stdio loop")
        finally:
            # Answer every request already received before exiting.
            worker.shutdown(wait=True)


def serve(
    settings: Settings | None = None,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> None:
    settings = settings or Settings.from_env()
    log.info("odoo-mcp-tools %s starting: %s", PLUGIN_VERSION, settings.redacted())
    inp = stdin if stdin is not None else sys.stdin.buffer
    out = stdout if stdout is not None else sys.stdout.buffer
    if stdout is None:
        # stdout is the MCP channel: send any stray print() to stderr instead.
        sys.stdout = sys.stderr
    McpServer(settings).run(inp, out)
