import os

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel


def _require_synthetic_data(provider: str) -> None:
    if os.getenv("AI_DATA_CLASS", "").strip().lower() != "synthetic":
        raise RuntimeError(
            f"{provider} is an external AI provider. Set AI_DATA_CLASS=synthetic "
            "only when all submitted questions, documents, and retrieved content "
            "are synthetic."
        )


def create_embeddings() -> Embeddings:
    provider = os.getenv("RAG_EMBEDDING_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    if provider == "mistral":
        _require_synthetic_data("Mistral embeddings")
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "MISTRAL_API_KEY is required when "
                "RAG_EMBEDDING_PROVIDER=mistral."
            )
        from langchain_mistralai import MistralAIEmbeddings
        from tokenizers import Tokenizer, models, pre_tokenizers

        tokenizer = Tokenizer(
            models.WordLevel({"[UNK]": 0}, unk_token="[UNK]")
        )
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()

        return MistralAIEmbeddings(
            model=os.getenv("MISTRAL_EMBEDDING_MODEL", "mistral-embed"),
            api_key=api_key,
            tokenizer=tokenizer,
        )
    raise ValueError(f"Unsupported RAG_EMBEDDING_PROVIDER: {provider}")


def create_chat_model() -> BaseChatModel:
    provider = os.getenv(
        "RAG_GENERATION_BACKEND",
        "extractive",
    ).strip().lower()
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=os.getenv("OLLAMA_CHAT_MODEL", "llama3.2:3b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0,
            num_predict=512,
        )
    if provider == "groq":
        _require_synthetic_data("Groq")
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is required when RAG_GENERATION_BACKEND=groq."
            )
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=os.getenv(
                "GROQ_CHAT_MODEL",
                "llama-3.3-70b-versatile",
            ),
            temperature=0,
            max_tokens=512,
            api_key=api_key,
        )
    if provider == "mistral":
        _require_synthetic_data("Mistral")
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "MISTRAL_API_KEY is required when "
                "RAG_GENERATION_BACKEND=mistral."
            )
        from langchain_mistralai import ChatMistralAI

        return ChatMistralAI(
            model_name=os.getenv("MISTRAL_CHAT_MODEL", "mistral-small-latest"),
            temperature=0,
            max_tokens=512,
            api_key=api_key,
        )
    raise ValueError(f"Unsupported RAG_GENERATION_BACKEND: {provider}")
