from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.connectors.jira import JiraDemoConnector, JiraProposalInput
from backend.app.main import app
from conftest import authenticate_as


def test_mock_jira_search_is_scoped_and_searches_created_issues(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JIRA_ACTIONS_PATH", str(tmp_path / "actions.json"))
    monkeypatch.setenv("JIRA_CREATED_ISSUES_PATH", str(tmp_path / "created.json"))

    employee_client = TestClient(app)
    authenticate_as("demo-employee")
    assert (
        employee_client.get("/api/v1/connectors/jira/issues").status_code
        == 403
    )

    it_client = TestClient(app)
    authenticate_as("demo-it")
    search = it_client.get(
        "/api/v1/connectors/jira/issues",
        params={"query": "AI Team"},
    )
    assert search.status_code == 200
    assert search.json()["status"] == "mock"
    assert [issue["key"] for issue in search.json()["issues"]] == ["DEMO-103"]

    created = JiraDemoConnector().create_issue(
        uuid4(),
        JiraProposalInput(
            summary="New fictional service defect",
            description="Reproducible steps and expected result for the demo.",
        ),
    )
    assert created.key == "DEMO-201"
    refreshed = JiraDemoConnector().search("service defect")
    assert any(issue.key == "DEMO-201" for issue in refreshed)


def test_jira_proposal_requires_distinct_authorized_approver(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JIRA_ACTIONS_PATH", str(tmp_path / "actions.json"))
    monkeypatch.setenv("JIRA_CREATED_ISSUES_PATH", str(tmp_path / "created.json"))

    requester = TestClient(app)
    authenticate_as("demo-it")
    proposal_response = requester.post(
        "/api/v1/connectors/jira/proposals",
        json={
            "project": "DEMO",
            "summary": "Salesforce login error in demo",
            "description": "The sign-in flow displays an error after the MFA step.",
            "priority": "High",
            "assignee_team": "IT Support",
        },
    )
    assert proposal_response.status_code == 200
    proposal = proposal_response.json()["proposal"]
    assert proposal["status"] == "proposed"
    assert proposal["issue_key"] is None

    self_approval = requester.post(
        f"/api/v1/connectors/jira/proposals/{proposal['action_id']}/approve"
    )
    assert self_approval.status_code == 403

    manager = TestClient(app)
    authenticate_as("demo-manager")
    pending = manager.get("/api/v1/connectors/jira/proposals")
    assert pending.status_code == 200
    assert [item["action_id"] for item in pending.json()] == [proposal["action_id"]]

    approved = manager.post(
        f"/api/v1/connectors/jira/proposals/{proposal['action_id']}/approve"
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["action"]["status"] == "completed"
    assert body["action"]["requester_id"] == "demo-it"
    assert body["action"]["approver_id"] == "demo-manager"
    assert body["issue"]["key"] == "DEMO-201"
    assert body["issue"]["status"] == "Open"
    assert body["notification"]["status"] == "simulated"
    assert body["notification"]["destination"] == "fictional IT Support queue"

    duplicate_approval = manager.post(
        f"/api/v1/connectors/jira/proposals/{proposal['action_id']}/approve"
    )
    assert duplicate_approval.status_code == 409

    issues = manager.get(
        "/api/v1/connectors/jira/issues",
        params={"query": "Salesforce login error in demo"},
    )
    assert any(issue["key"] == "DEMO-201" for issue in issues.json()["issues"])


def test_jira_proposal_validation_rejects_unapproved_project_and_fields(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JIRA_ACTIONS_PATH", str(tmp_path / "actions.json"))

    client = TestClient(app)
    authenticate_as("demo-it")

    response = client.post(
        "/api/v1/connectors/jira/proposals",
        json={
            "project": "PROD",
            "summary": "Invalid project proposal",
            "description": "This project must be rejected by validation.",
            "priority": "Critical",
            "assignee_team": "Unknown",
        },
    )
    assert response.status_code == 422
