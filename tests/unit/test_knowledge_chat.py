from fastapi.testclient import TestClient
import pytest
from langchain_core.messages import AIMessage

from backend.app.main import app
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.ingestion import load_knowledge_chunks


@pytest.fixture(autouse=True)
def isolate_chat_audit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JIRA_ACTIONS_PATH", str(tmp_path / "jira_actions.json"))
    monkeypatch.setenv(
        "JIRA_CREATED_ISSUES_PATH",
        str(tmp_path / "jira_created_issues.json"),
    )


def test_ingestion_loads_cited_demo_documents() -> None:
    chunks = load_knowledge_chunks()
    assert chunks
    assert any(chunk.document_id == "demo-hr-annual-leave" for chunk in chunks)
    assert all(chunk.text and chunk.source_path for chunk in chunks)
    salesforce_chunk = next(
        chunk for chunk in chunks if chunk.document_id == "demo-it-salesforce-login"
    )
    assert salesforce_chunk.owner == "Fictional IT Service Desk"
    assert salesforce_chunk.version == "demo-v2"
    assert salesforce_chunk.effective_date == "2026-01-15"
    assert salesforce_chunk.next_review == "2027-01-15"
    assert "fictional" in (salesforce_chunk.environment or "").lower()


def test_ingestion_keeps_new_metadata_optional(tmp_path) -> None:
    source = tmp_path / "minimal.md"
    source.write_text(
        "---\n"
        "document_id: minimal-doc\n"
        "title: Minimal Document\n"
        "source: fictional_test\n"
        "access_scope: general\n"
        "---\n"
        "\n"
        "# Content\n"
        "\n"
        "Synthetic content.\n",
        encoding="utf-8",
    )

    chunk = load_knowledge_chunks(tmp_path)[0]

    assert chunk.owner is None
    assert chunk.version is None
    assert chunk.effective_date is None
    assert chunk.next_review is None
    assert chunk.environment is None


def test_default_index_loads_fictional_scoped_demo_documents(monkeypatch) -> None:
    monkeypatch.delenv("KNOWLEDGE_SEED_DIRECTORY", raising=False)
    monkeypatch.setenv("RAG_BACKEND", "local")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()

    try:
        index = get_knowledge_index()
        hr_results = index.search(
            "How many working days of annual leave does a full-time employee receive?",
            {"hr"},
        )
        unauthorized_results = index.search(
            "How many working days of annual leave does a full-time employee receive?",
            {"general", "it"},
        )

        assert any(
            result.chunk.document_id == "northstar-hr-leave-and-wellbeing"
            for result in hr_results
        )
        assert all(
            result.chunk.document_id != "northstar-hr-leave-and-wellbeing"
            for result in unauthorized_results
        )
        assert {
            chunk.document_id for chunk in index.chunks
        } >= {
            "northstar-general-acceptable-use",
            "northstar-hr-leave-and-wellbeing",
            "northstar-it-account-access",
            "northstar-recruitment-campaign-process",
        }

        question = (
            "How many working days of annual leave does a full-time employee receive?"
        )
        with TestClient(app) as hr_client:
            hr_client.post(
                "/api/v1/auth/demo-login",
                json={"user_id": "demo-hr"},
            )
            hr_response = hr_client.post(
                "/api/v1/chat",
                json={"question": question},
            )
        assert hr_response.status_code == 200
        assert "20 working days" in hr_response.json()["answer"]
        assert any(
            source["document_id"] == "northstar-hr-leave-and-wellbeing"
            for source in hr_response.json()["sources"]
        )

        with TestClient(app) as employee_client:
            employee_client.post(
                "/api/v1/auth/demo-login",
                json={"user_id": "demo-employee"},
            )
            employee_response = employee_client.post(
                "/api/v1/chat",
                json={"question": question},
            )
        assert employee_response.status_code == 200
        assert all(
            source["document_id"] != "northstar-hr-leave-and-wellbeing"
            for source in employee_response.json()["sources"]
        )
        assert "20 working days" not in employee_response.json()["answer"]
    finally:
        get_knowledge_index.cache_clear()


