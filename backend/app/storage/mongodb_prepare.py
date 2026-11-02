from backend.app.core.environment import load_environment
from backend.app.storage.mongodb import close_mongodb_client
from backend.app.storage.mongodb_knowledge import MongoKnowledgeDocumentRepository


def main() -> None:
    load_environment()
    try:
        MongoKnowledgeDocumentRepository()
        print(
            "MongoDB knowledge collections and standard indexes are ready. "
            "No document content was written."
        )
    finally:
        close_mongodb_client()


if __name__ == "__main__":
    main()
