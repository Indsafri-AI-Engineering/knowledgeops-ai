# Architecture

## Active application

The application is a React/TypeScript/Vite client and FastAPI backend. Sign-in
uses OIDC bearer tokens; the backend verifies provider-issued claims and maps
configured groups to allowlisted capabilities. Demo sign-in is disabled by
default. Fixture-only connector and threat-scan routes are mounted only when
the test suite explicitly enables `ENABLE_TEST_FIXTURES`.

The knowledge corpus starts empty. Users with `knowledge:manage` upload PDF,
DOCX, TXT, Markdown, HTML, XLSX, or PPTX files through the knowledge-document
API. The backend validates and extracts text, chunks it, records document
metadata and chunks in the JSON repository at
`data/runtime/knowledge.json`, and indexes it for retrieval. Original upload
bytes are not retained. The JSON file is the application record store; local
Qdrant is the separate vector index and stores embeddings when
`RAG_BACKEND=qdrant`. The configured local environment uses Ollama for
embeddings and answer generation. Retrieval applies the user's allowed
knowledge scopes before ranking, and answers include source references.
Empty retrieval abstains without invoking the generation model.

Chat requests are classified by a deterministic LangChain router into
knowledge, workflow, analytical, or unsupported routes. Knowledge and
evidence-based analysis use the permission-filtered retrieval service;
workflow connectors remain fixture-only unless explicitly implemented and
authorized. Chat does not execute Jira or threat-scan actions, and unsupported
actions return a planned response without external side effects.

The dedicated Jira workspace is a real Jira Cloud REST integration when
`JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` are configured. Jira
credentials remain on the backend. Issue reads require `jira:read`; writes
require `jira:approve` and explicit user confirmation. The Jira service account
is subject to its own project permissions. Jira remains optional and does not
change the local JSON storage used for the knowledge corpus, conversations,
or audit records.

The knowledge store validates the complete JSON structure and fails without
overwriting a corrupt file. Writes use a temporary file and atomic replacement.
The repository abstraction keeps document and chunk persistence separate from
the API and retrieval logic. Conversations, audit events, and user profile
metadata are also stored locally; credentials, tokens, roles, and permissions
are not written to user JSON records.

Hosted Groq or Mistral inference remains an explicit configuration choice.
Those integrations fail closed unless `AI_DATA_CLASS=synthetic` is set; this
is an operator assertion, not content inspection. Do not select a hosted
provider for documents or questions that are not synthetic and approved for
that provider.

## Fictional demo corpus and test fixtures

The running application loads a small fictional Northstar Works corpus from
`data/fictional_demo/` by default. Each source document has an explicit access
scope, and retrieval filters chunks by the authenticated user's capabilities.
The separate `tests/fixtures/fictional_demo/` corpus is used only by automated
tests; `tests/conftest.py` selects it in the isolated test process. Mock
connector and threat routes are not enabled in the normal application.

## Operational boundaries

The current deployment is local and single-process. JSON storage, embedded
Qdrant, in-process sessions/caches/locks, and local Keycloak are development
building blocks, not approved production services. Source approvals, identity
configuration, access-scope mapping, retention, backups, and deployment
hardening remain go-live decisions. No real company source or production
integration is configured by this repository.
