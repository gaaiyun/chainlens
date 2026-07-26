from __future__ import annotations

from fastapi.testclient import TestClient

from api_server import allowed_origins, app, sanitize_json


def test_query_api_returns_evidence_and_tables() -> None:
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


def test_health_reports_active_database_backend() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] in {"duckdb", "mysql"}


def test_query_api_rejects_empty_question() -> None:
    client = TestClient(app)

    response = client.post("/api/query", json={"question": " "})

    assert response.status_code == 422


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
