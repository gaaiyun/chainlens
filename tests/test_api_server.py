from __future__ import annotations

import json
from threading import Event
from time import perf_counter

import pytest
from fastapi.testclient import TestClient

import api_server
from api_server import allowed_origins, app, sanitize_json
from chainlens.agents.autonomous import AutonomousAnalysisError
from chainlens.agents.llm import LLMConfigurationError
from chainlens.agents.orchestrator import ChainLensOrchestrator
from chainlens.warehouse.access import Warehouse


class FakeLLM:
    def complete(self, messages, **_: object) -> str:
        return json.dumps(
            {
                "title": "企业经营状态分布",
                "sql": (
                    "SELECT status, count(DISTINCT eid) AS enterprise_count "
                    "FROM v_enterprise GROUP BY status ORDER BY enterprise_count DESC"
                ),
                "chart": {
                    "kind": "bar",
                    "x": "status",
                    "y": "enterprise_count",
                    "title": "企业经营状态分布",
                },
            },
            ensure_ascii=False,
        )


@pytest.fixture
def local_runtime(monkeypatch):
    runtime = ChainLensOrchestrator(Warehouse(), autonomous_llm=FakeLLM())
    monkeypatch.setattr(api_server, "orchestrator", runtime)
    try:
        yield runtime
    finally:
        runtime.close()


def test_query_api_returns_evidence_and_tables(local_runtime) -> None:
    client = TestClient(app)

    response = client.post(
        "/api/query",
        json={"question": "哪些企业有真实中标能力但没有融资记录"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "financing"
    assert body["findings"]
    assert body["evidence"]
    assert "financing_gap" in body["tables"]


def test_health_reports_active_database_backend(local_runtime) -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["database"] in {"duckdb", "mysql"}


def test_readiness_and_query_report_initializing_state(monkeypatch) -> None:
    monkeypatch.setattr(api_server, "orchestrator", None)
    monkeypatch.setattr(api_server, "initialization_status", "initializing")
    monkeypatch.setattr(api_server, "initialization_error", None)
    client = TestClient(app)

    health_response = client.get("/health")
    ready_response = client.get("/ready")
    query_response = client.post("/api/query", json={"question": "统计经营状态分布"})

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "initializing"
    assert ready_response.status_code == 503
    assert ready_response.json()["error_type"] == "data_initializing"
    assert query_response.status_code == 503
    assert query_response.json()["error_type"] == "data_initializing"


def test_lifespan_does_not_block_health_while_runtime_initializes(monkeypatch) -> None:
    started = Event()
    release = Event()

    def slow_initialization() -> None:
        started.set()
        release.wait(timeout=3)

    monkeypatch.setattr(api_server, "orchestrator", None)
    monkeypatch.setattr(api_server, "initialization_status", "initializing")
    monkeypatch.setattr(api_server, "initialization_error", None)
    monkeypatch.setattr(api_server, "initialize_runtime", slow_initialization)

    with TestClient(app) as client:
        assert started.wait(timeout=1)
        before = perf_counter()
        response = client.get("/health")
        elapsed = perf_counter() - before
        release.set()

    assert response.status_code == 200
    assert response.json()["status"] == "initializing"
    assert elapsed < 0.5


def test_query_api_rejects_empty_question() -> None:
    client = TestClient(app)

    response = client.post("/api/query", json={"question": " "})

    assert response.status_code == 422


def test_autonomous_api_returns_sql_safety_and_trace(monkeypatch) -> None:
    runtime = ChainLensOrchestrator(Warehouse(), autonomous_llm=FakeLLM())
    monkeypatch.setattr(api_server, "orchestrator", runtime)
    try:
        response = TestClient(app).post(
            "/api/query",
            json={"question": "统计经营状态分布"},
        )
    finally:
        runtime.close()

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "autonomous"
    assert body["sql"].startswith("SELECT status")
    assert body["safe_sql"].endswith("LIMIT 500")
    assert body["safety"]["is_safe"] is True
    assert body["trace"]
    assert body["report_markdown"]


def test_autonomous_api_returns_structured_error(monkeypatch) -> None:
    class BrokenRuntime:
        def run(self, question: str):
            raise AutonomousAnalysisError("SQL 安全校验连续失败")

    monkeypatch.setattr(api_server, "orchestrator", BrokenRuntime())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/query", json={"question": "任意分析"})

    assert response.status_code == 422
    assert response.json() == {
        "error": "SQL 安全校验连续失败",
        "error_type": "autonomous_analysis_failed",
        "trace": [],
    }


def test_autonomous_api_returns_503_when_llm_is_not_configured(monkeypatch) -> None:
    class MissingLLMRuntime:
        def run(self, question: str):
            raise LLMConfigurationError("未配置 OPENAI_API_KEY")

    monkeypatch.setattr(api_server, "orchestrator", MissingLLMRuntime())

    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/query",
        json={"question": "按企业经济类型分析数量"},
    )

    assert response.status_code == 503
    assert response.json()["error_type"] == "llm_not_configured"


def test_allowed_origins_defaults_to_wildcard(monkeypatch) -> None:
    monkeypatch.delenv("CHAINLENS_ALLOWED_ORIGINS", raising=False)

    assert allowed_origins() == ["*"]


def test_allowed_origins_reads_comma_separated_values(monkeypatch) -> None:
    monkeypatch.setenv(
        "CHAINLENS_ALLOWED_ORIGINS",
        " https://gaaiyun.github.io, http://localhost:4174 ",
    )

    assert allowed_origins() == [
        "https://gaaiyun.github.io",
        "http://localhost:4174",
    ]


def test_sanitize_json_replaces_non_finite_numbers() -> None:
    payload = {
        "nan": float("nan"),
        "nested": [float("inf"), {"value": float("-inf")}],
        "valid": 1.5,
    }

    assert sanitize_json(payload) == {
        "nan": None,
        "nested": [None, {"value": None}],
        "valid": 1.5,
    }
