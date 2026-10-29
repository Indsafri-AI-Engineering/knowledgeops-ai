# KnowledgeOps AI --- Phase-by-Phase Implementation Plan

**Project:** Enterprise Knowledge and Intelligent Operations Platform

This roadmap implements the existing KnowledgeOps AI HLD phase by phase,
beginning with the foundation and JSON storage. The project scope
remains permission-aware RAG, hybrid retrieval, enterprise workflows,
Jira and n8n integration, threat detection, evaluation, and security.

## Overview

1.  **Phase 1 --- Project Foundation and JSON Storage:** Set up
    frontend, backend, API structure, JSON persistence, configuration,
    and testing.
2.  **Phase 2 --- Document Ingestion and Baseline RAG:** Ingest
    documents, extract and chunk text, generate embeddings, retrieve
    passages, and generate grounded answers.
3.  **Phase 3 --- Hybrid Retrieval and Ranking:** Combine semantic
    retrieval and keyword retrieval using BM25 and Reciprocal Rank
    Fusion (RRF).
4.  **Phase 4 --- LangChain Routing and Orchestration:** Route requests
    to the correct knowledge, workflow, or analytical component.
5.  **Phase 5 --- Authentication, RBAC, and Auditing:** Implement
    identity, roles, permissions, access enforcement, and audit records.
6.  **Phase 6 --- Document-Based HR, Recruitment, and IT Knowledge:**
    Ingest approved documents through the permission-aware knowledge pipeline.
7.  **Phase 7 --- Jira and n8n Integration:** Support approved
    operational workflows and controlled actions.
8.  **Phase 8 --- Threat and Fraud Detection:** Detect suspicious
    patterns, risk indicators, and anomalies.
9.  **Phase 9 --- Evaluation and Quality Metrics:** Evaluate
    faithfulness, relevancy, contextual precision, contextual recall,
    latency, and errors.
10. **Phase 10 --- Moderation and Guardrails:** Apply deterministic
    safety checks to user input, retrieved content, and generated answers.
11. **Phase 11 --- Hardening, Documentation, and Demonstration:**
    Complete security checks, testing, documentation, and the end-to-end
    demonstration.

------------------------------------------------------------------------

# Phase 1 --- Project Foundation and JSON Storage

## Objective

Establish the application structure before implementing advanced RAG and
workflows.

The phase focuses on: - Setting up the frontend and backend. - Creating
the initial API. - Implementing JSON persistence. - Designing repository
interfaces so a database can be introduced later. - Creating initial
sample data. - Establishing configuration, logging, and testing. -
Connecting the frontend to the backend.

**Important:** JSON is the initial storage mechanism. Business logic
should use repository abstractions rather than accessing JSON files
directly. This allows a future PostgreSQL or PostgreSQL with pgvector
implementation without redesigning the entire application.

## Technology stack

  Component             Technology
  --------------------- ----------------------------------
  Frontend              React, TypeScript, Vite
  Backend               Python, FastAPI
  Data validation       Pydantic
  Initial persistence   JSON files
  API testing           Swagger UI / Postman
  Automated testing     pytest
  Configuration         Environment variables and `.env`
  Version control       Git and GitHub

## Initial project structure

``` text
KnowledgeOps-AI/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── health.py
│   │   │   ├── chat.py
│   │   │   └── users.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   └── logging.py
│   │   ├── models/
│   │   │   ├── chat.py
│   │   │   └── user.py
│   │   ├── repositories/
│   │   │   ├── interfaces.py
│   │   │   └── json_user_repository.py
│   │   ├── services/
│   │   │   └── chat_service.py
│   │   └── main.py
│   ├── data/
│   │   └── users.json
│   ├── tests/
│   │   ├── test_health.py
│   │   ├── test_chat.py
│   │   └── test_repositories.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── [React and TypeScript application]
├── docs/
│   └── README.md
├── .gitignore
└── README.md
```

This is the initial foundation, not the complete final architecture.
Additional modules will be introduced in their relevant phases.

## Backend implementation

### A. Create the FastAPI application

Create the main application entry point with FastAPI initialization, API
version routing, health endpoint registration, basic error handling, and
configuration loading.

Initial endpoint: `GET /api/v1/health`

