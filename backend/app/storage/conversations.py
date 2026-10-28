import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from backend.app.api.v1.chat_models import SourceCitation

MAX_CONVERSATION_TURNS = 20
_STORE_LOCK = threading.RLock()


class ConversationTurn(BaseModel):
    question: str
    answer: str
    intent: str
    sources: list[SourceCitation] = Field(default_factory=list)


class Conversation(BaseModel):
    conversation_id: UUID
    owner_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)


@runtime_checkable
class ConversationRepository(Protocol):
    def create(self, conversation_id: UUID, owner_id: str) -> Conversation: ...

    def get(self, conversation_id: UUID, owner_id: str) -> Conversation | None: ...

    def append(
        self,
        conversation_id: UUID,
        owner_id: str,
        turn: ConversationTurn,
    ) -> Conversation | None: ...


class CorruptConversationStoreError(ValueError):
    """Raised when persisted conversation JSON cannot be safely validated."""


class ConversationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(
            os.getenv(
                "CONVERSATION_STORE_PATH",
                str(Path(__file__).resolve().parents[3] / "data" / "runtime" / "conversations.json"),
            )
        )

    def _read(self) -> dict[str, Conversation]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CorruptConversationStoreError(
                f"Conversation store contains invalid JSON: {self.path}"
            ) from error
        if not isinstance(payload, dict):
            raise CorruptConversationStoreError(
                f"Conversation store must contain a JSON object: {self.path}"
            )
        try:
            return {
                key: Conversation.model_validate(value)
                for key, value in payload.items()
            }
        except ValidationError as error:
            raise CorruptConversationStoreError(
                f"Conversation store contains an invalid record: {self.path}"
            ) from error

    def _write(self, conversations: dict[str, Conversation]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(
                    {
                        key: conversation.model_dump(mode="json")
                        for key, conversation in conversations.items()
                    },
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def create(self, conversation_id: UUID, owner_id: str) -> Conversation:
        key = str(conversation_id)
        with _STORE_LOCK:
            conversations = self._read()
            if key in conversations:
                raise ValueError("Conversation ID already exists.")
            conversation = Conversation(conversation_id=conversation_id, owner_id=owner_id)
            conversations[key] = conversation
            self._write(conversations)
            return conversation

    def get(self, conversation_id: UUID, owner_id: str) -> Conversation | None:
        with _STORE_LOCK:
            conversation = self._read().get(str(conversation_id))
            if conversation is None or conversation.owner_id != owner_id:
                return None
            return conversation

    def append(
        self,
        conversation_id: UUID,
        owner_id: str,
        turn: ConversationTurn,
    ) -> Conversation | None:
        with _STORE_LOCK:
            conversations = self._read()
            conversation = conversations.get(str(conversation_id))
            if conversation is None or conversation.owner_id != owner_id:
                return None
            conversation.turns.append(turn)
            conversation.turns = conversation.turns[-MAX_CONVERSATION_TURNS:]
            conversations[str(conversation_id)] = conversation
            self._write(conversations)
            return conversation


def get_conversation_repository() -> ConversationRepository:
    return ConversationStore()
