# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Shared fakes for the guarded-session tests (Layer B, design 9.2, 9.3 and 9.4).

``ScriptedSession`` is a raw Odoo session that answers from tables: the field
metadata of a small set of models (what ``fields_get`` returns for ``type`` and
``relation``), the rows the guard's pre-reads and the tools' reads ask for, and
fixed results. It records every call it receives, so a test can show that a
refused call never reached it, and which calls the guard made itself.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from odoo_mcp.compat import EnvFacts
from odoo_mcp.config import Settings
from odoo_mcp.errors import OdooFault
from odoo_mcp.policy.check import CallScope
from odoo_mcp.policy.guard import GuardedSession
from odoo_mcp.policy.loader import load_bytes
from odoo_mcp.policy.model import Policy
from odoo_mcp.registry import registry
from odoo_mcp.server import McpServer

KEY = "K3Y-GUARD-DO-NOT-LEAK-0123456789abcdef"
SEP = " \u2014 "  # CompatError joins a message and its remedy with it
A = "Nothing was sent to Odoo."
B = ("The call was stopped before Odoo ran it: nothing was changed and no record data was "
     "returned.")
NO_WORKAROUND = "do not use another tool to do the same thing."
REASON = "Ticket 4312: reviewed by the owner"

CHAR = {"type": "char"}


def m2o(model: str) -> dict[str, str]:
    return {"type": "many2one", "relation": model}


def o2m(model: str, inverse: str = "") -> dict[str, str]:
    return {"type": "one2many", "relation": model, "relation_field": inverse}


def m2m(model: str) -> dict[str, str]:
    return {"type": "many2many", "relation": model}


FIELDS: dict[str, dict[str, dict[str, str]]] = {
    "res.partner": {
        "id": {"type": "integer"}, "name": CHAR, "email": CHAR, "vat": CHAR,
        "comment": {"type": "text"}, "active": {"type": "boolean"}, "signup_token": CHAR,
        "parent_id": m2o("res.partner"), "child_ids": o2m("res.partner", "parent_id"),
        "user_ids": o2m("res.users", "partner_id"),
        "bank_ids": o2m("res.partner.bank", "partner_id"),
        "category_id": m2m("res.partner.category"), "country_id": m2o("res.country"),
        "company_id": m2o("res.company"), "message_follower_ids": o2m("mail.followers", "res_id"),
        "x_attachment_ids": m2m("ir.attachment"), "properties": {"type": "properties"},
    },
    "res.users": {
        "login": CHAR, "name": CHAR, "partner_id": m2o("res.partner"),
        "groups_id": m2m("res.groups"), "company_ids": m2m("res.company"),
        "api_key_ids": o2m("res.users.apikeys", "user_id"),
    },
    "res.users.apikeys": {"name": CHAR, "user_id": m2o("res.users")},
    "res.groups": {"name": CHAR, "users": m2m("res.users")},
    "res.company": {
        "name": CHAR, "partner_id": m2o("res.partner"), "user_ids": m2m("res.users"),
        "l10n_mx_edi_pac_password": CHAR,
    },
    "res.country": {"name": CHAR, "code": CHAR},
    "res.partner.bank": {"acc_number": CHAR, "partner_id": m2o("res.partner")},
    "res.partner.category": {"name": CHAR},
    "sale.order": {
        "name": CHAR, "note": {"type": "html"}, "state": {"type": "selection"},
        "amount_total": {"type": "monetary"}, "access_token": CHAR,
        "partner_id": m2o("res.partner"), "order_line": o2m("sale.order.line", "order_id"),
        "tag_ids": m2m("crm.tag"),
    },
    "sale.order.line": {
        "name": CHAR, "price_unit": {"type": "float"}, "order_id": m2o("sale.order"),
        "product_id": m2o("product.product"),
    },
    "product.product": {"name": CHAR, "default_code": CHAR},
    "product.template": {"name": CHAR,
                         "product_document_ids": o2m("product.document", "res_id")},
    "product.document": {"name": CHAR, "ir_attachment_id": m2o("ir.attachment")},
    "crm.tag": {"name": CHAR},
    "crm.lead": {"name": CHAR, "partner_id": m2o("res.partner"), "stage_id": m2o("crm.stage"),
                 "expected_revenue": {"type": "monetary"}},
    "crm.stage": {"name": CHAR},
    "payment.transaction": {"reference": CHAR, "amount": {"type": "monetary"},
                            "provider_id": m2o("payment.provider"),
                            "partner_id": m2o("res.partner")},
    "payment.provider": {"name": CHAR, "stripe_secret_key": CHAR},
    "mail.template": {"name": CHAR, "body_html": {"type": "html"},
                      "mail_server_id": m2o("ir.mail_server")},
    "ir.mail_server": {"name": CHAR, "smtp_host": CHAR, "smtp_pass": CHAR},
    "ir.attachment": {"name": CHAR, "res_model": CHAR, "res_id": {"type": "many2one_reference"},
                      "res_field": CHAR, "public": {"type": "boolean"},
                      "datas": {"type": "binary"}, "type": {"type": "selection"}},
    "website.page": {"name": CHAR, "url": CHAR, "arch": {"type": "text"},
                     "view_id": m2o("ir.ui.view")},
    "account.move": {"name": CHAR, "partner_id": m2o("res.partner"),
                     "message_main_attachment_id": m2o("ir.attachment"),
                     "invoice_pdf_report_id": m2o("ir.attachment")},
    "ir.actions.server": {"name": CHAR, "code": {"type": "text"}, "model_id": m2o("ir.model"),
                          "state": {"type": "selection"}},
    "base.automation": {"name": CHAR, "model_id": m2o("ir.model"),
                        "trigger": {"type": "selection"},
                        "action_server_id": m2o("ir.actions.server")},
    "hr.employee": {"name": CHAR, "private_email": CHAR, "work_email": CHAR},
}

