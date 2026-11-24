import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from starlette.requests import Request

from blocks_genesis._middlewares.tenant_middleware import TenantValidationMiddleware, _route_path

T = "blocks_genesis._middlewares.tenant_middleware."


def _enabled_tenant():
    return MagicMock(is_disabled=False, is_root_tenant=False, tenant_id="tid", applications=[])


def _server_span(path):
    """Serve one request through an instrumented app and return (status code, server span)."""
    app = FastAPI()
    app.add_middleware(TenantValidationMiddleware)

    @app.get("/api/fail")
    async def fail():
        return Response(status_code=500)

    @app.get("/api/missing")
    async def missing():
        return Response(status_code=404)

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    try:
        with patch(T + "get_tenant_service") as mock_gts:
            mock_gts.return_value.get_tenant = AsyncMock(return_value=_enabled_tenant())
            status = TestClient(app).get(path, headers={"x-blocks-key": "key"}).status_code
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        provider.shutdown()
    server = [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert len(server) == 1, [s.name for s in exporter.get_finished_spans()]
    return status, server[0]


def test_server_error_marks_the_server_span_error():
    status, span = _server_span("/api/fail")
    assert status == 500
    assert span.status.status_code == StatusCode.ERROR


def test_client_error_leaves_the_server_span_unset():
    status, span = _server_span("/api/missing")
    assert status == 404
    assert span.status.status_code == StatusCode.UNSET


def test_non_2xx_logs_no_invalid_attribute_warning(caplog):
    caplog.set_level(logging.WARNING, logger="opentelemetry")
    status, _ = _server_span("/api/missing")
    assert status == 404
    assert not [r.getMessage() for r in caplog.records if "invalid key" in r.getMessage()]


def _request(path, root):
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "root_path": root,
        "headers": [(b"x-blocks-key", b"key")],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
    })


async def _dispatch(path, root):
    """Dispatch one request; return (get_tenant mock, Activity mock, call_next mock, request)."""
    with patch(T + "get_tenant_service") as mock_gts, \
            patch(T + "Activity") as mock_activity, \
            patch(T + "BlocksContextManager") as mock_ctx:
        mock_ctx.is_localhost_host.return_value = False
        mock_ctx.resolve_application_domain.return_value = "app"
        mock_ctx.create.return_value = MagicMock()
        get_tenant = AsyncMock(return_value=_enabled_tenant())
        mock_gts.return_value.get_tenant = get_tenant
        mw = TenantValidationMiddleware(MagicMock())
        mw._is_valid_origin_or_referer = MagicMock(return_value=True)
        call_next = AsyncMock(return_value=MagicMock(status_code=200, headers={}, body_iterator=None))
        request = _request(path, root)
        await mw.dispatch(request, call_next)
    return get_tenant, mock_activity, call_next, request


def _assert_resolved(get_tenant, mock_activity):
    get_tenant.assert_awaited_once_with("key")
    mock_activity.set_current_property.assert_any_call("baggage.TenantId", "tid")


def _assert_not_validated(get_tenant, call_next, request):
    get_tenant.assert_not_awaited()
    call_next.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_api_path_under_root_path_resolves_the_tenant():
    get_tenant, mock_activity, _, _ = await _dispatch("/agents/api/x", "/agents")
    _assert_resolved(get_tenant, mock_activity)


@pytest.mark.asyncio
async def test_api_path_without_root_path_resolves_the_tenant():
    get_tenant, mock_activity, _, _ = await _dispatch("/api/x", "")
    _assert_resolved(get_tenant, mock_activity)


@pytest.mark.asyncio
async def test_gateway_stripped_path_with_root_path_resolves_the_tenant():
    get_tenant, mock_activity, _, _ = await _dispatch("/api/x", "/agents")
    _assert_resolved(get_tenant, mock_activity)


@pytest.mark.asyncio
async def test_root_path_is_cut_only_on_a_segment_boundary():
    get_tenant, _, call_next, request = await _dispatch("/agentsx/api/x", "/agents")
    _assert_not_validated(get_tenant, call_next, request)


@pytest.mark.asyncio
async def test_non_api_path_under_root_path_is_not_validated():
    get_tenant, _, call_next, request = await _dispatch("/agents/ping", "/agents")
    _assert_not_validated(get_tenant, call_next, request)


@pytest.mark.asyncio
async def test_root_path_equal_to_included_prefix_still_validates():
    get_tenant, mock_activity, _, _ = await _dispatch("/api/x", "/api")
    _assert_resolved(get_tenant, mock_activity)


@pytest.mark.parametrize("path, root, expected", [
    ("/a/api", "/a", "/api"),
    ("/a", "/a", "/"),
    ("/ab/api", "/a", "/ab/api"),
    ("/api", "", "/api"),
    ("/a/api", "/a/", "/api"),
])
def test_route_path_helper(path, root, expected):
    assert _route_path({"path": path, "root_path": root}) == expected
