import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx


_PROJECT_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,9}$")
_ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,9}-[1-9][0-9]*$")


class JiraConfigurationError(RuntimeError):
    pass


class JiraRequestError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"Jira returned HTTP {status_code}.")
        self.status_code = status_code


class JiraCloudClient:
    def __init__(self) -> None:
        self._base_url = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")
        self._email = os.getenv("JIRA_EMAIL", "").strip()
        self._api_token = os.getenv("JIRA_API_TOKEN", "").strip()

    @property
    def configured(self) -> bool:
        parsed_url = urlsplit(self._base_url)
        return bool(
            self._email
            and self._api_token
            and parsed_url.scheme == "https"
            and parsed_url.netloc
            and parsed_url.username is None
            and parsed_url.password is None
            and not parsed_url.query
            and not parsed_url.fragment
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._base_url or not self._email or not self._api_token:
            raise JiraConfigurationError(
                "Set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN."
            )
        parsed_url = urlsplit(self._base_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise JiraConfigurationError("JIRA_BASE_URL must use HTTPS.")

        try:
            response = httpx.request(
                method,
                f"{self._base_url}/rest/api/3/{path.lstrip('/')}",
                params=params,
                json=payload,
                auth=(self._email, self._api_token),
                headers={"Accept": "application/json"},
                timeout=15.0,
                follow_redirects=False,
            )
        except httpx.RequestError as error:
            raise JiraRequestError(0) from error
        if not response.is_success:
            raise JiraRequestError(response.status_code)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            result = response.json()
        except ValueError as error:
            raise JiraRequestError(502) from error
        if not isinstance(result, dict):
            raise JiraRequestError(502)
        return result

    def projects(self) -> list[dict[str, str]]:
        result = self._request(
            "GET",
            "project/search",
            params={"maxResults": 50},
        )
        values = result.get("values", [])
        if not isinstance(values, list):
            raise JiraRequestError(502)
        return [
            {"id": str(item["id"]), "key": item["key"], "name": item["name"]}
            for item in values
            if isinstance(item, dict)
            and all(key in item for key in ("id", "key", "name"))
        ]

    def issue_types(self, project_key: str) -> list[dict[str, str]]:
        _validate_project_key(project_key)
        result = self._request(
            "GET",
            f"issue/createmeta/{project_key}/issuetypes",
            params={"maxResults": 100},
        )
        values = result.get("issueTypes", [])
        if not isinstance(values, list):
            raise JiraRequestError(502)
        return [
            {"id": str(item["id"]), "name": item["name"]}
            for item in values
            if isinstance(item, dict) and "id" in item and "name" in item
        ]

    def search_issues(
        self,
        query: str = "",
        project_key: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 50:
            raise ValueError("Issue search limit must be between 1 and 50.")
        clauses: list[str] = []
        if query.strip():
            escaped_query = query.strip().replace("\\", "\\\\").replace('"', '\\"')
            clauses.append(f'text ~ "{escaped_query}"')
        if project_key:
            _validate_project_key(project_key)
            clauses.append(f"project = {project_key}")
        result = self._request(
            "POST",
            "search/jql",
            payload={
                "jql": " AND ".join(clauses) if clauses else "ORDER BY updated DESC",
                "maxResults": limit,
                "fields": [
                    "summary",
                    "description",
                    "status",
                    "priority",
                    "project",
                    "assignee",
                    "issuetype",
                    "updated",
                ],
            },
        )
        issues = result.get("issues", [])
        if not isinstance(issues, list):
            raise JiraRequestError(502)
        return [_issue_summary(issue) for issue in issues if isinstance(issue, dict)]

    def create_issue(
        self,
        *,
        project_key: str,
        issue_type_id: str,
        summary: str,
        description: str,
        priority_name: str | None,
    ) -> dict[str, str]:
        _validate_project_key(project_key)
        fields: dict[str, Any] = {
            "project": {"key": project_key},
            "issuetype": {"id": issue_type_id},
            "summary": summary,
            "description": _adf_document(description),
        }
        if priority_name:
            fields["priority"] = {"name": priority_name}
        result = self._request("POST", "issue", payload={"fields": fields})
        if not all(key in result for key in ("id", "key", "self")):
            raise JiraRequestError(502)
        return {
            "id": str(result["id"]),
            "key": str(result["key"]),
            "url": str(result["self"]),
        }

    def update_issue(
        self,
        issue_key: str,
        *,
        summary: str | None,
        description: str | None,
        priority_name: str | None,
    ) -> None:
        _validate_issue_key(issue_key)
        fields: dict[str, Any] = {}
        if summary is not None:
            fields["summary"] = summary
        if description is not None:
            fields["description"] = _adf_document(description)
        if priority_name is not None:
            fields["priority"] = {"name": priority_name}
        if not fields:
            raise ValueError("At least one issue field must be provided.")
        self._request("PUT", f"issue/{issue_key}", payload={"fields": fields})

    def add_comment(self, issue_key: str, body: str) -> dict[str, str]:
        _validate_issue_key(issue_key)
        result = self._request(
            "POST",
            f"issue/{issue_key}/comment",
            payload={"body": _adf_document(body)},
        )
        if "id" not in result:
            raise JiraRequestError(502)
        return {"id": str(result["id"])}

    def transitions(self, issue_key: str) -> list[dict[str, str]]:
        _validate_issue_key(issue_key)
        result = self._request("GET", f"issue/{issue_key}/transitions")
        values = result.get("transitions", [])
        if not isinstance(values, list):
            raise JiraRequestError(502)
        return [
            {"id": str(item["id"]), "name": item["name"]}
            for item in values
            if isinstance(item, dict) and "id" in item and "name" in item
        ]

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        _validate_issue_key(issue_key)
        if not transition_id.isdigit():
            raise ValueError("Transition ID must be numeric.")
        self._request(
            "POST",
            f"issue/{issue_key}/transitions",
            payload={"transition": {"id": transition_id}},
        )


def _validate_project_key(project_key: str) -> None:
    if not _PROJECT_KEY_PATTERN.fullmatch(project_key):
        raise ValueError("Project key has an invalid format.")


def _validate_issue_key(issue_key: str) -> None:
    if not _ISSUE_KEY_PATTERN.fullmatch(issue_key):
        raise ValueError("Issue key has an invalid format.")


def _adf_document(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _plain_text(value: Any) -> str:
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        return "\n".join(
            text
            for child in value.values()
            if (text := _plain_text(child))
        )
    if isinstance(value, list):
        return "\n".join(text for child in value if (text := _plain_text(child)))
    return ""


def _issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        raise JiraRequestError(502)

    def nested_name(name: str, key: str = "name") -> str | None:
        value = fields.get(name)
        return str(value[key]) if isinstance(value, dict) and value.get(key) else None

    project = fields.get("project")
    assignee = fields.get("assignee")
    return {
        "id": str(issue.get("id", "")),
        "key": str(issue.get("key", "")),
        "summary": str(fields.get("summary", "")),
        "description": _plain_text(fields.get("description")),
        "status": nested_name("status"),
        "priority": nested_name("priority"),
        "project_key": (
            str(project["key"])
            if isinstance(project, dict) and project.get("key")
            else None
        ),
        "assignee": (
            str(assignee["displayName"])
            if isinstance(assignee, dict) and assignee.get("displayName")
            else None
        ),
        "issue_type": nested_name("issuetype"),
        "updated": str(fields.get("updated", "")),
    }
