import os
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.app.core.auth import auth_mode, get_current_user
from backend.app.integrations.jira_cloud import JiraCloudClient
from backend.app.integrations.n8n import N8nAlertNotifier, N8nJiraNotifier

router = APIRouter(prefix="/system", tags=["system"])

SystemMode = Literal["local", "mock", "disabled", "external"]


class SystemComponent(BaseModel):
    name: str
    category: str
    mode: SystemMode
    description: str
    external_connection: bool


class SystemStatusResponse(BaseModel):
    environment: str
    components: list[SystemComponent]


_COMPONENTS = [
    SystemComponent(
        name="Knowledge sources",
        category="knowledge",
        mode="local",
        description="User-uploaded documents and extracted text chunks stored locally.",
        external_connection=False,
    ),
    SystemComponent(
        name="Retrieval",
        category="knowledge",
        mode="local",
        description="Permission-filtered TF-IDF and BM25 retrieval over uploaded document chunks.",
        external_connection=False,
    ),
    SystemComponent(
        name="Embeddings",
        category="ai",
        mode="local",
        description="Local Ollama embeddings are selected.",
        external_connection=False,
    ),
    SystemComponent(
        name="Answer generation",
        category="ai",
        mode="local",
        description="Deterministic local response templates; no chat model is configured.",
        external_connection=False,
    ),
    SystemComponent(
        name="Storage",
        category="data",
        mode="local",
        description="JSON stores document metadata and extracted chunks; runtime records use local JSON.",
        external_connection=False,
    ),
    SystemComponent(
        name="Jira Cloud",
        category="integration",
        mode="disabled",
        description="Jira Cloud credentials are not configured.",
        external_connection=False,
    ),
    SystemComponent(
        name="MCP",
        category="integration",
        mode="disabled",
        description="No MCP server or tools are configured or connected.",
        external_connection=False,
    ),
    SystemComponent(
        name="n8n notifications",
        category="integration",
        mode="disabled",
        description="No workflow webhook is configured.",
        external_connection=False,
    ),
    SystemComponent(
        name="Threat detection",
        category="security",
        mode="local",
        description=(
            "Pre-ingestion document checks, URL/email indicators, and repeated "
            "access-denial monitoring create redacted local alerts. Binary "
            "files are not executed and submitted URLs are not fetched."
        ),
        external_connection=False,
    ),
    SystemComponent(
        name="Groq",
        category="ai",
        mode="disabled",
        description="Not selected.",
        external_connection=False,
    ),
    SystemComponent(
        name="Mistral",
        category="ai",
        mode="disabled",
        description="Not selected.",
        external_connection=False,
    ),
]


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    dependencies=[Depends(get_current_user)],
)
def read_system_status() -> SystemStatusResponse:
    components = list(_COMPONENTS)
    n8n_index = next(
        index for index, component in enumerate(components)
        if component.name == "n8n notifications"
    )
    n8n_configured = (
        N8nAlertNotifier().configured or N8nJiraNotifier().configured
    )
    components[n8n_index] = SystemComponent(
        name="n8n notifications",
        category="integration",
        mode="external" if n8n_configured else "disabled",
        description=(
            "Configured webhooks receive minimal Jira-creation or security-alert metadata."
            if n8n_configured
            else "No valid Jira or security-alert webhook is configured."
        ),
        external_connection=n8n_configured,
    )
    jira_index = next(
        index for index, component in enumerate(components)
        if component.name == "Jira Cloud"
    )
    jira_configured = JiraCloudClient().configured
    components[jira_index] = SystemComponent(
        name="Jira Cloud",
        category="integration",
        mode="external" if jira_configured else "disabled",
        description=(
            "Jira Cloud REST API is configured. Issue writes require "
            "jira:approve and explicit confirmation."
            if jira_configured
            else "Jira Cloud credentials are not configured."
        ),
        external_connection=jira_configured,
    )
    embedding_provider = os.getenv(
        "RAG_EMBEDDING_PROVIDER",
        "ollama",
    ).strip().lower()
    rag_backend = os.getenv("RAG_BACKEND", "qdrant").strip().lower()
    if embedding_provider == "mistral" and rag_backend == "qdrant":
        embedding_status = SystemComponent(
            name="Embeddings",
            category="ai",
            mode="external",
            description=(
                "Mistral embeddings are selected; synthetic content is sent "
                "to the external Mistral API."
            ),
            external_connection=True,
        )
    elif embedding_provider == "ollama":
        embedding_status = SystemComponent(
            name="Embeddings",
            category="ai",
            mode="local",
            description="Local Ollama embeddings are selected.",
            external_connection=False,
        )
    else:
        embedding_status = SystemComponent(
            name="Embeddings",
            category="ai",
            mode="disabled",
            description=(
                "Mistral embeddings are configured but inactive until "
                "RAG_BACKEND=qdrant."
                if embedding_provider == "mistral"
                else f"Unsupported RAG_EMBEDDING_PROVIDER: {embedding_provider}."
            ),
            external_connection=False,
        )
    embedding_index = next(
        index for index, component in enumerate(components)
        if component.name == "Embeddings"
    )
    components[embedding_index] = embedding_status

    if os.getenv("RAG_BACKEND", "qdrant").lower() == "qdrant":
        retrieval_index = next(
            index
            for index, component in enumerate(components)
            if component.name == "Retrieval"
        )
        components[retrieval_index] = SystemComponent(
            name="Retrieval",
            category="knowledge",
            mode="local",
            description=(
                f"LangChain {embedding_provider.title()} embeddings with "
                "persistent local Qdrant dense retrieval and lexical hybrid ranking."
            ),
            external_connection=False,
        )
    generation_backend = os.getenv(
        "RAG_GENERATION_BACKEND",
        "extractive",
    ).lower()
    if generation_backend == "ollama":
        generation_mode: SystemMode = "local"
        generation_external = False
        generation_description = (
            "LangChain Ollama chat generation using retrieved local evidence; "
            "no hosted model provider is called."
        )
    elif generation_backend == "extractive":
        generation_mode = "local"
        generation_external = False
        generation_description = (
            "Deterministic local extractive response templates; no chat model is called."
        )
    elif generation_backend in ("groq", "mistral"):
        generation_mode = "external"
        generation_external = True
        generation_description = (
            f"{generation_backend.title()} chat is selected. Questions and "
            "retrieved evidence are sent to its hosted API; synthetic content only."
        )
    else:
        generation_mode = "disabled"
        generation_external = False
        generation_description = (
            f"Unsupported RAG_GENERATION_BACKEND setting: {generation_backend}."
        )
    generation_index = next(
        index
        for index, component in enumerate(components)
        if component.name == "Answer generation"
    )
    components[generation_index] = SystemComponent(
        name="Answer generation",
        category="ai",
        mode=generation_mode,
        description=generation_description,
        external_connection=generation_external,
    )
    for provider_name in ("Groq", "Mistral"):
        selected = (
            generation_backend == provider_name.lower()
            or (
                provider_name == "Mistral"
                and embedding_provider == "mistral"
                and rag_backend == "qdrant"
            )
        )
        provider_index = next(
            index
            for index, component in enumerate(components)
            if component.name == provider_name
        )
        components[provider_index] = SystemComponent(
            name=provider_name,
            category="ai",
            mode="external" if selected else "disabled",
            description=(
                "Selected for synthetic-only processing."
                if selected
                else "Not selected."
            ),
            external_connection=selected,
        )
    if auth_mode() == "oidc":
        authentication = SystemComponent(
            name="Authentication",
            category="identity",
            mode="local",
            description="Keycloak-issued OIDC bearer tokens are verified against the configured issuer and group mapping.",
            external_connection=False,
        )
    else:
        authentication = SystemComponent(
            name="Authentication",
            category="identity",
            mode="mock",
            description="Selectable fictional demo identities; no identity provider is connected.",
            external_connection=False,
        )
    components.insert(0, authentication)
    environment = os.getenv("APP_ENV", "development").strip().lower()
    return SystemStatusResponse(
        environment=environment,
        components=components,
    )
