import json
import logging

from fastapi.testclient import TestClient

from main import app
from observability import JsonFormatter, Metrics, request_id_var

client = TestClient(app)


# ----------------------------------------------------------------- metrics
def test_counters_and_labels():
    m = Metrics()
    m.inc("hits", {"path": "/a"})
    m.inc("hits", {"path": "/a"})
    m.inc("hits", {"path": "/b"})
    snap = m.snapshot()["counters"]
    assert snap['hits{path="/a"}'] == 2
    assert snap['hits{path="/b"}'] == 1


def test_histogram_records_count_sum_and_average():
    m = Metrics()
    for seconds in (0.1, 0.3):
        m.observe("dur", seconds)
    latency = m.snapshot()["latency"]["dur"]
    assert latency["count"] == 2
    assert latency["sum"] == 0.4
    assert latency["avg"] == 0.2


def test_histogram_buckets_are_cumulative():
    m = Metrics()
    m.observe("dur", 0.02)  # falls in every bucket from 0.05 up
    text = m.prometheus()
    assert 'dur{le="0.01"} 0' in text
    assert 'dur{le="0.05"} 1' in text
    assert 'dur{le="+Inf"} 1' in text


def test_prometheus_output_is_well_formed():
    m = Metrics()
    m.inc("http_requests_total", {"method": "GET", "status": "200"})
    text = m.prometheus()
    assert "# TYPE http_requests_total counter" in text
    assert 'http_requests_total{method="GET",status="200"} 1' in text
    assert text.endswith("\n")


# ----------------------------------------------------------------- logging
def test_json_formatter_emits_parseable_lines_with_request_id():
    token = request_id_var.set("abc123")
    try:
        record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello", None, None)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["request_id"] == "abc123"
    assert payload["ts"].endswith("Z")


def test_json_formatter_includes_extra_fields():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "req", None, None)
    record.extra_fields = {"status": 200, "duration_ms": 12.5}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["status"] == 200 and payload["duration_ms"] == 12.5


# ----------------------------------------------------------------- endpoints
def test_request_id_is_returned_and_echoed_when_supplied():
    generated = client.get("/healthz").headers["X-Request-ID"]
    assert len(generated) == 12

    supplied = client.get("/healthz", headers={"X-Request-ID": "trace-me"})
    assert supplied.headers["X-Request-ID"] == "trace-me"


def test_requests_are_counted_by_route_template_not_raw_path():
    # Two different tickers must collapse into one series, or cardinality explodes.
    client.get("/api/prices/SPY?days=5")
    client.get("/api/prices/AGG?days=5")
    text = client.get("/metrics").text
    assert 'path="/api/prices/{ticker}"' in text
    assert "/api/prices/SPY" not in text


def test_metrics_endpoints_expose_request_counts():
    client.get("/healthz")
    text = client.get("/metrics").text
    assert "http_requests_total" in text
    assert "http_request_duration_seconds" in text
    assert "app_uptime_seconds" in text

    snap = client.get("/metrics.json").json()
    assert snap["uptime_seconds"] >= 0
    assert any("http_requests_total" in k for k in snap["counters"])


def test_readyz_reports_each_dependency():
    body = client.get("/readyz").json()
    assert set(body["checks"]) == {"prices", "database", "knowledge_base", "llm"}
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["knowledge_base"]["chunks"] > 0
    assert body["ready"] is True


def test_readyz_reports_503_and_names_the_broken_dependency(monkeypatch):
    import main
    monkeypatch.setattr(main, "_prices", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert body["checks"]["prices"]["ok"] is False
    assert "boom" in body["checks"]["prices"]["error"]
    assert body["checks"]["database"]["ok"] is True  # unaffected deps stay healthy


def test_healthz_stays_dependency_free(monkeypatch):
    # Liveness must not fail just because an upstream is slow or broken.
    import main
    monkeypatch.setattr(main, "_prices", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert client.get("/healthz").status_code == 200


def test_chat_answers_are_counted_by_mode():
    client.post("/api/chat", json={"message": "What is max drawdown?"})
    text = client.get("/metrics").text
    assert "chat_answers_total" in text
