from queue import Queue
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from blocks_genesis._lmt import tracing
from blocks_genesis._lmt.activity import Activity
from blocks_genesis._lmt.mongo_trace_exporter import MongoDBTraceExporter

TR = 'blocks_genesis._lmt.tracing.'


@pytest.fixture
def spans():
    """A local provider (the global one can be set only once per process) and its finished spans."""
    provider = TracerProvider()
    provider.add_span_processor(tracing.BaggageSpanProcessor())
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter
    provider.shutdown()


def _finished(exporter, name):
    return next(s for s in exporter.get_finished_spans() if s.name == name)


def _tenant_child(provider, exporter):
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("root", attributes={"baggage.TenantId": "t1"}):
        with tracer.start_as_current_span("child"):
            pass
    return _finished(exporter, "child")


def test_child_span_inherits_parent_tenant(spans):
    child = _tenant_child(*spans)
    assert child.attributes.get("baggage.TenantId") == "t1"


def test_grandchild_inherits_through_a_span_that_set_nothing(spans):
    provider, exporter = spans
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("root", attributes={"baggage.TenantId": "t1"}):
        with tracer.start_as_current_span("child"):
            with tracer.start_as_current_span("grandchild"):
                pass
    assert _finished(exporter, "grandchild").attributes.get("baggage.TenantId") == "t1"


def test_child_keeps_its_own_baggage_value(spans):
    provider, exporter = spans
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("root", attributes={"baggage.TenantId": "t1"}):
        with tracer.start_as_current_span("child", attributes={"baggage.TenantId": "t2"}):
            pass
    assert _finished(exporter, "child").attributes["baggage.TenantId"] == "t2"


def test_only_baggage_attributes_are_copied(spans):
    provider, exporter = spans
    tracer = provider.get_tracer("test")
    root_attributes = {"http.url": "https://example.test/?code=secret", "baggage.UserId": "u1"}
    with tracer.start_as_current_span("root", attributes=root_attributes):
        with tracer.start_as_current_span("child"):
            pass
    child = _finished(exporter, "child")
    assert child.attributes.get("baggage.UserId") == "u1"
    assert "http.url" not in child.attributes


def test_remote_parent_copies_nothing(spans):
    provider, exporter = spans
    remote = TraceContextTextMapPropagator().extract(
        {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}
    )
    with provider.get_tracer("test").start_as_current_span("child", context=remote):
        pass
    child = _finished(exporter, "child")
    assert not [k for k in child.attributes if k.startswith("baggage.")]


def test_child_span_is_written_to_the_tenant_collection(spans):
    child = _tenant_child(*spans)
    exporter = MongoDBTraceExporter.__new__(MongoDBTraceExporter)
    exporter._service_name = 'svc'
    exporter._queue = Queue(maxsize=10)
    exporter._stop_event = MagicMock()

    exporter.export([child])

    collection, doc = exporter._queue.get_nowait()
    assert collection == "t1"
    assert doc["Baggage"]["TenantId"] == "t1"
    assert not [k for k in doc["Attributes"] if k.startswith("baggage.")]


def test_asgi_send_span_of_a_tenant_request_goes_to_the_tenant(spans):
    provider, exporter = spans
    app = FastAPI()

    @app.middleware("http")
    async def tenant(request, call_next):  # stands in for the tenant middleware
        Activity.set_current_property("baggage.TenantId", "t1")
        return await call_next(request)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    try:
        assert TestClient(app).get("/ping").status_code == 200
    finally:
        FastAPIInstrumentor.uninstrument_app(app)

    send_spans = [s for s in exporter.get_finished_spans() if s.name.endswith("http send")]
    assert send_spans, [s.name for s in exporter.get_finished_spans()]
    assert [s.attributes.get("baggage.TenantId") for s in send_spans] == ["t1"] * len(send_spans)


@patch(TR + 'get_blocks_secret')
@patch(TR + 'MongoDBTraceExporter')
@patch(TR + 'BatchSpanProcessor')
@patch(TR + 'Resource')
@patch(TR + 'TracerProvider')
@patch(TR + 'trace')
def test_configure_tracing_adds_baggage_processor_before_the_batch_processor(
    mock_trace, mock_tp, mock_res, mock_bsp, mock_exp, mock_gs
):
    tracing.configure_tracing()

    calls = mock_trace.get_tracer_provider.return_value.add_span_processor.call_args_list
    assert len(calls) == 2
    assert isinstance(calls[0].args[0], tracing.BaggageSpanProcessor)
    assert calls[1].args[0] is mock_bsp.return_value