Example response:

``` json
{
  "status": "healthy",
  "application": "KnowledgeOps AI",
  "version": "1.0.0"
}
```

This endpoint verifies that the backend is running; it does not prove
that every dependency or integration is operational.

### B. Define data models

Use Pydantic models to validate incoming requests and outgoing
responses. Initial models include User, Chat Request, Chat Response,
and Knowledge Source Metadata. Chat is stateless: do not create
conversation or message models for storing chat transcripts.

Keep models separate from the storage implementation so they can be
reused if the persistence layer changes.

### C. Implement JSON repositories

Create repository interfaces and JSON implementations for persistent
entities such as users. Do not persist chat questions or answers.

Example user repository interface:

``` python
from typing import Protocol


class UserRepository(Protocol):
    def get_by_id(self, user_id: str):
        ...

    def get_all(self):
        ...

    def create(self, user: dict):
        ...
```

The JSON implementation will satisfy this interface. Later, a PostgreSQL
implementation can satisfy the same interface. Business services should
depend on the interface rather than directly opening JSON files.

JSON storage requirements: - Store data in predictable files. - Validate
records before saving them. - Handle missing or malformed files
safely. - Avoid overwriting existing records accidentally. - Use unique
identifiers. - Keep read and write operations in the repository layer. -
Add appropriate error handling. - Do not store secrets or real sensitive
employee information in sample files.

Use fictional demonstration data in this phase.

### D. Implement the initial chat API

Create `POST /api/v1/chat`.

The initial chat endpoint validates the request and returns a structured
response. It may use a placeholder response until RAG is introduced in
Phase 2. Do not present placeholder responses as AI-generated answers or
claim retrieval is already implemented.

Example request:

``` json
{
  "question": "What is the fictional leave policy?"
}
```

Example response:

``` json
{
  "question": "What is the fictional leave policy?",
  "answer": "The knowledge retrieval capability will be implemented in Phase 2.",
  "sources": [],
  "status": "foundation"
}
```

The identifiers and content are illustrative examples.

## Frontend implementation

Create the initial React and TypeScript application using Vite. The
interface should include: - KnowledgeOps AI application title. - Chat
input field and send button. - Current response area. - Loading
indicator. - Error message display. - Source citation area, initially
empty.

The frontend must call the FastAPI backend instead of generating its own
responses. The purpose at this stage is to validate the
frontend-to-backend connection.

## Initial API contract

  -----------------------------------------------------------------------
  Endpoint                Purpose                 Phase 1 behaviour
  ----------------------- ----------------------- -----------------------
  `GET /api/v1/health`    Check backend status    Implement

  `GET /api/v1/me`        Return current user     Define the contract;
                          information             authentication is
                                                  introduced in Phase 5

  `POST /api/v1/chat`     Submit an independent  Implement basic
                          question                validated response

  JSON repository         Store initial users     Implement
  operations                                      
  -----------------------------------------------------------------------

The `/api/v1/me` endpoint must not claim to provide authenticated
identity until authentication is implemented.

## Testing requirements

-   Health endpoint returns a successful response.
-   Invalid chat requests are rejected.
-   Valid chat requests return the expected response structure.
-   JSON repositories can create and retrieve records.
-   Missing JSON files are handled safely.
-   Invalid JSON produces a controlled error.
-   Existing records are not unintentionally overwritten.
-   The frontend can call the backend successfully.

## Phase 1 completion checklist

-   [ ] Backend starts successfully.
-   [ ] Health endpoint works through Swagger UI.
-   [ ] Chat endpoint accepts validated requests.
-   [ ] Frontend communicates with the backend.
-   [ ] JSON repositories read and write sample data.
-   [ ] Repository interfaces separate storage from business logic.
-   [ ] Environment configuration and `.gitignore` are set up.
-   [ ] Automated tests pass.
-   [ ] README explains installation and execution.

**Phase 1 is complete when the foundation works reliably and the
repository abstraction is in place.** Advanced RAG, real enterprise
integrations, and production authentication are not requirements for
completing this phase.

------------------------------------------------------------------------

# Phase 2 --- Document Ingestion and Baseline RAG

## Objective

