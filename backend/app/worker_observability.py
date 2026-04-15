"""
Structured logging, Prometheus metrics, and optional OpenTelemetry for the PDF worker.

Implements PR-TR-10 (JSON logs), PR-TR-11 (metrics scrape endpoint), PR-TR-12 (optional OTLP).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# --- Prometheus (PR-TR-11): register metrics at import; HTTP server starts from worker ---

JOBS_COMPLETED = Counter("pdf_worker_jobs_completed_total", "Jobs finished successfully")
JOBS_FAILED = Counter("pdf_worker_jobs_failed_total", "Jobs finished with terminal failure")
JOBS_DLQ = Counter("pdf_worker_jobs_dlq_total", "Jobs moved to dead-letter stream")
JOBS_RETRIED = Counter("pdf_worker_jobs_retried_total", "Transient failures re-enqueued")
JOBS_SKIPPED_IDEMPOTENT = Counter(
    "pdf_worker_jobs_skipped_idempotent_total",
    "Stream deliveries skipped because job already done",
)
PROC_SECONDS = Histogram(
    "pdf_worker_process_seconds",
    "Wall time spent processing one stream message (excludes retry sleep)",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, float("inf")),
)
PENDING_GAUGE = Gauge(
    "pdf_worker_stream_pending_entries",
    "Approximate pending entries for the consumer group",
    ["stream"],
)

_metrics_server_started = False

# --- JSON logging (PR-TR-10) ----------------------------------------------------------------

_logger = logging.getLogger("pdf_worker")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
_logger.setLevel(logging.INFO)
_logger.propagate = False


def log_json(event: str, **fields: Any) -> None:
    """Emit one JSON object per line."""
    payload: dict[str, Any] = {"ts": time.time(), "level": "INFO", "service": "pdf-proc-worker", "event": event}
    for k, v in fields.items():
        if v is not None:
            payload[k] = v
    _logger.info(json.dumps(payload, default=str))


def init_worker_metrics(port: int) -> None:
    """Expose /metrics on 0.0.0.0:port when port > 0."""
    global _metrics_server_started
    if port <= 0 or _metrics_server_started:
        return
    start_http_server(port)
    _metrics_server_started = True
    log_json("metrics_server_started", port=port)


def observe_pending(stream: str, value: float) -> None:
    try:
        PENDING_GAUGE.labels(stream=stream).set(value)
    except Exception:
        pass


def metric_dlq() -> None:
    JOBS_DLQ.inc()


def metric_done() -> None:
    JOBS_COMPLETED.inc()


def metric_fail() -> None:
    JOBS_FAILED.inc()


def metric_retry() -> None:
    JOBS_RETRIED.inc()


def metric_skip_idempotent() -> None:
    JOBS_SKIPPED_IDEMPOTENT.inc()


def metric_observe_duration(seconds: float) -> None:
    PROC_SECONDS.observe(seconds)


# --- OpenTelemetry (optional, PR-TR-12) --------------------------------------------------

_tracer: Any | bool | None = None


def _ensure_tracer() -> Any:
    global _tracer
    if _tracer is not None:
        return _tracer if _tracer is not False else None
    if os.getenv("OTEL_SDK_DISABLED", "").strip().lower() in ("1", "true", "yes"):
        _tracer = False
        return None
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        _tracer = False
        return None
    try:
        from opentelemetry import trace as trace_api
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception as e:  # pragma: no cover
        log_json("otel_init_skipped", reason="import_failed", error=str(e))
        _tracer = False
        return None

    service = os.getenv("OTEL_SERVICE_NAME", "pdf-proc-worker")
    resource = Resource.create({"service.name": service})
    provider = SDKTracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    existing = trace_api.get_tracer_provider()
    if not isinstance(existing, SDKTracerProvider):
        trace_api.set_tracer_provider(provider)
    _tracer = trace_api.get_tracer("pdf-proc-worker", "1.0.0")
    log_json("otel_tracer_initialized", service=service)
    return _tracer


@contextmanager
def span_worker_process(
    *,
    name: str,
    job_id: str | None,
    msg_id: str | None,
    correlation_id: str | None,
) -> Iterator[None]:
    t = _ensure_tracer()
    if not t:
        yield
        return

    attrs: dict[str, Any] = {}
    if job_id:
        attrs["job_id"] = job_id
    if msg_id:
        attrs["messaging.message_id"] = str(msg_id)
    if correlation_id:
        attrs["correlation_id"] = correlation_id
    with t.start_as_current_span(name, attributes=attrs):
        yield
