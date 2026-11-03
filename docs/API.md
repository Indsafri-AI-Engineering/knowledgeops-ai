# API

The versioned API is under `/api/v1`. `GET /health` is retained for
compatibility; `GET /api/v1/health` is the versioned endpoint.

## Authentication

The application uses OIDC bearer authentication by default. Configure
`OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, `OIDC_GROUPS_CLAIM`, and the
allowlisted `OIDC_GROUP_CAPABILITIES` mapping in the backend `.env`. The
frontend OIDC client is configured separately in `frontend/.env.local`, based
on `frontend/.env.example`. The backend verifies the provider signature,
issuer, audience, expiry, and required claims. A user's source access is
derived from server-side capabilities; client-supplied roles and capabilities
are not trusted.

Knowledge-document upload, listing, and deletion require `knowledge:manage`.
Successful document listings and mutations, chat requests, and authorization
denials are recorded in the JSONL audit log. Audit metadata excludes document
and question text. `GET /api/v1/audit-events` requires `audit:read`.

The fixed demo identity endpoints and mock connector routes are disabled by
default. Threat scans are available to authenticated users with
`threat_scans:scan`; the scanner is local and does not fetch URLs, execute
files, or persist submitted artifact contents.

## Jira Cloud

The versioned Jira API connects to Jira Cloud with a backend-only service
account. Configure `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN` in the
ignored backend `.env` file. The base URL must use HTTPS. Never put the API
token in frontend configuration or source control. The Jira panel reports
whether credentials are configured without exposing them.

| Method | Endpoint | Required capability | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/jira/status` | Authenticated user | Report whether Jira is configured |
| `GET` | `/api/v1/jira/projects` | `jira:read` | List projects visible to the service account |
| `GET` | `/api/v1/jira/projects/{project_key}/issue-types` | `jira:read` | List createable issue types |
| `GET` | `/api/v1/jira/issues` | `jira:read` | Search issues, optionally by project |
| `POST` | `/api/v1/jira/issues` | `jira:approve` | Create an issue after explicit confirmation |
| `PATCH` | `/api/v1/jira/issues/{issue_key}` | `jira:approve` | Update summary, description, or priority |
| `POST` | `/api/v1/jira/issues/{issue_key}/comments` | `jira:approve` | Add a confirmed comment |
| `GET` | `/api/v1/jira/issues/{issue_key}/transitions` | `jira:read` | List available workflow transitions |
| `POST` | `/api/v1/jira/issues/{issue_key}/transitions` | `jira:approve` | Apply a confirmed transition |

Write calls require `confirmed: true` and a user authorized with
`jira:approve`; the UI prompts before submitting them. Jira actions are
audited with issue identifiers and action names, not comment or description
text. Jira operations use the configured service account's project
permissions, so grant it only the access required for the selected projects.
The application stores its knowledge corpus and audit records locally;
individual chat questions and answers are not persisted. Connecting Jira does
not migrate those stores.

## Threat detection and security alerts