Allow KnowledgeOps AI to ingest knowledge documents and answer questions
using retrieved content.

## Implementation tasks

1.  Implement document upload and file validation.
2.  Extract text from supported formats: PDF, DOCX, TXT, Markdown, HTML,
    XLSX, and PPTX.
3.  Clean and normalize extracted text.
4.  Split documents into chunks.
5.  Generate embeddings for each chunk.
6.  Store document metadata and chunk information.
7.  Retrieve relevant chunks for a question.
8.  Pass retrieved context to the language model.
9.  Generate an answer grounded in the retrieved context.
10. Return source information alongside the answer.

## Initial data

The application includes a small, clearly fictional Northstar Works seed
corpus under `data/fictional_demo/` for local demonstrations. These examples
are not real organizational policies. Additional documents may be uploaded
only by authorized users and should be approved for the configured storage
and AI providers. Each indexed document has metadata including document ID,
filename, file hash, document type, upload timestamp, chunk IDs, access scope,
and source metadata.

## Exit criteria

-   A document can be uploaded and processed.
-   Text extraction and chunking work.
-   Embeddings can be generated and stored.
-   Questions retrieve relevant passages.
-   Answers include source references.
-   The system can indicate when the available context is insufficient.

------------------------------------------------------------------------

# Phase 3 --- Hybrid Retrieval and Ranking

## Objective

Improve retrieval quality by combining semantic search with
keyword-based search.

## Implementation tasks

1.  Implement semantic retrieval.
2.  Implement BM25 keyword retrieval.
3.  Combine retrieval results using Reciprocal Rank Fusion (RRF).
4.  Deduplicate overlapping results.
5.  Rank retrieved passages.
6.  Configure retrieval parameters.
7.  Record retrieval results for evaluation.

## Exit criteria

-   Semantic and keyword searches operate independently.
-   Hybrid retrieval combines both result sets.
-   Retrieved passages can be traced to their source documents.
-   Retrieval behaviour can be tested against a fixed question set.

## Implementation notes

The Qdrant backend exposes dense-only, BM25-only, and hybrid retrieval.
Hybrid mode requests permission-filtered candidates from both retrievers and
combines their rankings with RRF (`k=60`), deduplicating repeated chunks by
chunk ID. BM25 candidates are obtained independently from dense retrieval.
The local backend provides a TF-IDF vector baseline alongside BM25. Retrieval
evaluation uses the fixed question set in `tests/evaluation/retrieval_cases.json`
and reports vector, keyword, and hybrid MRR@3.

------------------------------------------------------------------------

# Phase 4 --- LangChain Routing and Orchestration

## Objective

Introduce request routing so KnowledgeOps AI can distinguish between
knowledge questions, operational requests, and analytical tasks.

## Implementation tasks

1.  Define request categories.
2.  Build a routing service.
3.  Connect the knowledge-question route to the RAG pipeline.
4.  Prepare interfaces for HR, recruitment, and IT service routes.
5.  Implement structured routing outputs.
6.  Handle unsupported requests safely.
7.  Record routing decisions for debugging and evaluation.

## Exit criteria

-   Supported requests are routed to the correct component.
-   The knowledge route uses retrieval.
-   Unsupported requests do not trigger fabricated answers.
-   Routing failures are handled and logged.

## Implementation notes

Chat classification is a deterministic LangChain `RunnableLambda` that emits
a validated route decision containing intent, category, component, workflow
class, and clarification state. The orchestration service dispatches
permission-filtered knowledge retrieval, fixture-only Jira and recruitment
handlers, planned threat workflows, and evidence-bounded analytical
generation. Unsupported action requests do not fall through to RAG and do not
invoke external systems. Route category and component are returned in chat
responses and recorded in audit metadata.

------------------------------------------------------------------------

# Phase 5 --- Authentication, RBAC, and Auditing

## Objective

Introduce identity and authorization controls before exposing enterprise
knowledge or operational actions.

## Implementation tasks

1.  Implement authentication.
2.  Define user roles and permissions.
3.  Implement role-based access control (RBAC).
4.  Associate knowledge sources with access policies.
5.  Enforce permissions before retrieving content for the LLM.
6.  Restrict sensitive actions according to role.
7.  Add audit records for relevant access and actions.
8.  Add tests for unauthorized access.

