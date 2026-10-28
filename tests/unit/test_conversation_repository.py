import json
from uuid import uuid4

import pytest

from backend.app.storage.conversations import (
    ConversationRepository,
    ConversationStore,
    CorruptConversationStoreError,
    get_conversation_repository,
)


def test_missing_conversation_file_starts_empty_and_creates_record(tmp_path) -> None:
    path = tmp_path / "nested" / "conversations.json"
    store = ConversationStore(path)
    conversation_id = uuid4()

    assert store.get(conversation_id, "synthetic-user") is None
    created = store.create(conversation_id, "synthetic-user")

    assert created.conversation_id == conversation_id
    assert store.get(conversation_id, "synthetic-user") == created
    assert json.loads(path.read_text(encoding="utf-8"))[str(conversation_id)][
        "owner_id"
    ] == "synthetic-user"


def test_duplicate_conversation_id_does_not_overwrite_existing_record(
    tmp_path,
) -> None:
    path = tmp_path / "conversations.json"
    store = ConversationStore(path)
    conversation_id = uuid4()
    store.create(conversation_id, "original-owner")
    original_content = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        store.create(conversation_id, "different-owner")

    assert path.read_text(encoding="utf-8") == original_content
    assert store.get(conversation_id, "original-owner") is not None
    assert store.get(conversation_id, "different-owner") is None


@pytest.mark.parametrize(
    "content",
    [
        "{invalid",
        b"\xff\xfe",
        json.dumps({"conversation-id": {"owner_id": "missing required fields"}}),
        json.dumps([]),
    ],
)
def test_corrupt_conversation_file_fails_explicitly_without_overwrite(
    tmp_path,
    content: str | bytes,
) -> None:
    path = tmp_path / "conversations.json"
    original_content = (
        content if isinstance(content, bytes) else content.encode("utf-8")
    )
    path.write_bytes(original_content)
    store = ConversationStore(path)

    with pytest.raises(CorruptConversationStoreError):
        store.create(uuid4(), "synthetic-user")

    assert path.read_bytes() == original_content


def test_conversation_store_is_provided_behind_repository_interface(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CONVERSATION_STORE_PATH", str(tmp_path / "conversations.json"))

    repository = get_conversation_repository()

    assert isinstance(repository, ConversationRepository)
