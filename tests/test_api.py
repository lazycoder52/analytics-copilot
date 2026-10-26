"""Tests for the FastAPI service (/health, /schema, /ask, rate limiting, and error envelopes)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from copilot.api import create_app
from copilot.data import load_database
from copilot.providers import MockProvider, ProviderError


@pytest.fixture(scope="module")
def shared_con():
    con = load_database(harden=True)
    yield con
    con.close()


def test_health_endpoint(shared_con):
    provider = MockProvider(model="mock-test-v1")
    app = create_app(con=shared_con, provider=provider)
    with TestClient(app) as client:
        resp = client.get("/health", headers={"X-Request-ID": "req-health-1"})
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == "req-health-1"
        body = resp.json()
        assert body["status"] == "ok"
        assert body["provider"] == "mock"
        assert body["model"] == "mock-test-v1"
        assert body["tables_loaded"] >= 5


def test_schema_endpoint(shared_con):
    app = create_app(con=shared_con, provider=MockProvider())
    with TestClient(app) as client:
        resp = client.get("/schema")
        assert resp.status_code == 200
        data = resp.json()
        table_names = {t["name"] for t in data["tables"]}
        assert "weekly_store_family_summary" in table_names
        assert "sim_policy_summary" in table_names
        weekly = next(t for t in data["tables"] if t["name"] == "weekly_store_family_summary")
        col_names = [c["name"] for c in weekly["columns"]]
        assert "store_nbr" in col_names
        assert "total_sales" in col_names


def test_ask_endpoint_success_and_refusal(shared_con):
    provider = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "Count all rows in sim_policy_summary.",
                "sql": "SELECT COUNT(*) AS n FROM sim_policy_summary",
            },
            {
                "answerable": False,
                "reason": "Competitor prices are not recorded.",
                "sql": "",
            },
        ]
    )
    app = create_app(con=shared_con, provider=provider)
    with TestClient(app) as client:
        r_ok = client.post(
            "/ask",
            json={"question": "How many rows are in sim_policy_summary?"},
            headers={"X-Request-ID": "ask-123"},
        )
        assert r_ok.status_code == 200
        body_ok = r_ok.json()
        assert body_ok["request_id"] == "ask-123"
        assert body_ok["status"] == "ok"
        assert body_ok["answerable"] is True
        assert body_ok["columns"] == ["n"]
        assert body_ok["rows"] == [[39]]
        assert body_ok["row_count"] == 1

        r_ref = client.post(
            "/ask",
            json={"question": "What were competitor prices in Quito?"},
        )
        assert r_ref.status_code == 200
        body_ref = r_ref.json()
        assert body_ref["status"] == "refused"
        assert body_ref["answerable"] is False
        assert body_ref["sql"] is None
        assert "Competitor prices" in body_ref["answer"]


def test_ask_validation_error_returns_uniform_envelope(shared_con):
    app = create_app(con=shared_con, provider=MockProvider())
    with TestClient(app) as client:
        resp = client.post(
            "/ask",
            json={"question": "hi"},  # min_length=3 violated
            headers={"X-Request-ID": "val-err-1"},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body
        assert body["error"]["request_id"] == "val-err-1"
        assert body["error"]["code"] == "validation_error"


def test_rate_limiting_returns_429_uniform_envelope(shared_con):
    app = create_app(
        con=shared_con,
        provider=MockProvider(),
        rate_limit_max_requests=2,
        rate_limit_window_seconds=60.0,
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        r3 = client.get("/health", headers={"X-Request-ID": "rate-lim-3"})
        assert r3.status_code == 429
        body = r3.json()
        assert body["error"]["request_id"] == "rate-lim-3"
        assert body["error"]["code"] == "rate_limit_exceeded"


def test_provider_exception_returns_502_uniform_envelope(shared_con):
    def _failing_handler(prompt: str, system_prompt: str) -> str:
        raise ProviderError("Upstream LLM timeout")

    app = create_app(con=shared_con, provider=MockProvider(handler=_failing_handler))
    with TestClient(app) as client:
        resp = client.post(
            "/ask",
            json={"question": "How many rows are in sim_policy_summary?"},
            headers={"X-Request-ID": "prov-502"},
        )
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"]["request_id"] == "prov-502"
        assert body["error"]["code"] == "provider_error"
        assert "Upstream LLM timeout" in body["error"]["message"]
