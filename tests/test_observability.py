"""Observability tests: the /metrics endpoint, the JSON log formatter, and the
tracing no-op path."""

import json
import logging

from fastapi import FastAPI
from httpx import AsyncClient

from app.config import Settings
from app.logging_config import JsonFormatter, request_id_var
from app.tracing import setup_tracing


async def test_metrics_endpoint_exposes_prometheus(client: AsyncClient) -> None:
    await client.get("/health")  # generate one recorded request

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")

    body = resp.text
    assert "# TYPE http_requests_total counter" in body
    assert "# TYPE http_request_duration_seconds histogram" in body
    assert "http_requests_in_flight" in body
    assert 'route="/health"' in body  # the route TEMPLATE, not a raw path


def test_json_formatter_includes_request_id() -> None:
    request_id_var.set("rid-123")
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.request_id = request_id_var.get()  # the RequestIdFilter does this in the app

    data = json.loads(JsonFormatter().format(record))
    assert data["message"] == "hello world"
    assert data["level"] == "INFO"
    assert data["request_id"] == "rid-123"


def test_setup_tracing_is_noop_when_disabled() -> None:
    # otel isn't installed in the base env; with OTEL_ENABLED off this must neither
    # import opentelemetry nor raise.
    setup_tracing(FastAPI(), Settings(otel_enabled=False))
