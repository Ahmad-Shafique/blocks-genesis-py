# tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from blocks_genesis._lmt.mongo_trace_exporter import MongoDBTraceExporter
from blocks_genesis._core.secret_loader import get_blocks_secret

_BAGGAGE_PREFIX = "baggage."


class BaggageSpanProcessor(SpanProcessor):
    """Gives each new span the parent span's baggage.* attributes it does not set itself.

    The trace exporter files a span under its own baggage.TenantId. Copied at start, because
    export runs on the exporter's thread, outside the request's context. Only span attributes,
    never OTel context baggage: that would leave the process in outgoing headers, and an
    incoming baggage header could then pick the trace collection.
    """

    def on_start(self, span, parent_context=None):
        inherited = getattr(trace.get_current_span(parent_context), "attributes", None)
        if not inherited:
            return
        own = span.attributes or {}
        for key, value in inherited.items():
            if key.startswith(_BAGGAGE_PREFIX) and key not in own:
                span.set_attribute(key, value)


def configure_tracing() -> None:
    """Configures OpenTelemetry tracing for the FastAPI application."""
    trace.set_tracer_provider(
        TracerProvider(
            resource=Resource.create({SERVICE_NAME: get_blocks_secret().ServiceName})
        )
    )

    provider = trace.get_tracer_provider()
    provider.add_span_processor(BaggageSpanProcessor())
    provider.add_span_processor(BatchSpanProcessor(MongoDBTraceExporter()))