## Exit criteria

-   Users have an identifiable authenticated context.
-   Restricted sources are filtered before entering the LLM context.
-   Unauthorized operations are rejected.
-   Sensitive operations are auditable.
-   Access-control tests pass.

## Implementation notes

OIDC bearer tokens are verified against the configured issuer and audience,
and server-side group-to-capability mappings determine effective permissions.
The development demo identity is gated behind explicit local-development
settings. Capability checks protect API operations, while source scopes are
applied before retrieval context reaches generation. Audit records capture
authentication and authorization outcomes, chat requests, and knowledge
document operations without storing question or document text. Automated
tests cover token rejection, fail-closed group mapping, manager capabilities,
permission enforcement, source filtering, and audit records.

------------------------------------------------------------------------

# Phase 6 --- Document-Based HR, Recruitment, and IT Knowledge

## Objective

Make approved HR, recruitment, and IT documents available through the
existing permission-aware ingestion and retrieval pipeline. This phase uses
documents supplied by the user or organization; it does not introduce
fictional records, mock connectors, or external business-system integrations.

## Implementation tasks

1.  Identify the approved document sets and their owners.
2.  Assign each document an access scope (`hr`, `recruitment`, `it`, or
    `general`) that matches the organization's authorization policy.
3.  Ingest documents through the authenticated knowledge-document upload
    interface, using supported formats: PDF, DOCX, TXT, Markdown, HTML, XLSX,
    and PPTX.
4.  Provide accurate document titles and optional owner, version, effective
    date, next-review date, and environment metadata.
5.  Verify extraction, chunking, indexing, citations, and search results for
    each document set.
6.  Verify that users without the corresponding source scope cannot retrieve
    restricted document content.
7.  Confirm document listing, upload, and deletion are permission-checked and
    audited.
8.  Add tests for scope isolation and document-derived answers using synthetic
    fixtures only; do not create mock HR, recruitment, or IT records.

## Example demonstration scenarios

-   Ask a permitted question answered by an uploaded HR policy and inspect its
    citation.
-   Retrieve recruitment requirements from an authorized recruitment
    document.
-   Find troubleshooting steps in an uploaded IT manual.
-   Verify that a user without the relevant scope cannot retrieve restricted
    document content.

## Exit criteria

-   Approved documents are ingested through the knowledge-document pipeline.
-   Answers cite the ingested documents that support them.
-   Retrieval enforces document scopes before content reaches generation.
-   Unauthorized document-management operations are rejected and audited.
-   No mock HR, recruitment, or IT connector is exposed by the running
    application.

## Implementation notes

The document upload, extraction, JSON persistence, indexing, permission
checks, and scope-filtered retrieval were implemented in earlier phases.
Phase 6 applies that pipeline to the organization's approved documents;
document ingestion is not automatic, and actual source documents must be
provided and uploaded by an authorized user. The upload API supports PDF,
DOCX, TXT, Markdown, HTML, XLSX, and PPTX, with `hr`, `recruitment`, `it`,
and `general` access scopes. Do not upload confidential or personal documents
until the identity, access-scope mapping, storage, and model-provider choices
have been approved for that data.

------------------------------------------------------------------------

# Phase 7 --- Jira and n8n Integration

## Objective

Allow KnowledgeOps AI to support approved operational workflows, with
appropriate authorization and confirmation.

## Implementation tasks

1.  Define the workflow action interface.
2.  Integrate with Jira in a controlled environment.
3.  Configure n8n workflows.
4.  Validate action inputs.
5.  Enforce user permissions.
6.  Introduce confirmation or approval gates for sensitive actions.
7.  Record action requests and results.
8.  Handle failures and retries safely.

## Exit criteria

-   Approved actions can be triggered through the defined workflow.
-   Unauthorized actions are rejected.
-   Sensitive actions require the appropriate approval.
-   Results accurately reflect what the external system reports.
-   Failed actions are not reported as successful.

## Current Phase 7 progress

