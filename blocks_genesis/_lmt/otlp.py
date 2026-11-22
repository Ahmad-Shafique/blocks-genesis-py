"""OTLP export switch shared by the trace, metric and log setup.

Export over OTLP is on only when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set to a non-empty value. The
exporters then read their endpoint, headers, timeout and so on from the standard ``OTEL_EXPORTER_OTLP_*``
variables. ``OTEL_EXPORTER_OTLP_PROTOCOL`` picks the transport: ``grpc`` (the default) or ``http/protobuf``.
"""
import os

ENDPOINT_ENV = "OTEL_EXPORTER_OTLP_ENDPOINT"
PROTOCOL_ENV = "OTEL_EXPORTER_OTLP_PROTOCOL"


def otlp_enabled() -> bool:
    """True when an OTLP endpoint is configured."""
    return bool(os.getenv(ENDPOINT_ENV, "").strip())


def _use_http() -> bool:
    return os.getenv(PROTOCOL_ENV, "grpc").strip().lower().startswith("http")


def create_span_exporter():
    if _use_http():
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    return OTLPSpanExporter()


def create_metric_exporter():
    if _use_http():
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    return OTLPMetricExporter()


def create_log_exporter():
    if _use_http():
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    else:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    return OTLPLogExporter()