Threat detection is separate from knowledge retrieval. The
`/knowledge/security` OIDC group receives scan, alert-read, and alert-review
capabilities in `.env.example`. The `system:admin` capability also grants
alert access. Existing deployments should add `security_alerts:read` and
`security_alerts:manage` to the intended groups in their local
`OIDC_GROUP_CAPABILITIES`; the existing `threat_scans:scan` capability remains
a compatible security-analyst grant.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/threat-scans/urls` | Validate a URL and report deterministic local indicators; never fetches it |
| `POST` | `/api/v1/threat-scans/emails` | Inspect pasted email headers/body and extract URLs without fetching them |
| `POST` | `/api/v1/threat-scans/documents` | Inspect pasted text for `.txt`, `.md`, or `.eml`; does not accept or execute files |
| `GET` | `/api/v1/security/alerts?status=open&limit=100` | List redacted alerts for authorized analysts |
| `PATCH` | `/api/v1/security/alerts/{alert_id}` | Acknowledge, resolve, or mark an alert false positive |
| `POST` | `/api/v1/security/alerts/{alert_id}/response-workflow` | Dispatch an analyst-confirmed response request to configured n8n |

Knowledge uploads receive two inspections: a bounded raw-file preflight before
document parsers run, then a security scan of extracted text before any chunk
is indexed or sent to an embedding provider. High-severity credential/key
indicators block ingestion by default. Change
`THREAT_INGESTION_BLOCK_SEVERITY` (`info`, `low`, `medium`, `high`,
`critical`) only after reviewing false-positive and data-handling
implications. Lower-severity findings create alerts but do not block by
default.

Requests are size-limited. Alerts retain rule IDs, descriptions, severity,
detector version, actor, and a document fingerprint; matched values, source
text, and filenames are not persisted in the alert. Audit events do not
include submitted content. Repeated authentication or authorization denials
generate an alert using the configurable
`SECURITY_DENIAL_THRESHOLD`, `SECURITY_DENIAL_WINDOW_SECONDS`, and
`SECURITY_DENIAL_ALERT_COOLDOWN_SECONDS`; unauthenticated source identifiers
are hashed before audit storage. This event monitor is in-process and its
rolling counter resets on restart.

Configure both `N8N_ALERT_WEBHOOK_URL` and `N8N_ALERT_WEBHOOK_TOKEN` to enable
automatic security-alert notifications. Security events use this dedicated
webhook and are never sent to the Jira webhook. The backend sends the token as
`Authorization: Bearer <token>`; HTTPS is required except for localhost
development. A configured URL without a token is treated as a failed
notification and is not called.

The `knowledgeops.security.alert` payload contains only the event name, alert
ID, type, severity, detector version, rule IDs, and timestamp. It contains no
document text, extracted content, credentials, matched secrets, or file
contents. Configure recipient groups and severity routing in n8n: critical and
high to the Administrator and Security Team, medium to the Security Team, and
low to dashboard logging with an optional summary notification. Keep group
addresses or identifiers in n8n configuration, not in this app or in webhook
payloads.

`notification_status` on an alert is `sent` only when the webhook responds
with a successful 2xx status; it confirms webhook delivery, not downstream
email or chat delivery. A missing URL returns `not_configured`; missing/invalid
credentials, non-2xx responses (including invalid authentication), connection
errors, and timeouts return `failed`. Alert creation and storage are not rolled
back when notification delivery fails. The backend makes one bounded request
and does not retry.

An authorized analyst must acknowledge an alert and explicitly confirm a
response-workflow request before the app dispatches that separate event to
n8n. Notifications do not automatically remediate threats, delete documents,
block users, resolve alerts, or create Jira issues. The app does not accept
inbound n8n response commands.

An optional `N8N_JIRA_WEBHOOK_URL` sends a `knowledgeops.jira.issue_created`
event only after Jira confirms issue creation. The payload contains the event,
issue key, project key, and Jira browse URL; it omits issue summary and
description. Configure `N8N_JIRA_WEBHOOK_TOKEN` separately from the security
alert token. A webhook delivery failure is reported as `notification_status:
"failed"` in the successful Jira creation response and does not misreport the
Jira issue itself as failed. Missing configuration reports
`notification_status: "not_configured"`.
See [N8N_SETUP.md](N8N_SETUP.md) for workflow and environment setup.

The scanner does not provide antivirus, malware detonation, external
reputation lookups, or a full DLP classifier. `no-known-indicator` is not
proof of safety; results are risk signals for human review, not confirmed
fraud or malware determinations. Run the focused suite with
`python -m pytest tests\\unit\\test_threat_scans.py tests\\unit\\test_security_alerts.py tests\\unit\\test_knowledge_documents.py tests\\evaluation\\test_phase9_evaluation.py -q`.

## Knowledge documents

The corpus starts empty. Users with `knowledge:manage` may upload, list, and
delete documents:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/knowledge/documents` | List indexed document metadata |
| `POST` | `/api/v1/knowledge/documents` | Validate, extract, chunk, and index a supported document |
| `DELETE` | `/api/v1/knowledge/documents/{document_id}` | Remove the document and its searchable chunks |

`POST` accepts multipart form fields:

