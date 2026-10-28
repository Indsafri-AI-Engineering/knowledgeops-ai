import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

AuditOutcome = Literal["success", "denied", "failure"]
DEFAULT_AUDIT_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "runtime" / "audit.jsonl"
)
_AUDIT_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


class AuditEvent(BaseModel):
    timestamp: datetime
    request_id: UUID
    actor_id: str
    action: str
    resource_type: str
    outcome: AuditOutcome
    metadata: dict[str, str | int | bool]


class AuditLog:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.getenv("AUDIT_LOG_PATH")
        self.path = path or (Path(configured_path) if configured_path else DEFAULT_AUDIT_PATH)

    def record(
        self,
        *,
        request_id: UUID,
        actor_id: str,
        action: str,
        resource_type: str,
        outcome: AuditOutcome,
        metadata: dict[str, str | int | bool] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            timestamp=datetime.now(UTC),
            request_id=request_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            outcome=outcome,
            metadata=metadata or {},
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
        with _AUDIT_LOCK:
            with self.path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(serialized + "\n")
        if action.startswith("auth.") or action.startswith("authorization."):
            from backend.app.threat_detection.monitor import process_audit_event

            try:
                process_audit_event(event)
            except (OSError, RuntimeError, ValueError):
                logger.exception(
                    "Security event monitoring failed for request %s.",
                    request_id,
                )
        return event

    def list_events(self, limit: int = 100) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        with _AUDIT_LOCK:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        events = [AuditEvent.model_validate_json(line) for line in lines if line.strip()]
        events.reverse()
        return events[:limit]
