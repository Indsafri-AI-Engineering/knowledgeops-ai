from fastapi.testclient import TestClient

from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.ingestion import load_knowledge_chunks
from backend.app.knowledge.retrieval import LocalKnowledgeIndex
from backend.app.main import app


def test_retrieval_cache_is_partitioned_by_permission_scope() -> None:
    index = LocalKnowledgeIndex(load_knowledge_chunks())
    question = "What recruitment success fee applies?"

    recruiter_results = index.search(
        question,
        {"general", "recruitment"},
        mode="hybrid",
    )
    employee_results = index.search(
        question,
        {"general", "it"},
        mode="hybrid",
    )
    repeated_employee_results = index.search(
        question,
        {"general", "it"},
        mode="hybrid",
    )

    assert any(item.chunk.access_scope == "recruitment" for item in recruiter_results)
    assert all(item.chunk.access_scope != "recruitment" for item in employee_results)
    assert repeated_employee_results == employee_results
    assert index.cache_info()["hits"] == 1


def test_observability_metrics_are_administrator_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_knowledge_index.cache_clear()

    employee = TestClient(app)
    employee.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})
    assert employee.get("/api/v1/observability/metrics").status_code == 403

    admin = TestClient(app)
    admin.post("/api/v1/auth/demo-login", json={"user_id": "demo-admin"})
    metrics = admin.get("/api/v1/observability/metrics")

    assert metrics.status_code == 200
    payload = metrics.json()
    assert "retrieval_cache" in payload
    assert any(item["route"] == "/api/v1/auth/demo-login" for item in payload["requests"])
