"""OpenTelemetry setup for Tracecat services.

Configures:
- TracerProvider with OTLP gRPC exporter (→ Tempo)
- MeterProvider with Prometheus exporter (→ Prometheus scrape)
- Auto-instrumentation for HTTPX and SQLAlchemy

Controlled via environment variables:
- OTEL_TRACES_ENABLED: "true" to enable trace export (default: false)
- OTEL_METRICS_ENABLED: "true" to enable metrics export (default: false)
- OTEL_EXPORTER_OTLP_ENDPOINT: gRPC endpoint for Tempo (default: http://tempo:4317)
- OTEL_SERVICE_NAME: service name tag on all telemetry (default: tracecat)
"""

import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    _OTLP_GRPC_AVAILABLE = True
except ImportError:
    _OTLP_GRPC_AVAILABLE = False


def setup_telemetry(service_name: str | None = None) -> None:
    """Initialize OpenTelemetry providers and auto-instrumentation.

    Safe to call at process startup. Subsequent calls to this function after
    the providers are already set will have no effect on the global state.

    Args:
        service_name: Override for the OTEL_SERVICE_NAME env var. Falls back
            to the env var, then to "tracecat".
    """
    resolved_name = (
        service_name
        or os.environ.get("OTEL_SERVICE_NAME")
        or "tracecat"
    )
    traces_enabled = os.environ.get("OTEL_TRACES_ENABLED", "false").lower() == "true"
    metrics_enabled = os.environ.get("OTEL_METRICS_ENABLED", "false").lower() == "true"

    if not traces_enabled and not metrics_enabled:
        return

    resource = Resource(attributes={SERVICE_NAME: resolved_name})

    if traces_enabled:
        _setup_traces(resource)

    if metrics_enabled:
        _setup_metrics(resource)

    # Auto-instrument HTTPX (covers both sync and async clients)
    HTTPXClientInstrumentor().instrument()


def _setup_traces(resource: Resource) -> None:
    if not _OTLP_GRPC_AVAILABLE:
        return
    otlp_endpoint = os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://tempo:4317"
    )
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)  # type: ignore[name-defined]
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def _setup_metrics(resource: Resource) -> None:
    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)


def instrument_sqlalchemy(engine: object) -> None:
    """Instrument a SQLAlchemy engine after it is created.

    Passes the underlying sync engine because the OTEL SQLAlchemy instrumentor
    hooks into core SQLAlchemy events that are exposed on the sync layer.

    Args:
        engine: An AsyncEngine or sync Engine instance.
    """
    metrics_enabled = os.environ.get("OTEL_METRICS_ENABLED", "false").lower() == "true"
    traces_enabled = os.environ.get("OTEL_TRACES_ENABLED", "false").lower() == "true"
    if not metrics_enabled and not traces_enabled:
        return

    # AsyncEngine wraps a sync engine accessible via .sync_engine
    sync_engine = getattr(engine, "sync_engine", engine)
    SQLAlchemyInstrumentor().instrument(engine=sync_engine, enable_commenter=True)


def get_tracer(name: str) -> trace.Tracer:
    """Return an OpenTelemetry tracer bound to the given instrumentation name."""
    return trace.get_tracer(name)


def get_meter(name: str) -> metrics.Meter:
    """Return an OpenTelemetry meter bound to the given instrumentation name."""
    return metrics.get_meter(name)
