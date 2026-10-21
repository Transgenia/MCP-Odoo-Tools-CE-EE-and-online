# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""The permission policy docs agree with the code (design 9.6).

docs/policy.md carries tables generated from the policy's own data
(scripts/policy_docs.py), docs/policy.schema.json mirrors the loader's keys and
limits for editors (the standard library has no JSON Schema validator, so the
enums and patterns are compared instead), and every example file loads.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from odoo_mcp import tools as _tools  # noqa: F401  (registers the tools)
from odoo_mcp.policy import loader
from odoo_mcp.policy.classify import METHOD_NAME
from odoo_mcp.policy.loader import load_bytes
from odoo_mcp.policy.model import PROFILES
from odoo_mcp.registry import registry

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "policy.md"
SCHEMA = ROOT / "docs" / "policy.schema.json"
EXAMPLES = ROOT / "docs" / "policy-examples"
# The profile each example is written for (its "comment" and docs/policy.md say so).
EXAMPLE_PROFILES = {
    "production-hardened.json": "standard",
    "sales-team.json": "standard",
    "read-only-analyst.json": "readonly",
    "sandbox-builder.json": "builder",
}


def _policy_docs() -> Any:
    spec = importlib.util.spec_from_file_location("policy_docs",
                                                  ROOT / "scripts" / "policy_docs.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["policy_docs"] = module
    spec.loader.exec_module(module)
    return module


def test_the_generated_tables_match_the_policy_data() -> None:
    text = DOC.read_text(encoding="utf-8")
    expected = _policy_docs().render(text)
    assert expected == text, "run python3 scripts/policy_docs.py --write"


def test_the_generator_refuses_a_missing_or_unknown_block() -> None:
    docs = _policy_docs()
    with pytest.raises(KeyError, match="lacks the generated blocks"):
        docs.render("no blocks here\n")
    with pytest.raises(KeyError, match="unknown generated block"):
        docs.render(DOC.read_text(encoding="utf-8")
                    + "<!-- generated:bogus -->\n<!-- /generated:bogus -->\n")


def test_the_doc_names_every_code_and_the_escape() -> None:
    text = DOC.read_text(encoding="utf-8")
    for code in list(loader.ERRORS) + list(loader.WARNINGS):
        assert f"| {code} |" in text, code
    assert "W10 comes from `odoo_version`" in text
    assert "set Permission profile to `full`" in text  # the documented 1.4 escape
    assert "ODOO_POLICY=full" in text
    for profile in PROFILES:
        assert f"`{profile}`" in text
    assert "#tool-mapping" not in text  # the anchor is the heading itself
    assert "\n## Tool mapping\n" in text  # registry.MISSING_MAPPING points here


def test_new_prose_has_no_long_dashes() -> None:
    for path in [DOC, SCHEMA, *EXAMPLES.glob("*.json")]:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text, path.name


def test_the_examples_are_the_four_listed() -> None:
    assert {path.name for path in EXAMPLES.glob("*.json")} == set(EXAMPLE_PROFILES)
    text = DOC.read_text(encoding="utf-8")
    for name, profile in EXAMPLE_PROFILES.items():
        assert f"(policy-examples/{name}) | `{profile}` |" in text, name


@pytest.mark.parametrize("name", sorted(EXAMPLE_PROFILES))
def test_every_example_loads_under_every_profile(name: str) -> None:
    path = EXAMPLES / name
    names = [tool.name for tool in registry.all()]
    for profile in PROFILES:
        policy = load_bytes(path.read_bytes(), path=str(path), profile=profile,
                            tool_names=names)
        assert not policy.locked, (name, profile, policy.error)
    intended = load_bytes(path.read_bytes(), path=str(path),
                          profile=EXAMPLE_PROFILES[name], tool_names=names)
    assert "W4" not in {code for code, _text in intended.warnings}  # nothing expired


def test_the_hardened_example_is_the_one_in_the_doc() -> None:
    text = DOC.read_text(encoding="utf-8")
    section = text.split("The hardened file, for production with an administrator user:", 1)[1]
    block = section.split("```json\n", 1)[1].split("```", 1)[0]
    assert json.loads(block) == json.loads(
        (EXAMPLES / "production-hardened.json").read_text(encoding="utf-8"))


def test_the_hardened_example_does_what_the_doc_says() -> None:
    path = EXAMPLES / "production-hardened.json"
    policy = load_bytes(path.read_bytes(), path=str(path), profile="standard",
                        tool_names=[tool.name for tool in registry.all()])
    assert policy.decide("call", "sale.order", "action_confirm").allowed
    assert not policy.decide("call", "sale.order", "write").allowed
    assert not policy.decide("call", "res.partner", "read").allowed  # call is required
    assert policy.decide("call", "res.partner", "message_post").allowed
    assert not policy.decide("read", "hr.employee").allowed
    assert not policy.decide("read", "mail.message").allowed
    assert not policy.decide("write", "website.page").allowed
    assert policy.decide("write", "res.partner").allowed
    assert "odoo_import" in policy.disabled


def test_the_policy_file_example_in_the_doc_loads() -> None:
    text = DOC.read_text(encoding="utf-8")
    block = text.split("## The policy file\n", 1)[1].split("```json\n", 1)[1].split("```", 1)[0]
    policy = load_bytes(block.encode("utf-8"), path="/doc/policy.json", profile="standard",
                        tool_names=[tool.name for tool in registry.all()])
    assert not policy.locked, policy.error


# --- the editor schema --------------------------------------------------------------

def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _anchored(pattern: str) -> str:
    return f"^(?:{pattern})$"


def test_the_schema_has_the_loader_keys() -> None:
    schema = _schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert tuple(schema["properties"]) == loader.TOP_KEYS
    assert schema["required"] == ["version"]
    assert schema["properties"]["version"]["const"] == loader.FILE_VERSION
    exact = schema["$defs"]["exactEntry"]
    pattern = schema["$defs"]["patternEntry"]
    assert tuple(exact["properties"]) == loader.ENTRY_KEYS
    assert set(pattern["properties"]) == set(loader.ENTRY_KEYS) - {"reason", "expires"}  # E19
    assert exact["additionalProperties"] is False and pattern["additionalProperties"] is False
    for op in loader.BOOLEAN_OPS:
        assert exact["properties"][op]["type"] == "boolean"
    fields = schema["properties"]["fields"]
    assert tuple(fields["properties"]) == loader.FIELDS_KEYS
    allow = fields["properties"]["allow"]["items"]
    assert tuple(allow["properties"]) == loader.ALLOW_KEYS
    assert tuple(schema["properties"]["tools"]["properties"]) == loader.TOOLS_KEYS


def test_the_schema_has_the_loader_limits_and_patterns() -> None:
    schema = _schema()
    models = schema["properties"]["models"]
    assert models["maxProperties"] == loader.MAX_MODELS
    assert models["propertyNames"]["maxLength"] == loader.MAX_KEY_LENGTH
    assert models["propertyNames"]["pattern"] == _anchored(loader._MODEL_KEY.pattern)
    patterns = list(models["patternProperties"])
    assert len(patterns) == 1
    for key, is_pattern in (("*", True), ("hr.*", True), ("res.partner", False),
                            ("website.page", False)):
        assert bool(re.fullmatch(patterns[0][1:-1], key)) is is_pattern, key
    call = schema["$defs"]["exactEntry"]["properties"]["call"]["oneOf"][1]
    assert (call["minItems"], call["maxItems"]) == (1, loader.MAX_CALL_METHODS)
    assert call["items"]["pattern"] == _anchored(METHOD_NAME.pattern)
    reason = schema["$defs"]["exactEntry"]["properties"]["reason"]
    assert (reason["minLength"], reason["maxLength"]) == (loader.REASON_MIN, loader.REASON_MAX)
    fields = schema["properties"]["fields"]["properties"]
    withhold = [item["pattern"] for item in fields["withhold"]["items"]["anyOf"]]
    assert withhold == [_anchored(loader._MODEL_FIELD.pattern),
                        _anchored(loader._ANY_MODEL_FIELD.pattern)]
    allow_reason = fields["allow"]["items"]["properties"]["reason"]
    assert (allow_reason["minLength"], allow_reason["maxLength"]) == (
        loader.REASON_MIN, loader.REASON_MAX)


def test_the_schema_names_every_tool() -> None:
    enum = _schema()["properties"]["tools"]["properties"]["disabled"]["items"]["enum"]
    assert enum == sorted(tool.name for tool in registry.all())
    assert len(enum) == 28
