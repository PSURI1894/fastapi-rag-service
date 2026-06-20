"""Optional OpenTelemetry tracing.

No-op unless `OTEL_ENABLED=true` AND the `otel` extra is installed (imports are
lazy, so the app loads fine without it). When on, it auto-instruments FastAPI —
every request becomes a span, with child spans for instrumented libraries — and
exports to the console by default, or to an OTLP endpoint (a collector, or
LangSmith's OTLP ingest) when one is configured.
"""

from fastapi import FastAPI

from app.config import Settings


def setup_tracing(app: FastAPI, settings: Settings) -> None:
    if not settings.otel_enabled:
        return

    from opentelemetry import trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        processor = BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
        )
    else:
        processor = BatchSpanProcessor(ConsoleSpanExporter())

    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
