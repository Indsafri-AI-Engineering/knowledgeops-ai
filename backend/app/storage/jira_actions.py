import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel

from backend.app.connectors.jira import JiraProposalInput

ProposalStatus = Literal["proposed", "approved", "completed"]
_ACTION_LOCK = threading.RLock()


class JiraAction(BaseModel):
    action_id: UUID
    requester_id: str
    proposal: JiraProposalInput
    status: ProposalStatus = "proposed"
    created_at: datetime
    approver_id: str | None = None
    approved_at: datetime | None = None
    issue_key: str | None = None
    notification_status: Literal["simulated"] | None = None


class JiraActionStore:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.getenv("JIRA_ACTIONS_PATH")
        self.path = path or (
            Path(configured_path)
            if configured_path
            else Path(__file__).resolve().parents[3]
            / "data"
            / "runtime"
            / "jira_actions.json"
        )

    def _read(self) -> dict[str, JiraAction]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Jira action store must contain a JSON object: {self.path}")
        return {key: JiraAction.model_validate(value) for key, value in payload.items()}

    def _write(self, actions: dict[str, JiraAction]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(
                    {
                        key: action.model_dump(mode="json")
                        for key, action in actions.items()
                    },
                    temp_file,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def create(self, requester_id: str, proposal: JiraProposalInput) -> JiraAction:
        with _ACTION_LOCK:
            actions = self._read()
            action = JiraAction(
                action_id=uuid4(),
                requester_id=requester_id,
                proposal=proposal,
                created_at=datetime.now(UTC),
            )
            actions[str(action.action_id)] = action
            self._write(actions)
            return action

    def get(self, action_id: UUID) -> JiraAction | None:
        with _ACTION_LOCK:
            return self._read().get(str(action_id))

    def list_pending(self) -> list[JiraAction]:
        with _ACTION_LOCK:
            return [
                action
                for action in self._read().values()
                if action.status == "proposed"
            ]

    def save(self, action: JiraAction) -> None:
        with _ACTION_LOCK:
            actions = self._read()
            if str(action.action_id) not in actions:
                raise KeyError("Jira action does not exist.")
            actions[str(action.action_id)] = action
            self._write(actions)
