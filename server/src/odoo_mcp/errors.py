# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Normalized error types surfaced to MCP callers."""

from __future__ import annotations


class OdooMcpError(Exception):
    """Base class for all errors raised by this server."""


class AuthError(OdooMcpError):
    """Authentication against the Odoo instance failed."""


class TransportError(OdooMcpError):
    """A transport-level failure (network, protocol) occurred."""


class OdooFault(OdooMcpError):
    """The Odoo server returned an application-level fault."""


class CompatError(OdooMcpError):
    """A request cannot be satisfied on the target Odoo version/edition.

    Carries a human-readable remediation so the caller knows what to change.
    """

    def __init__(self, message: str, *, remediation: str | None = None) -> None:
        super().__init__(message)
        self.remediation = remediation

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = super().__str__()
        if self.remediation:
            return f"{base} — {self.remediation}"
        return base


class ConfigError(OdooMcpError):
    """Server configuration is incomplete or invalid."""
