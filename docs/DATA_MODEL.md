# Data model

## Knowledge documents

The knowledge repository stores document metadata and extracted chunks in
`data/runtime/knowledge.json` (override with `KNOWLEDGE_STORE_PATH`). The
initial repository contains no documents; content becomes searchable only
after an authorized upload.

Each document record contains:

| Field | Meaning |
| --- | --- |
| `document_id` | Unique ID used by chunk references and citations |
| `title`, `filename`, `document_type` | Display metadata and uploaded format |
| `source`, `access_scope` | Origin label and retrieval permission scope |
| `sha256` | Content hash used to reject duplicate uploads |
| `uploaded_at`, `chunk_count` | Ingestion timestamp and extracted chunk count |
| `owner`, `version`, `effective_date`, `next_review`, `environment` | Optional source metadata |

Chunk records contain their ID, parent document ID, ordinal, section, source
path, extracted text, access scope, and source metadata needed for retrieval
and citations. JSON writes use atomic replacement; invalid JSON, invalid
records, or broken references raise an explicit corruption error and are not
overwritten. Deleting a document removes its chunks from JSON and its vectors
from the active index.

Original uploaded bytes are not retained. PDF uploads are limited to 10 MiB,
100 pages, and 500,000 extracted characters. DOCX uploads are limited to
10 MiB, 2,000 archive entries, 20 MiB expanded content, and 500,000 extracted
characters. Encrypted, malformed, empty, or unsupported documents are
rejected.

Embedded Qdrant vectors are stored separately under `data/runtime/qdrant/`;
they are derived search data, not the authoritative document store. Changing
the embedding model creates a distinct collection. Audit and user profile
records use JSON files under the same ignored runtime directory. Chat question
and answer history is not persisted.

The local JSON and embedded-vector stores are single-machine development
components. Backups, retention/deletion policy, encryption, multi-process
access, and a production storage service require explicit design and approval.
