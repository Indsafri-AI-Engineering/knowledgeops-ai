import sys
from types import SimpleNamespace

import pytest
from tokenizers import Tokenizer

from backend.app.knowledge.ai_providers import (
    create_chat_model,
    create_embeddings,
)


def test_groq_requires_synthetic_data_and_api_key(monkeypatch) -> None:
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "groq")
    monkeypatch.delenv("AI_DATA_CLASS", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="AI_DATA_CLASS=synthetic"):
        create_chat_model()

    monkeypatch.setenv("AI_DATA_CLASS", "synthetic")
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        create_chat_model()


def test_groq_chat_model_configuration(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeChatGroq:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_groq",
        SimpleNamespace(ChatGroq=FakeChatGroq),
    )
    monkeypatch.setenv("AI_DATA_CLASS", "synthetic")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_CHAT_MODEL", "test-groq-model")
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "groq")

    assert isinstance(create_chat_model(), FakeChatGroq)
    assert captured == {
        "model": "test-groq-model",
        "temperature": 0,
        "max_tokens": 512,
        "api_key": "test-key",
    }


def test_mistral_chat_and_embeddings_require_synthetic_data(monkeypatch) -> None:
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "mistral")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "mistral")
    monkeypatch.delenv("AI_DATA_CLASS", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")

    with pytest.raises(RuntimeError, match="AI_DATA_CLASS=synthetic"):
        create_chat_model()
    with pytest.raises(RuntimeError, match="AI_DATA_CLASS=synthetic"):
        create_embeddings()

    monkeypatch.setenv("AI_DATA_CLASS", "synthetic")
    monkeypatch.delenv("MISTRAL_API_KEY")
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        create_chat_model()
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        create_embeddings()


def test_mistral_chat_and_embedding_configuration(monkeypatch) -> None:
    captured_chat: dict[str, object] = {}
    captured_embeddings: dict[str, object] = {}

    class FakeChatMistralAI:
        def __init__(self, **kwargs) -> None:
            captured_chat.update(kwargs)

    class FakeMistralAIEmbeddings:
        def __init__(self, **kwargs) -> None:
            captured_embeddings.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "langchain_mistralai",
        SimpleNamespace(
            ChatMistralAI=FakeChatMistralAI,
            MistralAIEmbeddings=FakeMistralAIEmbeddings,
        ),
    )
    monkeypatch.setenv("AI_DATA_CLASS", "synthetic")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("MISTRAL_CHAT_MODEL", "mistral-test-chat")
    monkeypatch.setenv("MISTRAL_EMBEDDING_MODEL", "mistral-test-embed")
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "mistral")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "mistral")

    assert isinstance(create_chat_model(), FakeChatMistralAI)
    assert isinstance(create_embeddings(), FakeMistralAIEmbeddings)
    assert captured_chat == {
        "model_name": "mistral-test-chat",
        "temperature": 0,
        "max_tokens": 512,
        "api_key": "test-key",
    }
    assert captured_embeddings["model"] == "mistral-test-embed"
    assert captured_embeddings["api_key"] == "test-key"
    assert isinstance(captured_embeddings["tokenizer"], Tokenizer)


def test_groq_is_not_available_as_an_embedding_provider(monkeypatch) -> None:
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "groq")

    with pytest.raises(ValueError, match="RAG_EMBEDDING_PROVIDER"):
        create_embeddings()
