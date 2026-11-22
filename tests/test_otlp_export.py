import logging
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace import TracerProvider

from blocks_genesis._lmt import log_config, otlp, tracing

TR = 'blocks_genesis._lmt.tracing.'
LC = 'blocks_genesis._lmt.log_config.'


@pytest.fixture(autouse=True)
def _no_otlp_env(monkeypatch):
    monkeypatch.delenv(otlp.ENDPOINT_ENV, raising=False)
    monkeypatch.delenv(otlp.PROTOCOL_ENV, raising=False)


@pytest.mark.parametrize('value, expected', [(None, False), ('', False), ('   ', False), ('http://otel-lgtm:4317', True)])
def test_otlp_enabled_only_when_endpoint_is_non_empty(monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv(otlp.ENDPOINT_ENV, value)
    assert otlp.otlp_enabled() is expected


@pytest.mark.parametrize('protocol, module', [
    (None, 'grpc'), ('grpc', 'grpc'), ('http/protobuf', 'http'),
])
def test_exporters_follow_the_protocol_variable(monkeypatch, protocol, module):
    if protocol:
        monkeypatch.setenv(otlp.PROTOCOL_ENV, protocol)
    monkeypatch.setenv(otlp.ENDPOINT_ENV, 'http://localhost:4317')
    for exporter in (otlp.create_span_exporter(), otlp.create_metric_exporter(), otlp.create_log_exporter()):
        assert f'.proto.{module}.' in type(exporter).__module__
        exporter.shutdown()


def _configure_tracing():
    secret = MagicMock(ServiceName='svc')
    with patch(TR + 'get_blocks_secret', return_value=secret), \
            patch(TR + 'MongoDBTraceExporter'), \
            patch(TR + 'trace') as mock_trace, \
            patch(TR + 'metrics') as mock_metrics:
        provider = TracerProvider()
        mock_trace.get_tracer_provider.return_value = provider
        with patch.object(provider, 'add_span_processor', wraps=provider.add_span_processor) as add:
            tracing.configure_tracing()
    return add, mock_metrics


def test_tracing_has_no_otlp_exporter_or_meter_provider_without_the_variable():
    add, mock_metrics = _configure_tracing()
    assert add.call_count == 1
    mock_metrics.set_meter_provider.assert_not_called()


def test_tracing_adds_otlp_span_exporter_and_meter_provider_when_the_variable_is_set(monkeypatch):
    monkeypatch.setenv(otlp.ENDPOINT_ENV, 'http://localhost:4317')
    add, mock_metrics = _configure_tracing()
    assert add.call_count == 2
    mock_metrics.set_meter_provider.assert_called_once()


def _configure_logger():
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    try:
        with patch(LC + 'MongoHandler') as mongo, patch(LC + 'get_blocks_secret', return_value=MagicMock(ServiceName='svc')):
            mongo.return_value = logging.NullHandler()
            log_config.configure_logger()
            return root.handlers[:]
    finally:
        root.handlers[:] = saved
        root.setLevel(level)


def test_logger_has_no_otlp_handler_without_the_variable():
    assert len(_configure_logger()) == 2


def test_logger_adds_otlp_handler_when_the_variable_is_set(monkeypatch):
    from opentelemetry.sdk._logs import LoggingHandler

    monkeypatch.setenv(otlp.ENDPOINT_ENV, 'http://localhost:4317')
    handlers = _configure_logger()
    assert len(handlers) == 3
    otlp_handlers = [h for h in handlers if isinstance(h, LoggingHandler)]
    assert len(otlp_handlers) == 1
    assert otlp_handlers[0].filters, 'the context filter must run first so the tenant id is exported'