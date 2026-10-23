# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Every tool's permission mapping, checked so a new tool or a wrong mapping cannot
bypass the policy (design 9.2, #1 to #5).

1. A missing mapping fails three ways: at the decorator, at ``register()``, and,
   for a definition placed in the registry by hand, when it is listed or called.
2. ``GOLDEN`` holds one sample call per tool with the touches Layer A derives;
   a new tool without a row fails here.
3. ``read_only`` agrees with the declared operations, so ``check_readonly`` and
   the policy never disagree about which tools write.
4. An AST scan of ``tools/*.py``: every model a handler passes to the session is
   declared (fixed, internal, or the agent's own ``model``), and every declared
   one is used.
5. An AST scan for what a tool must never reach: the transport, the secret, the
   connection manager's sessions, introspection that could get around them.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

import odoo_mcp.tools as tools_package
from odoo_mcp.config import Settings
from odoo_mcp.policy.check import FIELD_ARGUMENTS, execute_touches, touches_for
from odoo_mcp.policy.classify import method_ops, valid_method, valid_model
from odoo_mcp.policy.model import Policy, model_aliases
from odoo_mcp.policy.tiers import WRITE_OPERATIONS
from odoo_mcp.registry import (
    NO_MODEL,
    Access,
    ToolDef,
    ToolRegistry,
    obj,
    registry,
    validate_arguments,
)
from odoo_mcp.server import McpServer

TOOLS_DIR = Path(tools_package.__file__).parent
TOOLS = registry.all()

# tool -> (sample arguments, the touches Layer A derives from them)
GOLDEN: dict[str, tuple[dict[str, Any], list[str]]] = {
    "odoo_version": ({}, []),
    "odoo_connections": ({}, []),
    "odoo_telemetry_preview": ({}, []),
    "odoo_list_models": ({"like": "partner", "limit": 20}, ["read:ir.model"]),
    "odoo_module_info": ({"name": "sale"}, ["read:ir.module.module"]),
    "odoo_fields_get": ({"model": "res.partner", "attributes": ["type"]},
                        ["inspect:res.partner"]),
    "odoo_search": ({"model": "res.partner", "domain": [["is_company", "=", True]],
                     "limit": 5}, ["read:res.partner"]),
    "odoo_search_count": ({"model": "res.partner"}, ["read:res.partner"]),
    "odoo_read": ({"model": "res.partner", "ids": [1], "fields": ["name"]}, ["read:res.partner"]),
    "odoo_search_read": ({"model": "sale.order", "domain": [["state", "=", "sale"]],
                          "fields": ["name", "amount_total"], "order": "name"},
                         ["read:sale.order"]),
    "odoo_read_group": ({"model": "crm.lead", "fields": ["stage_id", "expected_revenue:sum"],
                         "groupby": ["stage_id"]}, ["read:crm.lead"]),
    "odoo_export_records_json": ({"model": "res.partner", "fields": ["name"]},
                                 ["read:res.partner"]),
    "odoo_export_records_csv": ({"model": "res.partner", "fields": ["name"]},
                                ["read:res.partner"]),
    "odoo_translate_get": ({"model": "product.template", "id": 1, "field": "name",
                            "lang": "es_MX"}, ["read:product.template"]),
    "odoo_api_catalog": ({"model": "res.partner"}, ["inspect:res.partner"]),
    "odoo_access_check": ({"model": "sale.order"}, ["inspect:sale.order"]),
    "odoo_record_documents": ({"model": "account.move", "res_id": 7},
                              ["read:account.move", "read:ir.attachment"]),
    "odoo_online_profile": ({}, ["read:res.users", "read:res.company", "read:res.users.apikeys",
                                "read:ir.module.module", "inspect:res.partner"]),
    "odoo_report": ({"report_name": "account.report_invoice", "ids": [1]}, []),
    "odoo_create": ({"model": "res.partner", "values": {"name": "Acme"}},
                    ["create:res.partner"]),
    "odoo_write": ({"model": "res.partner", "ids": [1], "values": {"phone": "555"}},
                   ["write:res.partner"]),
    "odoo_unlink": ({"model": "res.partner", "ids": [1]}, ["unlink:res.partner"]),
    "odoo_translate_set": ({"model": "product.template", "id": 1, "field": "name",
                            "lang": "es_MX", "value": "Silla"}, ["write:product.template"]),
    "odoo_import_preview": ({"model": "res.partner", "fields": ["name", "email"],
                             "rows": [["Acme", "info@example.com"]]},
                            ["create:res.partner", "write:res.partner"]),
    "odoo_import": ({"model": "res.partner", "fields": ["name", "country_id/id"],
                     "rows": [["Acme", "base.mx"]]},
                    ["create:res.partner", "write:res.partner"]),
    "odoo_add_field": ({"model": "res.partner", "name": "x_tier", "label": "Tier",
                        "field_type": "many2one", "relation": "res.country"},
                       ["schema:res.partner", "inspect:res.country"]),
    "odoo_add_automation": ({"model": "crm.lead", "name": "Flag",
                             "code": "records.write({'priority': '1'})"},
                            ["schema:crm.lead", "create:base.automation",
                             "create:ir.actions.server"]),
    "odoo_execute": ({"model": "sale.order", "method": "action_confirm", "ids": [1]},
                     ["call:sale.order:action_confirm"]),
}

WRITE_TOOLS = {"odoo_create", "odoo_write", "odoo_unlink", "odoo_translate_set",
               "odoo_import_preview", "odoo_import", "odoo_add_field", "odoo_add_automation",
               "odoo_execute"}
# Design 6.7: which write tools may overwrite or delete.
DESTRUCTIVE = {"odoo_write": True, "odoo_unlink": True, "odoo_execute": True,
               "odoo_import": True, "odoo_translate_set": True, "odoo_add_automation": True,
               "odoo_create": False, "odoo_add_field": False, "odoo_import_preview": False}


class _Manager:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.built = 0

    def default(self) -> object:
        self.built += 1
        return object()

    def record_tool_call(self, name: str) -> None:
        self.calls.append(name)


# --- 1. a missing mapping fails three ways ------------------------------------------

def test_the_decorator_requires_access() -> None:
    with pytest.raises(TypeError, match="access"):
        ToolRegistry().tool("t_new", "new", obj({}))  # type: ignore[call-arg]


def test_register_refuses_a_tool_without_a_mapping() -> None:
    expected = ("tool 't_new' has no permission mapping: pass access=... to registry.tool "
                "(docs/policy.md#tool-mapping)")
    with pytest.raises(ValueError) as info:
        ToolRegistry().register(ToolDef("t_new", "new", obj({}), lambda ctx, args: None))
    assert str(info.value) == expected
    with pytest.raises(ValueError, match=re.escape(expected)):
        ToolRegistry().tool("t_new", "new", obj({}), access=None)(  # type: ignore[arg-type]
            lambda ctx, args: None)
    ok = ToolRegistry()
    ok.tool("t_new", "new", obj({}), access=NO_MODEL)(lambda ctx, args: None)
    assert ok.get("t_new").access is NO_MODEL


def test_a_tool_placed_by_hand_without_a_mapping_is_hidden_and_refused(
        monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    monkeypatch.setitem(registry._tools, "t_raw", ToolDef(
        "t_raw", "raw", {"type": "object"}, lambda ctx, args: ran.append("ran")))
    manager = _Manager()
    for profile in ("readonly", "standard", "builder", "full"):
        server = McpServer(Settings(policy_profile=profile), manager=manager)  # type: ignore[arg-type]
        assert "t_raw" not in {t["name"] for t in server.list_tools()["tools"]}
        result = server.call_tool({"name": "t_raw", "arguments": {}})
        assert result["isError"] is True
        assert result["content"][0]["text"] == (
            "internal error: tool 't_raw' has no permission mapping, so it is refused (fail "
            "closed)")
    assert ran == [] and manager.built == 0 and manager.calls == []


# --- 2. the golden table ---------------------------------------------------------------

def test_the_golden_table_has_one_row_per_tool() -> None:
    assert len(TOOLS) == 28
    assert set(GOLDEN) == {tool.name for tool in TOOLS}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_golden_arguments_are_valid_calls(name: str) -> None:
    tool = registry.get(name)
    assert validate_arguments(tool.input_schema, GOLDEN[name][0]) is None


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_golden_touches(name: str) -> None:
    tool = registry.get(name)
    arguments, expected = GOLDEN[name]
    assert [str(touch) for touch in touches_for(tool, arguments)] == expected
    # Layer A grants them as declared under the profile that refuses nothing but NEVER.
    scope = Policy(profile_name="full").check(tool, arguments)
    assert scope.touch_strings() == expected
    assert scope.tool == name


@pytest.mark.parametrize(("method", "expected"), [
    ("action_confirm", ["call:sale.order:action_confirm"]),
    ("unlink", ["call:sale.order:unlink", "unlink:sale.order"]),
    ("write", ["call:sale.order:write", "write:sale.order"]),
    ("copy", ["call:sale.order:copy", "create:sale.order"]),
    ("search_read", ["call:sale.order:search_read", "read:sale.order"]),
    ("fields_get", ["call:sale.order:fields_get", "inspect:sale.order"]),
    ("load", ["call:sale.order:load", "create:sale.order", "write:sale.order"]),
    ("message_post", ["call:sale.order:message_post"]),
    ("_private", ["call:sale.order:_private"]),
])
def test_odoo_execute_touches_follow_the_method_class(method: str, expected: list[str]) -> None:
    touches = execute_touches({"model": "sale.order", "method": method})
    assert [str(touch) for touch in touches] == expected


# --- 3. read_only agrees with the declared operations ----------------------------------

@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
def test_read_only_agrees_with_the_declared_operations(tool: ToolDef) -> None:
    access = tool.access
    assert isinstance(access, Access)
    ops = set(access.arg_ops) | {op for op, _model in access.fixed} | {
        op for op, _argument in access.optional}
    internal_ops = {op for internal in access.internal for method in internal.methods
                    for op in method_ops(method)}
    if tool.read_only:
        assert ops <= {"read", "inspect"}, tool.name
        assert internal_ops <= {"read", "inspect"}, tool.name  # no write-class internal
        assert access.dynamic is None and access.columns_arg is None
        assert tool.destructive is None
    else:
        assert ops & WRITE_OPERATIONS or access.dynamic is not None, tool.name
        assert tool.destructive is DESTRUCTIVE[tool.name]
    assert (not tool.read_only) is (tool.name in WRITE_TOOLS)


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
def test_declarations_name_real_arguments_and_models(tool: ToolDef) -> None:
    access = tool.access
    assert access is not None
    properties = tool.input_schema.get("properties", {})
    if access.arg_ops or access.dynamic is not None:
        assert "model" in tool.input_schema.get("required", []), tool.name
    for op, model in access.fixed:
        assert valid_model(model) and op in ("read", "create", "write", "unlink", "call",
                                              "schema", "inspect")
    for _op, argument in access.optional:
        assert argument in properties
    if access.columns_arg is not None:
        assert access.columns_arg in properties
    assert not (access.stub and (access.arg_ops or access.fixed or access.dynamic))


@pytest.mark.parametrize("tool", TOOLS, ids=lambda tool: tool.name)
def test_internals_have_a_reason_and_never_reach_never(tool: ToolDef) -> None:
    full = Policy(profile_name="full")
    for internal in tool.access.internal:  # type: ignore[union-attr]
        assert internal.reason, (tool.name, internal)
        assert internal.methods and all(valid_method(m) for m in internal.methods)
        models = ({"base.automation", "base.action.rule"} if internal.model == "$automation"
                  else {internal.model})
        for model in models:
            assert valid_model(model), internal.model
            for method in internal.methods:
                for op in {"call", *method_ops(method)}:
                    decision = full.decide(op, model, method if op == "call" else None)
                    assert not decision.rule.startswith("never:"), (tool.name, model, method)


def test_every_argument_of_every_tool_is_classified() -> None:
    # A new argument that names fields must be read by Layer A (FIELD_ARGUMENTS, or an
    # import's columns_arg); any other must be listed here, so the choice is made.
    not_fields = {
        "model", "ids", "id", "limit", "offset", "lazy", "lang", "value", "like",
        "attributes", "name", "method", "args", "kwargs", "operations", "res_id",
        "attachment_id", "include_content", "max_bytes", "rows", "label", "field_type",
        "relation", "selection", "required", "help", "code", "trigger", "report_name",
        # field names of other models in a schema change, not data a call reads
        "relation_field", "currency_field",
    }
    for tool in TOOLS:
        for name in tool.input_schema.get("properties", {}):
            assert (name in FIELD_ARGUMENTS or name == tool.access.columns_arg  # type: ignore[union-attr]
                    or name in not_fields), (tool.name, name)


@pytest.mark.parametrize(("profile", "listed"), [
    ("readonly", 19), ("standard", 25), ("builder", 28), ("full", 28)])
def test_the_real_mappings_list_what_the_design_says(profile: str, listed: int) -> None:
    p = Policy(profile_name=profile)
    assert sum(p.tool_visible(tool) for tool in TOOLS) == listed
    assert sum(Policy(profile_name=profile, readonly=True).tool_visible(tool)
               for tool in TOOLS) == 19


# --- 4. the AST scan: every model a handler reaches is declared -------------------------

SESSION_CALLS = {"execute", "fields_get", "name_get", "api_doc"}
# A variable the code passes as the model of an internal call with a "$" model.
NAME_ALIASES = {"automation_model": "$automation"}
DOLLAR = {"$automation": {"base.automation", "base.action.rule"}}


def _module_functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _tool_name(fn: ast.FunctionDef) -> str | None:
    for decorator in fn.decorator_list:
        if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool" and decorator.args
                and isinstance(decorator.args[0], ast.Constant)):
            return str(decorator.args[0].value)
    return None


def _model_arguments(fn: ast.FunctionDef, functions: dict[str, ast.FunctionDef],
                     seen: set[str]) -> list[ast.expr]:
    """The model expression of every session call the function makes, helpers included."""
    found: list[ast.expr] = []
    for statement in fn.body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in SESSION_CALLS:
                assert node.args, f"{fn.name}: {func.attr}() without a model"
                found.append(node.args[0])
            elif isinstance(func, ast.Name) and func.id == "_field_names":
                found.append(node.args[1])
            elif isinstance(func, ast.Name) and func.id in functions and func.id not in seen:
                seen.add(func.id)
                found.extend(_model_arguments(functions[func.id], functions, seen))
    return found


def _scan(source: str) -> dict[str, list[ast.expr]]:
    tree = ast.parse(source)
    functions = _module_functions(tree)
    out = {}
    for fn in functions.values():
        name = _tool_name(fn)
        if name is not None:
            out[name] = _model_arguments(fn, functions, {fn.name})
    return out


def _check_models(tool: ToolDef, expressions: list[ast.expr]) -> list[str]:
    """The problems of one handler's model expressions against its mapping."""
    access = tool.access
    assert access is not None
    declared = {model for _op, model in access.fixed} | {i.model for i in access.internal}
    used: set[str] = set()
    problems = []
    for node in expressions:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            used.add(node.value)
            if node.value not in declared:
                problems.append(f"{tool.name}: '{node.value}' is not declared")
        elif isinstance(node, ast.Name) and node.id == "model":
            if not (access.arg_ops or access.dynamic is not None):
                problems.append(f"{tool.name}: uses the agent's model without arg_ops")
        elif isinstance(node, ast.Name) and node.id in NAME_ALIASES:
            used.add(NAME_ALIASES[node.id])
            if NAME_ALIASES[node.id] not in declared:
                problems.append(f"{tool.name}: {node.id} matches no Internal")
        else:
            problems.append(f"{tool.name}: a model expression the scan cannot verify "
                            f"({ast.dump(node)[:60]})")
    expanded = used | {model for alias in used & set(DOLLAR) for model in DOLLAR[alias]}
    problems.extend(f"{tool.name}: declares '{model}' but never calls it"
                    for model in sorted(declared - expanded))
    return problems


def test_every_model_a_handler_reaches_is_declared() -> None:
    scanned: dict[str, list[ast.expr]] = {}
    for path in sorted(TOOLS_DIR.glob("*.py")):
        scanned.update(_scan(path.read_text(encoding="utf-8")))
    assert set(scanned) == {tool.name for tool in TOOLS}
    problems = [problem for name, expressions in scanned.items()
                for problem in _check_models(registry.get(name), expressions)]
    assert problems == []


def test_the_model_scan_catches_an_undeclared_call() -> None:
    bad = '''
@registry.tool("odoo_version", "x", obj({}), access=NO_MODEL)
def handler(ctx, args):
    helper(ctx)
    return ctx.session.execute(other_name, "read", [])

def helper(ctx):
    ctx.session.fields_get("res.users")
    ctx.session.execute("res.partner", "unlink", [[1]])
'''
    expressions = _scan(bad)["odoo_version"]
    tool = ToolDef("odoo_version", "x", obj({}), lambda c, a: None,
                   access=registry.get("odoo_version").access)
    problems = _check_models(tool, expressions)
    assert any("'res.partner' is not declared" in p for p in problems)
    assert any("cannot verify" in p for p in problems)
    assert not any("'res.users' is not declared" in p for p in problems)  # the W10 internal


# --- 5. the AST scan: what a tool must never reach ----------------------------------------

FORBIDDEN_ATTRIBUTES = {"execute_kw", "secret", "__dict__", "__class__"}
FORBIDDEN_MODULES = ("odoo_mcp.session", "odoo_mcp.tenancy", "odoo_mcp.transport")
ALLOWED_MODULES = {"odoo_mcp.transport.json2_signatures"}


def _imported(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        base = {0: "", 1: "odoo_mcp.tools", 2: "odoo_mcp"}.get(node.level, "?")
        if node.module:
            return [f"{base}.{node.module}".lstrip(".")]
        return [f"{base}.{alias.name}" for alias in node.names]
    return []


def _forbidden(source: str) -> list[str]:
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES:
                problems.append(f"attribute {node.attr}")
            receiver = node.value
            if node.attr in ("default", "get") and (
                    (isinstance(receiver, ast.Attribute) and receiver.attr == "manager")
                    or (isinstance(receiver, ast.Name) and receiver.id == "manager")):
                problems.append(f"manager.{node.attr}")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("getattr", "setattr", "delattr", "hasattr")):
            name = node.args[1] if len(node.args) > 1 else None
            if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                problems.append(f"{node.func.id} with a computed name")
            elif name.value in FORBIDDEN_ATTRIBUTES:
                problems.append(f"{node.func.id} {name.value}")
        for module in _imported(node):
            if module.startswith(FORBIDDEN_MODULES) and module not in ALLOWED_MODULES:
                problems.append(f"import {module}")
    return problems


def test_no_tool_reaches_the_transport_the_secret_or_a_session() -> None:
    problems = {path.name: _forbidden(path.read_text(encoding="utf-8"))
                for path in sorted(TOOLS_DIR.glob("*.py"))}
    assert {name: found for name, found in problems.items() if found} == {}


@pytest.mark.parametrize("snippet", [
    "ctx.session.transport.execute_kw('db', 1, 'k', 'res.partner', 'read', [])",
    "key = ctx.session.creds.secret",
    "ctx.manager.default()",
    "manager.get(creds)",
    "x = ctx.session.__dict__",
    "y = ctx.session.__class__",
    "getattr(ctx.session, name)",
    "getattr(ctx.session.creds, 'secret')",
    "from ..session import OdooSession",
    "from ..tenancy import ConnectionManager",
    "from ..transport.json2 import Json2Transport",
    "from .. import session",
    "import odoo_mcp.transport.fallback",
])
def test_the_forbidden_scan_catches(snippet: str) -> None:
    assert _forbidden(snippet)


def test_the_forbidden_scan_allows_the_signature_table() -> None:
    assert _forbidden("from ..transport.json2_signatures import SIGNATURES") == []
    assert _forbidden("getattr(ctx.session, 'transport', None)") == []


def test_aliases_of_declared_models_are_the_compat_renames() -> None:
    # The agent's model is decided with its alias closure before resolve_model runs,
    # so the name Odoo receives is always one the decision covered.
    from odoo_mcp.compat.deltas import MODEL_RENAMES

    for rename in MODEL_RENAMES:
        assert rename.new in model_aliases(rename.old) and rename.old in model_aliases(rename.new)