# Rows the guard's pre-reads and the tools' reads find, by model and id.
ROWS: dict[str, dict[int, dict[str, Any]]] = {
    "ir.attachment": {
        5: {"id": 5, "name": "key.pem", "res_model": "certificate.key", "res_id": 1,
            "res_field": "content"},
        6: {"id": 6, "name": "notes.txt", "res_model": "res.partner", "res_id": 3,
            "res_field": False},
        7: {"id": 7, "name": "provider.txt", "res_model": "payment.provider", "res_id": 1,
            "res_field": False},
        8: {"id": 8, "name": "orphan.txt", "res_model": False, "res_id": 0, "res_field": False},
        10: {"id": 10, "name": "scan.png", "mimetype": "image/png", "file_size": 10,
             "create_date": "2026-09-01 10:00:00", "type": "binary",
             "res_model": "account.move", "res_id": 7, "res_field": False, "datas": "UE5H"},
        11: {"id": 11, "name": "INV_2026_0001.pdf", "mimetype": "application/pdf",
             "file_size": 300, "create_date": "2026-09-02 10:00:00", "type": "binary",
             "res_model": "account.move", "res_id": 7, "res_field": "invoice_pdf_report_file",
             "datas": "UERG"},
        12: {"id": 12, "name": "other.pdf", "mimetype": "application/pdf", "file_size": 30,
             "create_date": "2026-09-03 10:00:00", "type": "binary",
             "res_model": "account.move", "res_id": 8, "res_field": False, "datas": "T1RI"},
        13: {"id": 13, "name": "secret.bin", "mimetype": "application/octet-stream",
             "file_size": 30, "create_date": "2026-09-03 10:00:00", "type": "binary",
             "res_model": "account.move", "res_id": 7, "res_field": "x_private_key_file",
             "datas": "U0VD"},
    },
    "res.partner": {
        3: {"id": 3, "name": "Acme", "user_ids": [], "email": "info@acme.example",
            "signup_token": "TOKEN-DO-NOT-LEAK", "vat": "XAXX010101000"},
        7: {"id": 7, "name": "Bot user", "user_ids": [4], "email": "bot@example.com"},
        8: {"id": 8, "name": "Customer", "user_ids": [], "email": "c@example.com"},
    },
    "account.move": {
        7: {"id": 7, "name": "INV/2026/0001", "message_main_attachment_id": [10, "scan.png"],
            "invoice_pdf_report_id": [11, "INV_2026_0001.pdf"]},
    },
}


