#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""End-to-end check of a local sandbox through the plugin's own MCP server.

Used by the sandbox matrix workflow after ``deploy_local.py sandbox up``:
``python3 scripts/sandbox_smoke.py --dir <sandbox dir> --expect 17``.
It starts ``server/run_stdio.py`` with the sandbox credentials (read from the
owner-only ``.env``, never printed), speaks MCP over stdio exactly as Claude
Code does, and checks ``odoo_version`` plus a bounded ``odoo_search_read``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def call(proc: subprocess.Popen, msg_id: int, method: str, params: dict) -> dict:
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method,
                                 "params": params}) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit(f"MCP server exited before answering {method}")
        reply = json.loads(line)
        if reply.get("id") == msg_id:
            return reply


def tool(proc: subprocess.Popen, msg_id: int, name: str, arguments: dict) -> dict:
    reply = call(proc, msg_id, "tools/call", {"name": name, "arguments": arguments})
    result = reply.get("result") or {}
    text = (result.get("content") or [{}])[0].get("text", "")
    if result.get("isError") or "error" in reply:
        raise SystemExit(f"{name} failed: {text or reply.get('error')}")
    return json.loads(text)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", required=True, help="sandbox directory (holds .env)")
    parser.add_argument("--expect", type=int, required=True, help="expected Odoo major")
    args = parser.parse_args(argv)
    env_file = read_env(Path(args.dir).expanduser() / ".env")
    env = dict(os.environ)
    env.update({
        "ODOO_URL": f"http://localhost:{env_file['ODOO_PORT']}",
        "ODOO_DB": env_file["ODOO_DB"],
        "ODOO_LOGIN": env_file["ODOO_ADMIN_LOGIN"],
        "ODOO_PASSWORD": env_file["ODOO_ADMIN_PASSWORD"],
        "ODOO_API_KEY": "",
    })
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "server" / "run_stdio.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
    )
    try:
        init = call(proc, 1, "initialize", {"protocolVersion": "2025-06-18",
                                            "capabilities": {},
                                            "clientInfo": {"name": "sandbox-smoke",
                                                           "version": "1"}})
        server = init["result"]["serverInfo"]
        version = tool(proc, 2, "odoo_version", {})
        partners = tool(proc, 3, "odoo_search_read",
                        {"model": "res.partner", "fields": ["name"], "limit": 1})
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=30)
    report = {"server": server, "odoo": version,
              "partners_read": len(partners.get("records", []))}
    print(json.dumps(report, indent=2))
    if version.get("version") != args.expect:
        raise SystemExit(f"expected Odoo {args.expect}, the server reports {version}")
    if version.get("edition") != "community":
        raise SystemExit(f"expected a Community sandbox, got {version.get('edition')}")
    if report["partners_read"] < 1:
        raise SystemExit("res.partner returned no record")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