def test_versioned_health_endpoint_returns_success() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_returns_grounded_answer_and_source(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-hr"})

    response = client.post(
        "/api/v1/chat",
        json={"question": "How many annual leave days do employees receive?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "20 working days" in body["answer"]
    assert body["intent"] == "hr.policy"
    assert body["workflow_status"] == "available"
    assert body["needs_clarification"] is False
    assert body["route_category"] == "knowledge"
    assert body["route_component"] == "hr_knowledge"
    assert body["sources"][0]["document_id"] == "demo-hr-annual-leave"
    assert body["sources"][0]["source_path"] == "hr_policies/annual_leave.md"
    assert body["sources"][0]["owner"] is None
    assert body["sources"][0]["version"] is None


def test_chat_routes_analysis_to_grounded_analytical_generation(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    captured: dict[str, object] = {}

    def fake_generate(results, question, *, analytical=False):
        captured["results"] = results
        captured["question"] = question
        captured["analytical"] = analytical
        return "Evidence-bounded analysis [S1]."

    monkeypatch.setattr(
        "backend.app.orchestration.service.generate_grounded_answer",
        fake_generate,
    )
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

    response = client.post(
        "/api/v1/chat",
        json={"question": "Summarize the customer data handling policy."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "knowledge.analysis"
    assert body["route_category"] == "analytical"
    assert body["route_component"] == "knowledge_analytics"
    assert body["sources"]
    assert body["answer"] == "Evidence-bounded analysis [S1]."
    assert captured["analytical"] is True


def test_chat_marks_unsupported_action_without_executing_it(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

    response = client.post(
        "/api/v1/chat",
        json={"question": "Send an email to the payroll team."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route_category"] == "unsupported"
    assert body["route_component"] == "unsupported"
    assert body["workflow_status"] == "planned"
    assert body["needs_clarification"] is True
    assert body["sources"] == []
    assert "cannot perform that action" in body["answer"].lower()


def test_chat_uses_local_model_for_retrieved_evidence(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "ollama")
    get_knowledge_index.cache_clear()
    captured_prompts = []

    class FakeChatOllama:
        def __init__(self, **kwargs) -> None:
            assert kwargs["model"] == "llama3.2:3b"

        def invoke(self, prompt):
            captured_prompts.extend(prompt.to_messages())
            return AIMessage(content="Employees receive 20 working days [S1].")

    monkeypatch.setattr(
        "backend.app.knowledge.generation.create_chat_model",
        lambda: FakeChatOllama(model="llama3.2:3b"),
    )
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-hr"})

    response = client.post(
        "/api/v1/chat",
        json={"question": "How many annual leave days do employees receive?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Employees receive 20 working days [S1]."
    assert body["sources"][0]["document_id"] == "demo-hr-annual-leave"
    assert "How many annual leave days" in captured_prompts[1].content
    assert "demo-hr-annual-leave" not in captured_prompts[1].content
    assert "20 working days" in captured_prompts[1].content


def test_chat_filters_recruitment_documents_before_retrieval(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

    response = client.post(
        "/api/v1/chat",
        json={"question": "What success fee applies under the recruitment agreement?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert body["needs_clarification"] is True
    assert "9,600" not in body["answer"]


def test_employee_chat_denies_hr_onboarding_without_exposing_sources(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

    response = client.post(
        "/api/v1/chat",
        json={"question": "What steps are included in the employee onboarding checklist?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert body["needs_clarification"] is True
    assert "not authorized" in body["answer"].lower()
    assert "it support runbook" not in body["answer"].lower()
    assert "candidate" not in body["answer"].lower()


def test_salesforce_guided_login_help_uses_fictional_source_and_langchain(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-it"})

    response = client.post(
        "/api/v1/connectors/it/salesforce/login-guide",
        json={"symptom": "mfa_problem"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connector"] == "fictional_it_knowledge"
    assert body["status"] == "mock"
    assert body["execution"] == "local_langchain"
    assert any("Never share a verification code" in step for step in body["steps"])
    assert body["sources"][0]["document_id"] == "demo-it-salesforce-login"
    assert body["sources"][0]["owner"] == "Fictional IT Service Desk"
    assert body["sources"][0]["version"] == "demo-v2"
    assert body["sources"][0]["effective_date"] == "2026-01-15"
    assert body["sources"][0]["next_review"] == "2027-01-15"
    assert "fictional" in body["sources"][0]["environment"].lower()


def test_salesforce_guided_login_help_denies_users_without_it_scope(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-recruiter"})

    response = client.post(
        "/api/v1/connectors/it/salesforce/login-guide",
        json={"symptom": "account_locked"},
    )

    assert response.status_code == 403


def test_salesforce_guided_login_help_validates_symptom(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

    response = client.post(
        "/api/v1/connectors/it/salesforce/login-guide",
        json={"symptom": "reset_account"},
    )

    assert response.status_code == 422


def test_recruiter_can_retrieve_recruitment_agreement(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-recruiter"})

    response = client.post(
        "/api/v1/chat",
        json={"question": "What success fee applies under the recruitment agreement?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "12%" in body["answer"]
    assert body["sources"][0]["document_id"] == "demo-recruitment-agreement"


def test_chat_requires_a_demo_session(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)

    assert client.post("/api/v1/chat", json={"question": "Annual leave?"}).status_code == 401


def test_chat_rejects_empty_question(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

    assert client.post("/api/v1/chat", json={"question": ""}).status_code == 422


def test_chat_accepts_vector_and_hybrid_modes(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

    for mode in ("vector", "keyword", "hybrid"):
        response = client.post(
            "/api/v1/chat",
            json={
                "question": "How many annual leave days do employees receive?",
                "retrieval_mode": mode,
            },
        )
        assert response.status_code == 200
        assert response.json()["retrieval_mode"] == mode

    invalid_mode = client.post(
        "/api/v1/chat",
        json={
            "question": "How many annual leave days do employees receive?",
            "retrieval_mode": "semantic",
        },
    )
    assert invalid_mode.status_code == 422


def test_chat_is_stateless_and_does_not_persist_prior_questions_or_answers(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    monkeypatch.setenv(
        "CONVERSATION_STORE_PATH",
        str(tmp_path / "conversations.json"),
    )
    captured_questions: list[str] = []

    def fake_orchestrate(question, route, user, request, index, retrieval_mode):
        from backend.app.orchestration.service import OrchestrationResult

        captured_questions.append(question)
        return OrchestrationResult(
            answer=f"Independent answer for: {question}",
            workflow_status="available",
            sources=[],
            needs_clarification=False,
        )

    monkeypatch.setattr(
        "backend.app.api.v1.chat.orchestrate_request",
        fake_orchestrate,
    )
    get_knowledge_index.cache_clear()
    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "demo-employee"},
        )
        first_question = "How many annual leave days do employees receive?"
        second_question = (
            "What steps should a recruiter follow when screening candidates?"
        )
        first_response = client.post(
            "/api/v1/chat",
            json={"question": first_question},
        )
        second_response = client.post(
            "/api/v1/chat",
            json={"question": second_question},
        )
        old_history_endpoint = client.get(
            "/api/v1/conversations/00000000-0000-0000-0000-000000000001"
        )
        conversation_id_request = client.post(
            "/api/v1/chat",
            json={
                "question": "This field is not accepted.",
                "conversation_id": "00000000-0000-0000-0000-000000000001",
            },
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert captured_questions == [first_question, second_question]
    assert second_response.json()["question"] == second_question
    assert second_response.json()["answer"] == (
        f"Independent answer for: {second_question}"
    )
    assert "history" not in second_response.json()
    assert "conversation_id" not in second_response.json()
    assert old_history_endpoint.status_code == 404
    assert conversation_id_request.status_code == 422
    assert not (tmp_path / "conversations.json").exists()
    audit_contents = audit_path.read_text(encoding="utf-8")
    assert first_question not in audit_contents
    assert second_question not in audit_contents
    assert "Independent answer for:" not in audit_contents


def test_jira_and_threat_intents_are_routed_but_not_executed(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-manager"})

    jira_response = client.post(
        "/api/v1/chat",
        json={"question": "Which open Jira issues are assigned to the AI team?"},
    )
    threat_response = client.post(
        "/api/v1/chat",
        json={"question": "Scan this email for phishing indicators."},
    )

    assert jira_response.json()["intent"] == "jira.search"
    assert jira_response.json()["workflow_status"] == "available"
    assert jira_response.json()["sources"][0]["document_id"] == "DEMO-103"
    assert "No live Jira system was queried" in jira_response.json()["answer"]
    assert threat_response.json()["intent"] == "threat.scan"
    assert threat_response.json()["workflow_status"] == "planned"


def test_faq_suggestions_respect_user_scopes(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    employee_client = TestClient(app)
    employee_client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-employee"},
    )
    employee_faqs = employee_client.get("/api/v1/faqs/suggestions").json()
    assert all(faq["faq_id"] != "recruitment-fee" for faq in employee_faqs)
    assert any(faq["faq_id"] == "annual-leave" for faq in employee_faqs)

    recruiter_client = TestClient(app)
    recruiter_client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-recruiter"},
    )
    recruiter_faqs = recruiter_client.get(
        "/api/v1/faqs/suggestions",
        params={"query": "success fee"},
    ).json()
    assert [faq["faq_id"] for faq in recruiter_faqs] == ["recruitment-fee"]


def test_recruiter_chat_matches_fictional_cvs_with_review_notice(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    client = TestClient(app)
    client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-recruiter"},
    )

    response = client.post(
        "/api/v1/chat",
        json={"question": "How many CVs meet the backend engineer campaign criteria?"},
    )
    body = response.json()

    assert response.status_code == 200
    assert body["intent"] == "recruitment.knowledge"
    assert "1 of 2 fictional CVs" in body["answer"]
    assert "human recruiter must review" in body["answer"]
    assert {source["document_id"] for source in body["sources"]} == {
        "demo-cv-001",
        "demo-cv-002",
    }


def test_recruitment_fee_is_transparent_and_permission_filtered(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()
    recruiter_client = TestClient(app)
    recruiter_client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-recruiter"},
    )

    calculated = recruiter_client.post(
        "/api/v1/connectors/recruitment/success-fee",
        json={"salary": "80000"},
    )
    assert calculated.status_code == 200
    assert calculated.json()["fee"] == "9600.00"
    assert calculated.json()["rate_percent"] == "12"
    assert calculated.json()["formula"] == "salary × rate_percent ÷ 100"
    assert calculated.json()["status"] == "mock"

    chat_response = recruiter_client.post(
        "/api/v1/chat",
        json={"question": "Calculate the success fee for salary 80,000 credits."},
    )
    assert "9,600.00 credits" in chat_response.json()["answer"]
    assert chat_response.json()["sources"][0]["document_id"] == (
        "demo-recruitment-agreement"
    )

    employee_client = TestClient(app)
    employee_client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-employee"},
    )
    assert (
        employee_client.post(
            "/api/v1/connectors/recruitment/success-fee",
            json={"salary": "80000"},
        ).status_code
        == 403
    )
    restricted_chat = employee_client.post(
        "/api/v1/chat",
        json={"question": "What success fee applies under the recruitment agreement?"},
    )
    assert restricted_chat.status_code == 200
    assert restricted_chat.json()["sources"] == []
    assert "12%" not in restricted_chat.json()["answer"]


def test_mock_hr_and_it_connectors_enforce_scopes(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    get_knowledge_index.cache_clear()

    employee_client = TestClient(app)
    employee_client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-employee"},
    )
    leave = employee_client.get("/api/v1/connectors/hr/leave-policy")
    assert leave.status_code == 200
    assert leave.json()["status"] == "mock"
    assert "20 working days" in leave.json()["answer"]
    assert leave.json()["sources"][0]["document_id"] == "demo-hr-annual-leave"

    denied_it = employee_client.post(
        "/api/v1/connectors/it/troubleshooting",
        json={"question": "Salesforce login troubleshooting"},
    )
    assert denied_it.status_code == 403

    it_client = TestClient(app)
    it_client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-it"},
    )
    it = it_client.post(
        "/api/v1/connectors/it/troubleshooting",
        json={"question": "Salesforce login troubleshooting"},
    )
    assert it.status_code == 200
    assert it.json()["status"] == "mock"
    assert it.json()["sources"][0]["document_id"] == "demo-it-salesforce-login"

    security_client = TestClient(app)
    security_client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-security"},
    )
    assert (
        security_client.post(
            "/api/v1/connectors/it/troubleshooting",
            json={"question": "Salesforce login troubleshooting"},
        ).status_code
        == 403
    )


def test_mock_recruitment_campaign_endpoint_is_authorized(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-recruiter"})

    response = client.post(
        "/api/v1/connectors/recruitment/campaigns/backend-engineer/matches"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "mock"
    assert response.json()["matched_count"] == 1
    assert response.json()["human_review_required"] is True

    unknown = client.post(
        "/api/v1/connectors/recruitment/campaigns/unknown/matches"
    )
    assert unknown.status_code == 404


def test_filtered_retrieval_does_not_include_or_score_restricted_documents() -> None:
    from backend.app.knowledge.retrieval import LocalKnowledgeIndex

    index = get_knowledge_index()
    employee_results = index.search(
        "What success fee applies under the recruitment agreement?",
        {"general", "it"},
        mode="hybrid",
    )
    recruiter_results = index.search(
        "What success fee applies under the recruitment agreement?",
        {"general", "it", "recruitment"},
        mode="hybrid",
    )
    visible_index = LocalKnowledgeIndex(
        [chunk for chunk in index.chunks if chunk.access_scope != "recruitment"]
    )
    visible_results = visible_index.search(
        "What success fee applies under the recruitment agreement?",
        {"general", "it"},
        mode="hybrid",
    )

    assert all(result.chunk.access_scope != "recruitment" for result in employee_results)
    assert any(
        result.chunk.document_id == "demo-recruitment-agreement"
        for result in recruiter_results
    )
    assert employee_results == visible_results
