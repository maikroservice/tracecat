"""Tests for the OpenTelemetry telemetry module.

TDD: These tests define expected behavior before implementation.
"""

from collections.abc import Generator
from unittest.mock import MagicMock, call, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_otel_globals() -> None:
    """Reset OpenTelemetry global providers between tests.

    The OTEL SDK uses module-level singletons. We must reset them so that
    each test starts from a clean state.
    """
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider

    trace.set_tracer_provider(TracerProvider())
    metrics.set_meter_provider(MeterProvider())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_otel() -> Generator[None, None, None]:
    """Reset OTEL global providers before and after every test."""
    _reset_otel_globals()
    yield
    _reset_otel_globals()


@pytest.fixture
def metrics_app() -> FastAPI:
    """Minimal FastAPI app with /metrics endpoint (matches impl in app.py)."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    app = FastAPI()

    @app.get("/metrics")
    def prometheus_metrics():  # pyright: ignore[reportUnusedFunction]
        from fastapi.responses import Response

        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return app


@pytest.fixture
def metrics_client(metrics_app: FastAPI) -> TestClient:
    return TestClient(metrics_app)


# ---------------------------------------------------------------------------
# setup_telemetry — disabled (no-op)
# ---------------------------------------------------------------------------


def test_setup_telemetry_noop_when_both_disabled() -> None:
    """setup_telemetry does nothing when both flags are false (the default)."""
    from opentelemetry import metrics, trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider

    original_tracer_provider = trace.get_tracer_provider()
    original_meter_provider = metrics.get_meter_provider()

    with (
        patch.dict("os.environ", {"OTEL_TRACES_ENABLED": "false", "OTEL_METRICS_ENABLED": "false"}),
        patch("opentelemetry.sdk.trace.TracerProvider", wraps=TracerProvider) as mock_tp,
        patch("opentelemetry.sdk.metrics.MeterProvider", wraps=MeterProvider) as mock_mp,
    ):
        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry(service_name="test-service")

        # Neither provider was constructed inside setup_telemetry
        mock_tp.assert_not_called()
        mock_mp.assert_not_called()

    # Global state is unchanged
    assert trace.get_tracer_provider() is original_tracer_provider
    assert metrics.get_meter_provider() is original_meter_provider


def test_setup_telemetry_noop_when_env_vars_absent() -> None:
    """setup_telemetry is a no-op when OTEL_* flags are not set at all."""
    import os

    from opentelemetry import metrics, trace

    # Remove flags entirely
    env_without_flags = {k: v for k, v in os.environ.items() if "OTEL_" not in k}

    original_tracer_provider = trace.get_tracer_provider()
    original_meter_provider = metrics.get_meter_provider()

    with patch.dict("os.environ", env_without_flags, clear=True):
        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry()

    assert trace.get_tracer_provider() is original_tracer_provider
    assert metrics.get_meter_provider() is original_meter_provider


# ---------------------------------------------------------------------------
# setup_telemetry — traces enabled
# ---------------------------------------------------------------------------


def test_setup_telemetry_configures_tracer_provider_when_traces_enabled() -> None:
    """When OTEL_TRACES_ENABLED=true, a TracerProvider with OTLP exporter is set globally."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    with (
        patch.dict("os.environ", {"OTEL_TRACES_ENABLED": "true", "OTEL_METRICS_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.OTLPSpanExporter") as mock_exporter_cls,
        patch("tracecat.telemetry.setup.BatchSpanProcessor") as mock_processor_cls,
        patch("tracecat.telemetry.setup.trace") as mock_trace,
    ):
        mock_exporter = MagicMock()
        mock_exporter_cls.return_value = mock_exporter
        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry(service_name="test-traces")

        # A TracerProvider was created and set globally
        mock_trace.set_tracer_provider.assert_called_once()
        provider_arg = mock_trace.set_tracer_provider.call_args[0][0]
        assert isinstance(provider_arg, TracerProvider)

        # OTLPSpanExporter was constructed with the default Tempo endpoint
        mock_exporter_cls.assert_called_once_with(
            endpoint="http://tempo:4317", insecure=True
        )

        # BatchSpanProcessor was created with the exporter and added to the provider
        mock_processor_cls.assert_called_once_with(mock_exporter)


def test_setup_telemetry_traces_uses_custom_otlp_endpoint() -> None:
    """OTEL_EXPORTER_OTLP_ENDPOINT env var overrides the default Tempo endpoint."""
    with (
        patch.dict(
            "os.environ",
            {
                "OTEL_TRACES_ENABLED": "true",
                "OTEL_METRICS_ENABLED": "false",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://my-collector:4317",
            },
        ),
        patch("tracecat.telemetry.setup.OTLPSpanExporter") as mock_exporter_cls,
        patch("tracecat.telemetry.setup.BatchSpanProcessor"),
        patch("tracecat.telemetry.setup.trace"),
    ):
        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry(service_name="test-custom-endpoint")

        mock_exporter_cls.assert_called_once_with(
            endpoint="http://my-collector:4317", insecure=True
        )