The direct Jira Cloud API supports authorized search and explicitly confirmed
issue changes. An optional n8n webhook now receives a minimal event after
successful issue creation; delivery status is returned separately from the
Jira result and recorded in the audit log. See `docs/N8N_SETUP.md`. The actual
n8n workflow URL and secret remain deployment configuration, and live
end-to-end delivery still needs verification in an approved test workspace.

------------------------------------------------------------------------

# Phase 8 --- Threat and Fraud Detection

## Objective

Introduce a separate detection capability for suspicious patterns,
potential threats, and anomalous activity.

## Implementation tasks

1.  Define the detection use cases.
2.  Identify permitted input data.
3.  Prepare fictional or authorized demonstration datasets.
4.  Implement initial detection rules or anomaly detection.
5.  Generate structured alerts.
6.  Record evidence and detection reasons.
7.  Add configurable thresholds.
8.  Test normal and suspicious scenarios.

## Exit criteria

-   Detection results are explainable.
-   Alerts include the relevant evidence.
-   Detection is separated from the general knowledge-answering
    pipeline.
-   The system distinguishes potential risk indicators from confirmed
    fraud or threats.

------------------------------------------------------------------------

# Phase 9 --- Evaluation and Quality Metrics

## Objective

Measure the quality of retrieval, generated answers, and operational
behaviour.

## Implementation tasks

1.  Create a test dataset with questions and reference answers.
2.  Record expected source documents and supporting context.
3.  Evaluate faithfulness.
4.  Evaluate answer relevancy.
5.  Evaluate contextual precision.
6.  Evaluate contextual recall.
7.  Track latency and error rates.
8.  Compare results across changes to retrieval and generation settings.
9.  Document known limitations.

## Exit criteria

-   Evaluation results can be reproduced.
-   The system can identify unsupported answers.
-   Retrieval quality can be compared across configurations.
-   Evaluation results are recorded rather than inferred from a few
    successful demonstrations.

## Current Phase 9 progress

Run `python -m backend.app.evaluation.run_demo_evaluation` from the repository
root to evaluate the versioned synthetic question set and save a JSON report to
`data/evaluation/phase9_latest.json`. The report compares local vector
(TF-IDF), BM25 keyword, and hybrid retrieval, then evaluates the configured
answer generator for faithfulness, reference-answer relevancy, contextual
precision, contextual recall, latency, and errors. It also includes routing,
restricted-scope denial/leak, and threat-detection metrics. Use
`--generation-backends extractive,ollama` to compare generators; hosted
generation remains subject to `AI_DATA_CLASS=synthetic`.

Faithfulness and answer relevancy use lexical overlap with retrieved context
and reference answers; contextual recall uses overlap with annotated supporting
facts. These reproducible proxies can flag likely unsupported sentences but do
not establish semantic entailment. The fixtures are synthetic and small, so
scores are a regression baseline, not a production quality claim or approved
go/no-go threshold. Results include per-case metric values, retrieved document
IDs, unsupported sentence text, request latency, and error types. The report
path is ignored by Git; copy or rename it before another run to retain a
comparison.

------------------------------------------------------------------------

# Phase 10 --- Moderation and Guardrails

## Objective

Apply a local, deterministic safety layer around the existing permission-aware
chat and RAG pipeline. Moderation supplements, and never replaces,
authentication, authorization, scope-filtered retrieval, or approved workflow
controls.

## Implementation tasks

1. Normalize and classify chat input; block explicit credential disclosure,
   access-control bypass, instruction override, targeted abuse, and narrowly
   defined harmful requests.
2. Ask for clarification on ambiguous or unsupported requests without
   invoking retrieval or generation.
3. Inspect retrieved passages and remove suspicious instruction sentences
   before generation while preserving safe evidence and citation metadata.
4. Check generated answers for credential-like values, invalid citations,
   unsupported numeric claims, and low lexical evidence support. Withhold an
   answer that fails these checks.
5. Record stage, outcome, category, severity, rule, policy version, and
   non-content metadata in the existing audit log. Do not write raw prompts,
   retrieved passages, answers, or detected secret values to moderation audit
   events.
6. Keep chat-created external actions disabled; require the existing approved
   workflow and authorization paths for side effects, and audit attempted
   unsupported actions.
7. Run the synthetic guardrail cases together with the Phase 9 evaluation and
   preserve JSON reports for comparison.
