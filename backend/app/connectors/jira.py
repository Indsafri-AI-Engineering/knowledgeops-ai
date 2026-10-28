import json
import os
from pathlib import Path
import tempfile
import threading
import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from backend.app.connectors.base import ConnectorMetadata

ISSUES_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "fictional_demo"
    / "jira_issues"
    / "issues.json"
)
AllowedPriority = Literal["Low", "Medium", "High"]
CREATED_ISSUES_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "runtime"
    / "jira_created_issues.json"
)
_CREATED_ISSUES_LOCK = threading.RLock()


class DemoIssue(BaseModel):
    key: str
    project: str
    issue_type: Literal["Bug", "Task"]
    summary: str
    description: str
    status: str
    priority: AllowedPriority
    assignee_team: str


class JiraProposalInput(BaseModel):
    project: Literal["DEMO"] = "DEMO"
    summary: str = Field(min_length=8, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    priority: AllowedPriority = "Medium"
    assignee_team: Literal["IT Support", "AI Team"] = "IT Support"


class JiraDemoConnector:
    metadata = ConnectorMetadata(connector="fictional_jira_demo")

    def __init__(
        self,
        issues_path: Path = ISSUES_PATH,
        created_issues_path: Path | None = None,
    ) -> None:
        configured_created_path = os.getenv("JIRA_CREATED_ISSUES_PATH")
        self._created_issues_path = created_issues_path or (
            Path(configured_created_path)
            if configured_created_path
            else CREATED_ISSUES_PATH
        )
        try:
            payload: Any = json.loads(issues_path.read_text(encoding="utf-8"))
            issues = payload["issues"]
            if not isinstance(issues, list):
                raise ValueError("issues must be a list")
            self._issues = [DemoIssue.model_validate(item) for item in issues]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValidationError) as error:
            raise ValueError(f"Invalid fictional Jira fixture: {issues_path}") from error

    def search(self, query: str = "", limit: int = 20) -> list[DemoIssue]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        with _CREATED_ISSUES_LOCK:
            created = self._read_created_issues()
        issues = [*self._issues, *created]
        wants_open = bool(re.search(r"\bopen\b", query, re.IGNORECASE))
        ignored_terms = {
            "a", "all", "are", "assigned", "by", "for", "in", "issues",
            "issue", "jira", "list", "me", "open", "show", "team", "the",
            "to", "what", "which",
        }
        terms = [
            term.casefold()
            for term in re.findall(r"[a-z0-9-]+", query)
            if term.casefold() not in ignored_terms
        ]
        if not terms and not wants_open:
            return issues[:limit]
        return [
            issue
            for issue in issues
            if (not wants_open or issue.status.casefold() == "open")
            and all(
                term in " ".join(
                    (
                        issue.key,
                        issue.project,
                        issue.summary,
                        issue.description,
                        issue.status,
                        issue.assignee_team,
                    )
                ).casefold()
                for term in terms
            )
        ][:limit]

    def create_issue(
        self,
        proposal_id: UUID,
        proposal: JiraProposalInput,
    ) -> DemoIssue:
        with _CREATED_ISSUES_LOCK:
            payload = self._read_created_payload()
            existing = next(
                (
                    item
                    for item in payload
                    if item.get("proposal_id") == str(proposal_id)
                ),
                None,
            )
            if existing is not None:
                return DemoIssue.model_validate(existing["issue"])

            next_number = 201 + len(payload)
            issue = DemoIssue(
                key=f"DEMO-{next_number}",
                project=proposal.project,
                issue_type="Bug",
                summary=proposal.summary,
                description=proposal.description,
                status="Open",
                priority=proposal.priority,
                assignee_team=proposal.assignee_team,
            )
            payload.append(
                {"proposal_id": str(proposal_id), "issue": issue.model_dump(mode="json")}
            )
            self._write_created_payload(payload)
            return issue

    def _read_created_payload(self) -> list[dict[str, Any]]:
        if not self._created_issues_path.exists():
            return []
        payload = json.loads(self._created_issues_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(
                f"Created Jira issue store must contain a JSON array: {self._created_issues_path}"
            )
        return payload

    def _read_created_issues(self) -> list[DemoIssue]:
        return [
            DemoIssue.model_validate(item["issue"])
            for item in self._read_created_payload()
        ]

    def _write_created_payload(self, payload: list[dict[str, Any]]) -> None:
        self._created_issues_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._created_issues_path.parent,
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(payload, temp_file, ensure_ascii=False, indent=2)
            os.replace(temp_path, self._created_issues_path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
