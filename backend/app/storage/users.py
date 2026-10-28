import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_USERS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "runtime" / "users.json"
)
_USERS_LOCK = threading.RLock()


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)


@runtime_checkable
class UserRepository(Protocol):
    def get_by_id(self, user_id: str) -> UserRecord | None: ...

    def get_all(self) -> list[UserRecord]: ...

    def create(self, user: UserRecord) -> UserRecord: ...


class CorruptUserStoreError(ValueError):
    """Raised when persisted user JSON cannot be safely validated."""


class JsonUserRepository:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.getenv("USER_STORE_PATH")
        self.path = path or (
            Path(configured_path) if configured_path else DEFAULT_USERS_PATH
        )

    def _read(self) -> dict[str, UserRecord]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise CorruptUserStoreError(
                f"User store contains invalid JSON: {self.path}"
            ) from error
        if not isinstance(payload, dict):
            raise CorruptUserStoreError(
                f"User store must contain a JSON object: {self.path}"
            )
        try:
            users = {
                key: UserRecord.model_validate(value)
                for key, value in payload.items()
            }
        except ValidationError as error:
            raise CorruptUserStoreError(
                f"User store contains an invalid record: {self.path}"
            ) from error
        if any(key != user.user_id for key, user in users.items()):
            raise CorruptUserStoreError(
                f"User store record keys must match user IDs: {self.path}"
            )
        return users

    def _write(self, users: dict[str, UserRecord]) -> None:
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
                        key: user.model_dump(mode="json")
                        for key, user in users.items()
                    },
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def get_by_id(self, user_id: str) -> UserRecord | None:
        with _USERS_LOCK:
            return self._read().get(user_id)

    def get_all(self) -> list[UserRecord]:
        with _USERS_LOCK:
            return list(self._read().values())

    def create(self, user: UserRecord) -> UserRecord:
        with _USERS_LOCK:
            users = self._read()
            if user.user_id in users:
                raise ValueError("User ID already exists.")
            users[user.user_id] = user
            self._write(users)
            return user


def get_user_repository() -> UserRepository:
    return JsonUserRepository()
