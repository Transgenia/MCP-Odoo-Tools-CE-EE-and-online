# SPDX-License-Identifier: MIT
"""Offline MCP test double for the directory plugin's read-only connection check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

CATALOGS = {
    "connected": ("odoo_version",),
    "alternate": ("instance_metadata",),
    "disconnected": (),
    "ambiguous": ("north_odoo_version", "south_odoo_version"),
    "denied": ("odoo_version",),
    "unsupported": ("count_orders",),
}


def tool(name):
    description = ("Count sales orders" if name == "count_orders" else
                   "Read the Odoo server version for this connection")
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True}}


def reply(request, case, trace):
    if "id" not in request:
        return None
    method = request["method"]
    response = {"jsonrpc": "2.0", "id": request["id"]}
    event = {"case": case, "method": method}
    if method == "initialize":
        response["result"] = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "fixture-odoo", "version": "1"}}
    elif method == "tools/list":
        response["result"] = {"tools": [tool(name) for name in CATALOGS[case]]}
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        event["tool"] = name
        if name not in CATALOGS[case] or params.get("arguments", {}) != {}:
            response["error"] = {"code": -32602, "message": "Unknown tool or invalid arguments"}
        elif case == "denied":
            response["result"] = {"isError": True, "content": [{"type": "text",
                                  "text": "Sign-in expired. Reconnect the selected connector."}]}
        elif name == "count_orders":
            response["result"] = {"isError": True, "content": [{"type": "text",
                                  "text": "Business records are outside this check."}]}
        else:
            # The host must obtain this value from a call, even if it has seen past runs.
            event["version"] = "19.0-sim-" + uuid4().hex[:8]
            response["result"] = {"content": [{"type": "text",
                                  "text": json.dumps({"server_version": event["version"]})}]}
    elif method == "ping":
        response["result"] = {}
    else:
        response["error"] = {"code": -32601, "message": "Method not found"}
    with trace.open("a", encoding="utf-8") as out:
        out.write(json.dumps(event) + "\n")
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=CATALOGS)
    parser.add_argument("--trace", type=Path, required=True)
    args = parser.parse_args()
    for line in sys.stdin:
        result = reply(json.loads(line), args.case, args.trace)
        if result is not None:
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