def test_setup_telemetry_traces_resource_uses_service_name() -> None:
    """The TracerProvider resource includes the given service name."""
    from opentelemetry.sdk.resources import SERVICE_NAME

    with (
        patch.dict("os.environ", {"OTEL_TRACES_ENABLED": "true", "OTEL_METRICS_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.OTLPSpanExporter"),
        patch("tracecat.telemetry.setup.BatchSpanProcessor"),
        patch("tracecat.telemetry.setup.TracerProvider") as mock_tp_cls,
        patch("tracecat.telemetry.setup.trace"),
    ):
        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry(service_name="my-worker")

        # TracerProvider was constructed with a Resource containing SERVICE_NAME
        assert mock_tp_cls.called
        resource_arg = mock_tp_cls.call_args.kwargs.get("resource") or mock_tp_cls.call_args[1].get("resource")
        assert resource_arg is not None
        assert resource_arg.attributes[SERVICE_NAME] == "my-worker"


def test_setup_telemetry_traces_service_name_from_env() -> None:
    """OTEL_SERVICE_NAME env var is used when service_name arg is None."""
    with (
        patch.dict(
            "os.environ",
            {
                "OTEL_TRACES_ENABLED": "true",
                "OTEL_METRICS_ENABLED": "false",
                "OTEL_SERVICE_NAME": "env-service",
            },
        ),
        patch("tracecat.telemetry.setup.OTLPSpanExporter"),
        patch("tracecat.telemetry.setup.BatchSpanProcessor"),
        patch("tracecat.telemetry.setup.TracerProvider") as mock_tp_cls,
        patch("tracecat.telemetry.setup.trace"),
    ):
        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry()  # no service_name arg

        resource_arg = mock_tp_cls.call_args.kwargs.get("resource") or mock_tp_cls.call_args[1].get("resource")
        from opentelemetry.sdk.resources import SERVICE_NAME

        assert resource_arg.attributes[SERVICE_NAME] == "env-service"


# ---------------------------------------------------------------------------
# setup_telemetry — metrics enabled
# ---------------------------------------------------------------------------


def test_setup_telemetry_configures_meter_provider_when_metrics_enabled() -> None:
    """When OTEL_METRICS_ENABLED=true, a MeterProvider with Prometheus reader is set globally."""
    from opentelemetry.sdk.metrics import MeterProvider

    with (
        patch.dict("os.environ", {"OTEL_METRICS_ENABLED": "true", "OTEL_TRACES_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.PrometheusMetricReader") as mock_reader_cls,
        patch("tracecat.telemetry.setup.MeterProvider") as mock_mp_cls,
        patch("tracecat.telemetry.setup.metrics") as mock_metrics,
    ):
        mock_reader = MagicMock()
        mock_reader_cls.return_value = mock_reader
        mock_provider = MagicMock(spec=MeterProvider)
        mock_mp_cls.return_value = mock_provider

        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry(service_name="test-metrics")

        # PrometheusMetricReader was created
        mock_reader_cls.assert_called_once()

        # MeterProvider was created with the reader
        mock_mp_cls.assert_called_once()
        call_kwargs = mock_mp_cls.call_args.kwargs
        assert mock_reader in call_kwargs.get("metric_readers", [])

        # MeterProvider was set globally
        mock_metrics.set_meter_provider.assert_called_once_with(mock_provider)


# ---------------------------------------------------------------------------
# setup_telemetry — HTTPX auto-instrumentation
# ---------------------------------------------------------------------------


def test_setup_telemetry_instruments_httpx_when_enabled() -> None:
    """HTTPXClientInstrumentor is called when either signal is enabled."""
    with (
        patch.dict("os.environ", {"OTEL_TRACES_ENABLED": "true", "OTEL_METRICS_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.HTTPXClientInstrumentor") as mock_httpx_cls,
        patch("tracecat.telemetry.setup.OTLPSpanExporter"),
        patch("tracecat.telemetry.setup.BatchSpanProcessor"),
        patch("tracecat.telemetry.setup.trace"),
    ):
        mock_httpx = MagicMock()
        mock_httpx_cls.return_value = mock_httpx

        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry(service_name="test-httpx")

        mock_httpx_cls.assert_called_once()
        mock_httpx.instrument.assert_called_once()


def test_setup_telemetry_does_not_instrument_httpx_when_disabled() -> None:
    """HTTPXClientInstrumentor is NOT called when all signals are disabled."""
    with (
        patch.dict("os.environ", {"OTEL_TRACES_ENABLED": "false", "OTEL_METRICS_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.HTTPXClientInstrumentor") as mock_httpx_cls,
    ):
        from tracecat.telemetry.setup import setup_telemetry

        setup_telemetry(service_name="test-disabled")

        mock_httpx_cls.assert_not_called()


# ---------------------------------------------------------------------------
# instrument_sqlalchemy
# ---------------------------------------------------------------------------


def test_instrument_sqlalchemy_noop_when_telemetry_disabled() -> None:
    """instrument_sqlalchemy does nothing when telemetry is disabled."""
    with (
        patch.dict("os.environ", {"OTEL_TRACES_ENABLED": "false", "OTEL_METRICS_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.SQLAlchemyInstrumentor") as mock_sa_cls,
    ):
        from tracecat.telemetry.setup import instrument_sqlalchemy

        mock_engine = MagicMock()
        instrument_sqlalchemy(mock_engine)

        mock_sa_cls.assert_not_called()


def test_instrument_sqlalchemy_instruments_sync_engine_when_metrics_enabled() -> None:
    """instrument_sqlalchemy extracts the sync engine from an AsyncEngine."""
    with (
        patch.dict("os.environ", {"OTEL_METRICS_ENABLED": "true", "OTEL_TRACES_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.SQLAlchemyInstrumentor") as mock_sa_cls,
    ):
        mock_instrumentor = MagicMock()
        mock_sa_cls.return_value = mock_instrumentor

        from tracecat.telemetry.setup import instrument_sqlalchemy

        # Simulate an AsyncEngine with .sync_engine attribute
        mock_async_engine = MagicMock()
        mock_sync_engine = MagicMock()
        mock_async_engine.sync_engine = mock_sync_engine

        instrument_sqlalchemy(mock_async_engine)

        mock_sa_cls.assert_called_once()
        mock_instrumentor.instrument.assert_called_once_with(
            engine=mock_sync_engine, enable_commenter=True
        )


def test_instrument_sqlalchemy_uses_engine_directly_when_no_sync_engine_attr() -> None:
    """instrument_sqlalchemy falls back to the engine itself if .sync_engine is absent."""
    with (
        patch.dict("os.environ", {"OTEL_TRACES_ENABLED": "true", "OTEL_METRICS_ENABLED": "false"}),
        patch("tracecat.telemetry.setup.SQLAlchemyInstrumentor") as mock_sa_cls,
    ):
        mock_instrumentor = MagicMock()
        mock_sa_cls.return_value = mock_instrumentor

        from tracecat.telemetry.setup import instrument_sqlalchemy

        # Sync engine (no .sync_engine attr)
        mock_sync_engine = MagicMock(spec=[])  # no attributes
        instrument_sqlalchemy(mock_sync_engine)

        mock_instrumentor.instrument.assert_called_once_with(
            engine=mock_sync_engine, enable_commenter=True
        )


# ---------------------------------------------------------------------------
# /metrics endpoint
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_200(metrics_client: TestClient) -> None:
    """GET /metrics returns HTTP 200."""
    response = metrics_client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_returns_prometheus_content_type(metrics_client: TestClient) -> None:
    """GET /metrics returns a Prometheus-compatible Content-Type."""
    response = metrics_client.get("/metrics")
    content_type = response.headers.get("content-type", "")
    # Prometheus text format: text/plain; version=0.0.4; charset=utf-8
    assert "text/plain" in content_type


def test_metrics_endpoint_body_is_not_empty(metrics_client: TestClient) -> None:
    """GET /metrics returns a non-empty body (at minimum the process/go metrics)."""
    response = metrics_client.get("/metrics")
    assert len(response.content) > 0


# ---------------------------------------------------------------------------
# Custom metrics helpers
# ---------------------------------------------------------------------------


def test_get_tracer_returns_noop_tracer_when_traces_disabled() -> None:
    """get_tracer returns the global (no-op) tracer when traces are not configured."""
    from opentelemetry import trace

    from tracecat.telemetry.setup import get_tracer

    tracer = get_tracer("tracecat.test")
    # Both delegate to the same global ProxyTracerProvider — same type, not same instance
    assert type(tracer) is type(trace.get_tracer("tracecat.test"))


def test_get_meter_returns_noop_meter_when_metrics_disabled() -> None:
    """get_meter returns the global (no-op) meter when metrics are not configured."""
    from opentelemetry import metrics

    from tracecat.telemetry.setup import get_meter

    meter = get_meter("tracecat.test")
    assert type(meter) is type(metrics.get_meter("tracecat.test"))
