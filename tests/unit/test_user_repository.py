import json

import pytest

from backend.app.storage.users import (
    CorruptUserStoreError,
    JsonUserRepository,
    UserRecord,
    UserRepository,
    get_user_repository,
)


def test_missing_user_file_starts_empty_and_persists_records(tmp_path) -> None:
    path = tmp_path / "nested" / "users.json"
    repository = JsonUserRepository(path)
    user = UserRecord(user_id="synthetic-user", display_name="Synthetic User")

    assert repository.get_by_id(user.user_id) is None
    assert repository.get_all() == []
    assert repository.create(user) == user
    assert repository.get_by_id(user.user_id) == user
    assert repository.get_all() == [user]
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "synthetic-user": {
            "user_id": "synthetic-user",
            "display_name": "Synthetic User",
        }
    }


def test_duplicate_user_id_does_not_overwrite_existing_record(tmp_path) -> None:
    path = tmp_path / "users.json"
    repository = JsonUserRepository(path)
    original = UserRecord(user_id="synthetic-user", display_name="Original Name")
    repository.create(original)
    original_content = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="already exists"):
        repository.create(
            UserRecord(user_id="synthetic-user", display_name="Changed Name")
        )

    assert path.read_text(encoding="utf-8") == original_content
    assert repository.get_by_id(original.user_id) == original


@pytest.mark.parametrize(
    "content",
    [
        "{invalid",
        b"\xff\xfe",
        json.dumps({"synthetic-user": {"user_id": "missing display name"}}),
        json.dumps({"wrong-key": {"user_id": "synthetic-user", "display_name": "User"}}),
        json.dumps({"synthetic-user": {"user_id": "synthetic-user", "display_name": "User", "role": "admin"}}),
        json.dumps([]),
    ],
)
def test_corrupt_user_file_fails_explicitly_without_overwrite(
    tmp_path,
    content: str | bytes,
) -> None:
    path = tmp_path / "users.json"
    original_content = (
        content if isinstance(content, bytes) else content.encode("utf-8")
    )
    path.write_bytes(original_content)
    repository = JsonUserRepository(path)

    with pytest.raises(CorruptUserStoreError):
        repository.create(UserRecord(user_id="new-user", display_name="New User"))

    assert path.read_bytes() == original_content


def test_user_repository_uses_configured_path_and_interface(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("USER_STORE_PATH", str(tmp_path / "users.json"))

    repository = get_user_repository()

    assert isinstance(repository, UserRepository)
    repository.create(UserRecord(user_id="synthetic-user", display_name="User"))
    assert (tmp_path / "users.json").exists()
