# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia SAS)
"""Transport package: JSON-2, JSON-RPC, XML-RPC, and the selecting fallback wrapper."""

from .base import Transport
from .fallback import FallbackTransport
from .json2 import (
    Json2SignatureMismatch,
    Json2Transport,
    Json2Unavailable,
    Json2Unreachable,
)
from .jsonrpc import ApiKeyRejected, JsonRpcTransport, JsonRpcUnavailable
from .xmlrpc import XmlRpcTransport

__all__ = [
    "ApiKeyRejected",
    "FallbackTransport",
    "Json2SignatureMismatch",
    "Json2Transport",
    "Json2Unavailable",
    "Json2Unreachable",
    "JsonRpcTransport",
    "JsonRpcUnavailable",
    "Transport",
    "XmlRpcTransport",
]
