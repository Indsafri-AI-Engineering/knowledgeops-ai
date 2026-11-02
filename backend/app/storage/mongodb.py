import os
import sys
from threading import Lock

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

_client: MongoClient | None = None
_client_lock = Lock()


def get_mongodb_client() -> MongoClient:
    global _client

    if _client is None:
        with _client_lock:
            if _client is None:
                uri = os.getenv("MONGODB_URI", "").strip()
                if not uri:
                    raise RuntimeError(
                        "Set MONGODB_URI in the backend environment."
                    )
                _client = MongoClient(uri)
    return _client


def get_mongodb_database_name() -> str:
    database_name = os.getenv("MONGODB_DATABASE", "knowledgeops").strip()
    if not database_name:
        raise RuntimeError("MONGODB_DATABASE must not be empty.")
    return database_name


def get_mongodb_database() -> Database:
    return get_mongodb_client()[get_mongodb_database_name()]


def ping_mongodb() -> None:
    get_mongodb_client().admin.command("ping")


def close_mongodb_client() -> None:
    global _client

    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def main() -> None:
    from backend.app.core.environment import load_environment

    load_environment()
    try:
        ping_mongodb()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from error
    except PyMongoError as error:
        print(
            f"MongoDB connection failed ({type(error).__name__}).",
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    else:
        print(
            "MongoDB connection successful "
            f"(database: {get_mongodb_database_name()})."
        )
    finally:
        close_mongodb_client()


if __name__ == "__main__":
    main()
