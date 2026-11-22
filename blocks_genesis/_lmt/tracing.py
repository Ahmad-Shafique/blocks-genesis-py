# tracing.py
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from blocks_genesis._lmt.mongo_trace_exporter import MongoDBTraceExporter
from blocks_genesis._lmt.otlp import create_metric_exporter, create_span_exporter, otlp_enabled
from blocks_genesis._core.secret_loader import get_blocks_secret

def configure_tracing() -> None:
    """Configures OpenTelemetry tracing and metrics for the FastAPI application.

    Spans always go to MongoDB. When OTEL_EXPORTER_OTLP_ENDPOINT is set they also go over OTLP, and
    a meter provider exports metrics the same way. The sampler is the SDK's own: it follows
    OTEL_TRACES_SAMPLER when that is set.
    """
    resource = Resource.create({SERVICE_NAME: get_blocks_secret().ServiceName})
    trace.set_tracer_provider(TracerProvider(resource=resource))

    exporter = MongoDBTraceExporter()

    processor = BatchSpanProcessor(exporter)
    trace.get_tracer_provider().add_span_processor(processor)

    if otlp_enabled():
        trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(create_span_exporter()))
        reader = PeriodicExportingMetricReader(create_metric_exporter())
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