| Field | Required | Description |
| --- | --- | --- |
| `file` | Yes | PDF, DOCX, TXT, MD, HTML, XLSX, or PPTX; maximum 10 MiB |
| `title` | No | Display title, maximum 200 characters; defaults to the filename without its extension |
| `access_scope` | Yes | `general`, `hr`, `it`, or `recruitment` |
| `owner`, `version`, `effective_date`, `next_review`, `environment` | No | Optional source metadata |

The Knowledge documents UI accepts up to 50 files in one selection and uploads
them sequentially with one shared access scope. Each result is reported
individually; a failure or duplicate does not prevent later files from being
processed. Duplicate detection uses the SHA-256 hash of the uploaded file
bytes, so identical files are rejected even when their filenames differ.

PDFs are limited to 100 pages and 500,000 extracted characters. DOCX, XLSX,
and PPTX archives are limited to 2,000 entries, 20 MiB expanded content, and
500,000 extracted characters. HTML ingestion excludes script, style,
template, and noscript content. Text formats must be UTF-8. Encrypted,
malformed, empty, unsupported, and image-only PDF documents are rejected.
The original uploaded bytes are not retained. The response includes the
document ID, content hash, file type, upload timestamp, and chunk count.

Document metadata and extracted chunks are stored in MongoDB Atlas in the
`knowledge_documents` and `knowledge_chunks` collections by default. Each
chunk stores its text and derived embedding; document metadata is stored once
in the documents collection. Atlas Vector Search uses the configured
`MONGODB_VECTOR_INDEX` index. The vector index must include an `access_scope`
filter field, and retrieval applies the authenticated user's allowed scopes
server-side before returning matches. `KNOWLEDGE_INGESTION_ENABLED` defaults
to `false`; enable it only after the Atlas storage and vector-search path have
been verified. Existing local JSON and Qdrant data are not migrated
automatically.

## Chat and citations

`POST /api/v1/chat` accepts `question` and optional `retrieval_mode` (`vector`,
`keyword`, or `hybrid`). Each request is independent: chat requests do not
accept conversation IDs, use previous turns as context, or persist questions
and answers. Responses contain only the current question and answer. `vector`
uses dense embedding search, `keyword` uses BM25, and `hybrid` fuses the dense
and BM25 rankings with Reciprocal Rank Fusion (RRF, `k=60`). Each retriever
fetches up to five times the requested result count before fusion; duplicate
chunks across retrievers contribute once per ranking. Scope restrictions are
applied independently to both candidate sets before ranking. The backend
filters documents by the authenticated user's capabilities before retrieval.
HR, IT, and recruitment requests require their corresponding knowledge scope.
If the authenticated user lacks that scope, chat returns an authorization
message with no source citations and does not search the knowledge index.
Answers return source references and indicate when no supporting evidence
was found. Empty retrieval does not invoke the generation model. The employee
demo role is limited to `general`; IT knowledge is limited to the IT-support
role.

Chat responses include `intent`, `route_category` (`knowledge`, `workflow`,
`analytical`, or `unsupported`), and `route_component`. Knowledge and
knowledge-analysis requests use permission-filtered retrieval; analysis
prompts may compare or summarize only the retrieved evidence. Jira and threat
requests are routed to workflow components but are not executed by chat.
Fictional Jira search is available only in fixture-enabled tests; no live
external workflow is invoked. Unsupported action requests return a planned
response with no external side effect.

The configured local profile uses Ollama embeddings and chat generation.
Groq and Mistral require explicit provider selection, credentials, and
`AI_DATA_CLASS=synthetic`; the flag is an operator assertion. Do not use
hosted providers with real, confidential, personal, or otherwise
unapproved content. Provider calls are not made as part of startup or this
documentation workflow.

## Other active endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/me` | Return the authenticated identity and capabilities |
| `GET` | `/api/v1/system/status` | Report selected and disabled application components |
| `GET` | `/api/v1/audit-events?limit=100` | Read audit events with `audit:read` |

Request IDs are returned in `X-Request-ID`. Audit records omit question and
document text. Audit, alert, and user-profile JSON stores and in-process
sessions, caches, and locks remain single-process development components;
retention, backups, production identity, and deployment controls still
require approval.