class ScriptedSession:
    """A raw session answering from ``FIELDS``, ``ROWS`` and ``results``."""

    def __init__(self, *, version: int = 17, fields: dict[str, Any] | None = None,
                 rows: dict[str, Any] | None = None, results: dict[Any, Any] | None = None,
                 failing: set[str] | None = None, uid: int = 2, active: str = "json2",
                 json2: bool = True) -> None:
        self.uid = uid
        self._facts = EnvFacts(version=version, edition="community", deployment="onprem",
                               raw_version=f"{version}.0")
        self.fields = {**FIELDS, **(fields or {})}
        self.rows = {model: dict(table) for model, table in {**ROWS, **(rows or {})}.items()}
        self.results = dict(results or {})
        self.failing = set(failing or ())
        self.calls: list[tuple[str, str, Any, Any, Any]] = []
        self.metadata: list[tuple[str, Any]] = []
        self.creds = SimpleNamespace(url="https://gateway:pw@odoo.example", db="db",
                                     login="bot@example.com", secret=KEY, secret_kind="api_key")
        self.transport = SimpleNamespace(active=active, series=(version, 0),
                                         json2_available=json2, transport_notice=None,
                                         secret_kind="api_key",
                                         execute_kw=self._forbidden)
        self.invalidated: list[str] = []

    def _forbidden(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the transport was called directly")

    def facts(self) -> EnvFacts:
        return self._facts

    def version_info(self) -> dict[str, Any]:
        return {"server_version": self._facts.raw_version,
                "server_version_info": [self._facts.version, 0, 0, "final", 0, ""]}

    def module_installed(self, name: str) -> bool:
        return True

    def invalidate_fields(self, model: str) -> None:
        self.invalidated.append(model)

    def fields_get(self, model: str, attributes: Any = None) -> dict[str, Any]:
        self.metadata.append((model, attributes))
        if model in self.failing:
            raise OdooFault(f"AccessError: fields_get on {model}")
        return self.fields.get(model, {})

    def name_get(self, model: str, ids: list[int]) -> list[list[Any]]:
        self.calls.append((model, "name_get", [ids], None, None))
        return [[i, f"{model} {i}"] for i in ids]

    def api_doc(self, model: str) -> Any:
        self.calls.append((model, "api_doc", None, None, None))
        return {"model": model, "methods": {}}

    def execute(self, model: str, method: str, args: Any = None, kwargs: Any = None, *,
                ids: Any = None, transports: Any = None) -> Any:
        self.calls.append((model, method, args, kwargs, ids))
        result = self.results.get((model, method))
        if callable(result):
            return result(args, kwargs, ids)
        if result is not None:
            return result
        if method == "read":
            positional = list(args or [])
            records = ids if ids is not None else (positional.pop(0) if positional else [])
            fields = (kwargs or {}).get("fields") or (positional[0] if positional else None)
            table = self.rows.get(model, {})
            rows = []
            for record in records if isinstance(records, list) else [records]:
                row = table.get(record)
                if row is not None:
                    rows.append({k: v for k, v in row.items() if not fields or k in fields
                                 or k == "id"})
            return rows
        if method in ("search_read", "web_search_read", "read_group", "formatted_read_group"):
            return []
        if method in ("search", "web_read", "name_search", "export_data"):
            return []
        if method in ("create", "copy"):
            return 101
        if method in ("write", "unlink", "load"):
            return True if method != "load" else {"ids": [201], "messages": []}
        return None

    # what the tests read back -------------------------------------------------------
    def sent(self, method: str | None = None) -> list[tuple[str, str]]:
        """The (model, method) of every execute and name_get received."""
        return [(model, m) for model, m, _a, _k, _i in self.calls
                if method is None or m == method]

    def call(self, model: str, method: str) -> tuple[Any, Any, Any]:
        """The (args, kwargs, ids) of the last such call."""
        for m, f, args, kwargs, ids in reversed(self.calls):
            if (m, f) == (model, method):
                return args, kwargs, ids
        raise AssertionError(f"no call {model}.{method}")


def policy(profile: str = "standard", models: dict[str, Any] | None = None, *,
           readonly: bool = False, **document: Any) -> Policy:
    """The policy of a file holding ``models`` (and ``fields``, ``tools``)."""
    body: dict[str, Any] = {"version": 1, **document}
    if models is not None:
        body["models"] = models
    loaded = load_bytes(json.dumps(body).encode("utf-8"), path="/etc/odoo-tools/policy.json",
                        profile=profile, readonly=readonly,
                        tool_names=[t.name for t in registry.all()])
    assert not loaded.locked, loaded.error
    return loaded


def guarded(tool: str, arguments: dict[str, Any], *, p: Policy | None = None,
            session: Any = None, layer_a: bool = True) -> tuple[GuardedSession, CallScope]:
    """The guarded session a call of ``tool`` gets: Layer A first (it must allow
    the call), or, with ``layer_a=False``, the declared touches granted as they are."""
    p = p if p is not None else Policy()
    definition = registry.get(tool)
    if layer_a:
        scope = p.check(definition, arguments)
    else:
        from odoo_mcp.policy.check import scope_for

        scope = scope_for(p, definition, arguments)
    return GuardedSession(session if session is not None else ScriptedSession(), scope), scope


class Manager:
    """A connection manager that hands out one raw session and counts calls."""

    def __init__(self, session: Any = None) -> None:
        self.session = session
        self.built = 0
        self.calls: list[str] = []

    def default(self) -> Any:
        self.built += 1
        if self.session is None:
            raise AssertionError("a session was built")
        return self.session

    def record_tool_call(self, name: str) -> None:
        self.calls.append(name)

    def connections(self) -> list[dict[str, str]]:
        return []

    def tool_calls_snapshot(self) -> dict[str, int]:
        return {}


def server(session: Any = None, *, p: Policy | None = None, **settings: Any) -> McpServer:
    return McpServer(Settings(**settings), manager=Manager(session),  # type: ignore[arg-type]
                     policy=p)


def call(srv: McpServer, tool: str, /, **arguments: Any) -> tuple[bool, str]:
    result = srv.call_tool({"name": tool, "arguments": arguments})
    return result["isError"], result["content"][0]["text"]


def refused(op: str, model: str, rule: str, hint: str, *, profile: str = "standard",
            layer: str = "B", workaround: bool = True) -> str:
    """The exact text of a refused check (design 6.8)."""
    tail = f"; {NO_WORKAROUND}" if workaround else ""
    suffix = B if layer == "B" else A
    return (f"the odoo-tools permission policy refuses '{op}' on '{model}' (profile '{profile}', "
            f"rule {rule}). {suffix}{SEP}{hint}{tail}")
