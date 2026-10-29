# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
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

Every call passes the permission policy (``odoo_mcp.policy``) before a session
exists: the read-only kill-switch first, then the tool itself (a tool the
policy forbids everywhere is not listed, and is refused when called by name),
then the arguments' schema, then Layer A, which decides what the tool declares
it touches from the arguments alone. A refusal there never signs in, never
opens a transport and is not counted as a call.

Then the handler runs with a guarded session (Layer B, ``policy/guard.py``), the
only session it gets: every Odoo call it makes is checked, with its values and
paths, before the transport is touched, and withheld fields are removed from
what reads return (the result names them in ``policy_withheld_fields``).

Every ``tools/call`` of a known tool leaves one audit line (``odoo_mcp.audit``),
refusals included, at whichever step it ends: names and counts only, never a
value, a domain, an id or a secret.

The local diagnostics (``odoo_mcp.diagnostics``, off unless ODOO_DIAG_DIR names a
folder) note the lifecycle for support, metadata only: ``start`` when ``serve``
starts, ``connect`` after the first tool call that reached a connection outcome,
``crash`` for an unexpected exception, and ``stop`` with the call and error counts
when the stdio loop ends. They never change what a tool does or answers.
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
from .audit import AuditLog
from .config import Settings
from .diagnostics import Diagnostics
from .errors import (
    AuthError,
    CompatError,
    ConfigError,
    OdooMcpError,
    PolicyError,
    TransportError,
)
from .observability import Observability
from .policy import Policy
from .policy.guard import GuardedSession, ManagerView
from .policy.texts import description_suffix, instructions_line
from .registry import ToolContext, ToolDef, registry, validate_arguments
from .support import INSTRUCTIONS, SETUP_HINT, SUPPORT_LINE
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


def _with_guidance(exc: OdooMcpError) -> str:
    """Connection problems also say where to fix them and who can help."""
    text = str(exc)
    if isinstance(exc, (ConfigError, AuthError, TransportError)):
        text = f"{text}\n{SETUP_HINT}\n{SUPPORT_LINE}"
    return text


