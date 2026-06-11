"""App-level OTel TracerProvider singleton.

Call ``init_global_provider`` once at application startup (before any
spans are created).  After that, the standard ``opentelemetry.trace``
API automatically delegates to the global provider — callers just need
``trace.get_tracer(name)``.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_provider: TracerProvider | None = None


def _load_otlp_exporter(protocol: str) -> Any:
    import importlib

    if protocol == "http/protobuf":
        mod = importlib.import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    else:
        mod = importlib.import_module("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    return mod.OTLPSpanExporter


def init_global_provider(
    *,
    service_name: str = "joysafeter",
) -> TracerProvider:
    global _provider
    if _provider is not None:
        return _provider

    _provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
    )

    _maybe_attach_otlp_exporter(_provider)

    trace.set_tracer_provider(_provider)
    return _provider


def get_global_provider() -> TracerProvider:
    if _provider is None:
        raise RuntimeError("call init_global_provider() during app startup")
    return _provider


def _maybe_attach_otlp_exporter(provider: TracerProvider) -> None:
    """Attach an OTLP span exporter if OTEL_EXPORTER_OTLP_ENDPOINT is configured."""
    from app.joysafeter_shared.config.settings import settings

    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return

    protocol = settings.otel_exporter_otlp_protocol

    try:
        exporter_cls = _load_otlp_exporter(protocol)
        exporter = exporter_cls(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(f"   ✓ OTLP trace exporter → {endpoint} ({protocol})")
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but the exporter package is not installed. "
            "Install opentelemetry-exporter-otlp-proto-grpc or opentelemetry-exporter-otlp-proto-http."
        )
    except Exception:
        logger.opt(exception=True).warning("Failed to initialize OTLP trace exporter")
