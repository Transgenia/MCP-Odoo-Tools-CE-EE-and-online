# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Transgenia (Centrum Transgenia S.A.S. de C.V.)
"""Optional Prometheus metrics and OpenTelemetry tracing.

Both are OFF by default and degrade to no-ops when the optional dependencies
are not installed, so the base install stays lean.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator

log = logging.getLogger("odoo_mcp.observability")


class Observability:
    def __init__(self, *, metrics: bool = False, metrics_port: int = 8085,
                 otel_endpoint: str = "") -> None:
        self._counter = None
        self._latency = None
        self._tracer = None
        if metrics:
            self._init_metrics(metrics_port)
        if otel_endpoint:
            self._init_otel(otel_endpoint)

    def _init_metrics(self, port: int) -> None:
        try:
            from prometheus_client import Counter, Histogram, start_http_server

            self._counter = Counter(
                "odoo_mcp_tool_calls_total", "Tool invocations", ["tool", "status"]
            )
            self._latency = Histogram(
                "odoo_mcp_tool_latency_seconds", "Tool latency", ["tool"]
            )
            start_http_server(port)
            log.info("Prometheus metrics on :%d/metrics", port)
        except Exception as exc:  # pragma: no cover - optional dep / port issues
            log.warning("metrics disabled (%s)", exc)

    def _init_otel(self, endpoint: str) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(resource=Resource.create({"service.name": "odoo-mcp-tools"}))
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer("odoo_mcp")
            log.info("OTLP tracing to %s", endpoint)
        except Exception as exc:  # pragma: no cover - optional dep
            log.warning("otel disabled (%s)", exc)

    @contextlib.contextmanager
    def span(self, tool: str) -> Iterator[None]:
        if self._tracer is None:
            yield
            return
        with self._tracer.start_as_current_span(f"tool.{tool}"):  # pragma: no cover - optional
            yield

    def record(self, tool: str, status: str, seconds: float) -> None:
        if self._counter is not None:
            self._counter.labels(tool=tool, status=status).inc()
        if self._latency is not None:
            self._latency.labels(tool=tool).observe(seconds)