def check_readonly(settings: Settings, tool: ToolDef) -> None:
    """Enforce the ODOO_READONLY kill-switch centrally (demos, safe exploration).

    Read-only tools always pass; anything flagged ``read_only=False`` is
    refused before any session or transport is touched.
    """
    if settings.readonly and not tool.read_only:
        raise CompatError(
            f"tool '{tool.name}' is disabled: the server runs with ODOO_READONLY=1",
            remediation="unset ODOO_READONLY and restart for writes, or use a read-only "
            "tool (search/read/fields_get/export/report/odoo_online_profile/"
            "odoo_access_check)",
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


def _annotations(tool: ToolDef) -> dict[str, Any]:
    """``readOnlyHint`` as declared. A write tool also states ``destructiveHint``,
    which MCP otherwise assumes true. Hints for the client, never enforcement."""
    hints: dict[str, Any] = {"readOnlyHint": tool.read_only}
    if not tool.read_only:
        hints["destructiveHint"] = True if tool.destructive is None else bool(tool.destructive)
    return hints


def _takes_model(tool: ToolDef) -> bool:
    return "model" in (tool.input_schema.get("properties") or {})


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
        policy: Policy | None = None,
        audit: AuditLog | None = None,
        diagnostics: Diagnostics | None = None,
    ) -> None:
        self.settings = settings
        # Read once, here: the policy is fixed for the life of the process (a
        # change needs a reconnect). It never raises; a bad one is locked.
        self.policy = policy if policy is not None else Policy.from_settings(
            settings, [tool.name for tool in registry.all()])
        self.manager = manager or ConnectionManager(settings)
        # One line per tool call; serve() writes the start line.
        self.audit = audit if audit is not None else AuditLog.from_settings(settings)
        # Metadata for support (ODOO_DIAG_DIR); serve() writes start and stop.
        self.diag = diagnostics if diagnostics is not None else Diagnostics.from_settings(
            settings)
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
        line = instructions_line(self.policy, registry.all())
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": PLUGIN_VERSION},
            "instructions": f"{INSTRUCTIONS}\n{line}\n",
        }

    def list_tools(self) -> dict[str, Any]:
        # Only what the policy may allow somewhere, as a read-only consent hides
        # write tools: a listed tool can still be refused for a given model.
        suffix = description_suffix(self.policy)
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description + (suffix if _takes_model(t) else ""),
                    "inputSchema": t.input_schema,
                    "annotations": _annotations(t),
                }
                for t in registry.all()
                if self.policy.tool_visible(t)
            ]
        }

    def _needs_session(self, tool: ToolDef) -> bool:
        """A stub never calls Odoo, and a locked odoo_version answers without it."""
        if tool.access is not None and tool.access.stub:
            return False
        return not (self.policy.locked and tool.name == "odoo_version")

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
            self.audit.refused(name, exc, layer="tool", rule="readonly", policy=self.policy)
            self.diag.tool_call(category="policy")
            return _tool_result(str(exc), is_error=True)
        try:
            self.policy.check_tool(tool)  # locked, unmapped, disabled or hidden: the same
        except OdooMcpError as exc:
            self.audit.refused(name, exc, layer="tool", policy=self.policy)
            self.diag.tool_call(category="policy")
            return _tool_result(str(exc), is_error=True)
        problem = validate_arguments(tool.input_schema, arguments)
        if problem:
            self.audit.call(name, policy=self.policy, status="invalid")
            self.diag.tool_call(category="other")
            return _tool_result(f"Input validation error: {problem}", is_error=True)
        try:
            scope = self.policy.check(tool, arguments)  # Layer A: the arguments alone
        except PolicyError as exc:
            self.audit.refused(name, exc, layer="A", policy=self.policy)
            self.diag.tool_call(category="policy")
            return _tool_result(str(exc), is_error=True)
        except Exception as exc:
            log.exception("the permission policy could not check a call of %s", name)
            self.audit.call(name, policy=self.policy, status="error", exc=exc, layer="A",
                            rule="internal", decision="deny")
            self.diag.crash(exc, "policy")
            self.diag.tool_call(category="other")
            return _tool_result(
                f"internal error: the odoo-tools permission policy could not check this {name} "
                "call, so it was refused (fail closed). Nothing was sent to Odoo.",
                is_error=True)

        started = time.monotonic()
        status = "ok"
        failure: BaseException | None = None
        raw = None
        try:
            # stdio = single-tenant from env
            raw = self.manager.default() if self._needs_session(tool) else None
            # Layer B: the handler gets only the guarded session, which checks every
            # Odoo call against the policy before the transport is touched.
            session = GuardedSession(raw, scope) if raw is not None else None
            ctx = ToolContext(session=session, manager=ManagerView(self.manager),
                              policy=self.policy)
            with self.obs.span(name):
                result = tool.handler(ctx, arguments)
            text = json.dumps(scope.annotate(result), default=str, ensure_ascii=False)
            return _tool_result(text, is_error=False)
        except PolicyError as exc:  # Layer B: an actual Odoo call was refused
            status, failure = "refused", exc
            return _tool_result(str(exc), is_error=True)
        except OdooMcpError as exc:
            status, failure = "error", exc
            # Clean, actionable message; the client shows it as a tool error.
            return _tool_result(_with_guidance(exc), is_error=True)
        except Exception as exc:
            status, failure = "error", exc
            log.exception("tool %s failed unexpectedly", name)
            self.diag.crash(exc, "tool")
            return _tool_result(f"internal error in {name}: {exc}", is_error=True)
        finally:
            elapsed = time.monotonic() - started
            # Layer B refusals carry their own layer and rule; the class name only of
            # any other error, never its message (an Odoo fault can echo values).
            self.audit.call(name, policy=self.policy, status=status, scope=scope,
                            exc=failure, seconds=elapsed)
            self.obs.record(name, status, elapsed)
            try:
                self.manager.record_tool_call(name)
            except Exception:  # noqa: S110 - counters must never fail a tool call
                pass
            # Never raise (a raise here would replace the answer), never contact Odoo.
            self.diag.tool_call(failure)
            self.diag.connection(raw, failure)

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
        except Exception as exc:
            log.exception("unexpected error while handling a message")
            self.diag.crash(exc, "request")
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
                except Exception as exc:  # one bad message must never stop the server
                    log.exception("unexpected error in the stdio loop")
                    self.diag.crash(exc, "loop")
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
    # First, so a failure while starting still leaves a crash and a stop line.
    diag = Diagnostics.from_settings(settings)
    try:
        inp = stdin if stdin is not None else sys.stdin.buffer
        out = stdout if stdout is not None else sys.stdout.buffer
        if stdout is None:
            # stdout is the MCP channel: send any stray print() to stderr instead.
            sys.stdout = sys.stderr
        server = McpServer(settings, diagnostics=diag)
        log_policy(server.policy)
        log.info("audit: %s", server.audit.describe())
        log.info("diagnostics: %s", diag.describe())
        server.audit.start(settings, server.policy)
        diag.start(settings, server.policy, server.audit.mode)
        server.run(inp, out)
    except Exception as exc:
        diag.crash(exc, "serve")
        raise
    finally:
        diag.stop()  # the end of input, a crash or an interrupt


def log_policy(policy: Policy) -> None:
    """The startup line of the permission policy: its digest, or why it is locked."""
    if policy.locked:
        log.error("permission policy locked (%s): %s; every Odoo tool except odoo_version is "
                  "disabled", policy.error_code, policy.error)
        return
    warnings = ",".join(code for code, _text in policy.warnings) or "none"
    log.info("permission policy: profile %s, digest %s, file %s, read-only %s, warnings %s",
             policy.profile_name, policy.digest, policy.source or "none", policy.readonly,
             warnings)