8. Document policy scope, refusal behavior, configuration, and known
   limitations.

## Exit criteria

- Moderation is applied on the real authenticated chat path at input,
  retrieval, and output stages.
- Unauthorized retrieval remains denied before search, regardless of
  moderation classification.
- Unsafe answers are withheld and their sources are not returned.
- Chat action requests cannot invoke external side effects.
- Audit events contain policy metadata but not raw user or source content.
- Synthetic evaluations report expected outcomes, authorization denials, and
  side-effect prevention reproducibly.

## Current Phase 10 progress

The local rules and synthetic evaluation dataset are implemented in
`backend/app/moderation/` and `tests/evaluation/guardrail_cases.json`.
Run the combined evaluation with
`python -m backend.app.evaluation.run_demo_evaluation --generation-backends extractive --output data/evaluation/phase10_latest.json`;
the report includes stage-level binary metrics, per-case outcomes,
authorization checks, and side-effect prevention. In the latest synthetic
run, all 19 guardrail cases passed. Input precision/recall was 1.00 across
10 binary cases, retrieval precision/recall was 1.00 across 2 cases, and
output precision/recall was 1.00 across 3 cases. The single authorization
check was denied as expected, and the single action case had no side effect.
Two clarification cases are reported separately from binary classification.
These small fixture counts are regression evidence only, not production
performance claims.

`MODERATION_MAX_INPUT_CHARS` is bounded to 1–2000 characters (the API schema
also caps chat input at 2000), and
`MODERATION_MIN_ANSWER_SUPPORT` is a lexical threshold from 0 to 1. Defaults
are shown in `.env.example`.

The rules are deliberately local and deterministic; they are not a semantic
moderation model. They can miss paraphrases or flag benign language.
Lexical answer support is only a heuristic, not proof of entailment.
The evaluation uses fictional synthetic fixtures and is a regression check,
not a production safety certification. The standalone document-ingestion
threat scanner remains separate.

------------------------------------------------------------------------

# Phase 11 --- Hardening, Documentation, and Demonstration

## Objective

Prepare the application for a controlled end-to-end demonstration and
future deployment work.

## Implementation tasks

1.  Review authentication and authorization.
2.  Review input validation and error handling.
3.  Check secret management.
4.  Review logging and audit records.
5.  Test JSON persistence and recovery.
6.  Validate configuration for different environments.
7.  Run automated tests.
8.  Document architecture and setup.
9.  Document known limitations and proposed future improvements.
10. Prepare an end-to-end demonstration.

## Exit criteria

-   The documented setup works from a clean environment.
-   Tests pass and known failures are documented.
-   Demonstration data is fictional or explicitly authorized.
-   The system does not claim unimplemented capabilities.
-   The architecture and future database migration approach are
    documented.

------------------------------------------------------------------------

# JSON Storage and Future Database Migration

Throughout the phases, maintain the requirement that **JSON is the
initial persistence layer, and database integration comes later**.

The intended progression is:

``` text
Application services
        |
        v
Repository interfaces
        |
        +---------------------+
        |                     |
        v                     v
JSON repositories     Database repositories
Initial               Later
```

The application services should not depend directly on a particular
storage implementation.

When the project reaches the database migration stage, PostgreSQL can be
introduced for structured data, with pgvector considered for embedding
storage and similarity search. The migration should preserve the
repository contracts wherever practical.

# Recommended Implementation Order

Complete each phase and verify its exit criteria before proceeding to
the next.

-   Phase 1 establishes the project foundation.
-   Phase 2 delivers the first functional RAG capability.
-   Phase 3 improves retrieval.
-   Phase 4 introduces request orchestration.
-   Phase 5 adds enterprise permissions and auditing.
-   Phase 6 introduces sample enterprise connectors.
-   Phase 7 adds controlled operational integrations.
-   Phase 8 develops threat and fraud detection.
-   Phase 9 evaluates system quality.
-   Phase 10 adds moderation and guardrails around the chat pipeline.
-   Phase 11 prepares the project for a controlled demonstration.

**Immediate starting point: Phase 1 --- Project Foundation and JSON
Storage.**

The architecture remains designed for JSON-based storage now and a
future database integration, without changing the stated project scope.
