import pytest

from backend.app.storage import mongodb


@pytest.fixture(autouse=True)
def clear_mongodb_client():
    mongodb.close_mongodb_client()
    yield
    mongodb.close_mongodb_client()


def test_mongodb_client_requires_a_connection_uri(monkeypatch) -> None:
    monkeypatch.delenv("MONGODB_URI", raising=False)

    with pytest.raises(RuntimeError, match="Set MONGODB_URI"):
        mongodb.get_mongodb_client()


def test_mongodb_client_is_reused_and_pinged(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://example.invalid")
    clients = []

    class FakeAdmin:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def command(self, name: str) -> dict[str, int]:
            self.commands.append(name)
            return {"ok": 1}

    class FakeClient:
        def __init__(self, uri: str) -> None:
            self.uri = uri
            self.admin = FakeAdmin()
            self.closed = False

        def __getitem__(self, name: str):
            return name

        def close(self) -> None:
            self.closed = True

    def create_client(uri: str) -> FakeClient:
        client = FakeClient(uri)
        clients.append(client)
        return client

    monkeypatch.setattr(mongodb, "MongoClient", create_client)

    first_client = mongodb.get_mongodb_client()
    assert mongodb.get_mongodb_client() is first_client
    mongodb.ping_mongodb()

    assert len(clients) == 1
    assert clients[0].uri == "mongodb+srv://example.invalid"
    assert clients[0].admin.commands == ["ping"]


def test_mongodb_database_uses_configured_name(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://example.invalid")
    monkeypatch.setenv("MONGODB_DATABASE", "knowledgeops_test")

    class FakeClient:
        def __init__(self, uri: str) -> None:
            self.uri = uri

        def __getitem__(self, name: str) -> str:
            return name

        def close(self) -> None:
            pass

    monkeypatch.setattr(mongodb, "MongoClient", FakeClient)

    assert mongodb.get_mongodb_database() == "knowledgeops_test"


def test_repository_backend_defaults_to_mongodb(monkeypatch) -> None:
    from backend.app.storage.knowledge import get_knowledge_document_repository

    monkeypatch.delenv("KNOWLEDGE_STORE_BACKEND", raising=False)
    monkeypatch.setattr(
        "backend.app.storage.mongodb_knowledge.MongoKnowledgeDocumentRepository",
        lambda: "mongodb-repository",
    )

    assert get_knowledge_document_repository() == "mongodb-repository"
