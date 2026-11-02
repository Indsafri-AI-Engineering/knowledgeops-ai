# Architecture

## Active application

The application is a React/TypeScript/Vite client and FastAPI backend. Sign-in
uses OIDC bearer tokens; the backend verifies provider-issued claims and maps
configured groups to allowlisted capabilities. Demo sign-in is disabled by
default. Fixture-only connector and threat-scan routes are mounted only when
the test suite explicitly enables `ENABLE_TEST_FIXTURES`.

The knowledge corpus starts with fictional seed files. The backend validates
and extracts text from authorized uploads, chunks it, and stores document
metadata in MongoDB Atlas `knowledge_documents`; chunk text, scope metadata,
and embeddings are stored in `knowledge_chunks`. Atlas Vector Search filters
by the authenticated user's allowed scopes before returning candidates.
Hybrid retrieval combines Atlas vector results with local BM25 rankings.
Original upload bytes are not retained. Uploads remain disabled until
`KNOWLEDGE_INGESTION_ENABLED=true` is set after the MongoDB and vector-search
path is verified. Existing local JSON and Qdrant data are not migrated
automatically. The configured local environment uses Ollama for embeddings
and answer generation. Answers include source references; empty retrieval
abstains without invoking the generation model.

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
change the local JSON storage used for the knowledge corpus or audit records.

The knowledge repository keeps document and chunk persistence separate from
the API and retrieval logic. MongoDB applies unique document-hash and
document-to-chunk indexes; chunks are separate records so their count is not
embedded in a potentially unbounded array. Chat is stateless: question and answer text are
not written to an application conversation store, included in audit metadata,
or used as context for later requests. Only the current response is held in
frontend component memory and is replaced when the next question is submitted.
Audit events record chat routing and source counts only. Credentials, tokens,
roles, and permissions are not written to user JSON records.

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

The current deployment is local and single-process. MongoDB Atlas is the
knowledge document/vector store; audit and other runtime records, in-process
sessions/caches/locks, and local Keycloak remain development components.
Source approvals, identity
configuration, access-scope mapping, retention, backups, and deployment
hardening remain go-live decisions. No real company source or production
integration is configured by this repository.
