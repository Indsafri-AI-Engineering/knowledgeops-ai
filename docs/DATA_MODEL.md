# Data model

## Knowledge documents

The knowledge repository stores document metadata and extracted chunks in
MongoDB Atlas collections `knowledge_documents` and `knowledge_chunks`
(configurable with `MONGODB_DOCUMENTS_COLLECTION` and
`MONGODB_CHUNKS_COLLECTION`). The repository has no uploaded user documents
until an authorized upload; the fictional seed corpus is indexed from its
source files.

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
path, extracted text, access scope, source metadata, and a derived embedding.
Chunks are separate documents so retrieval can index them individually and
documents are not subject to unbounded embedded arrays or the 16 MB document
limit. The vector index must include `access_scope` as a filter field. Every
Atlas vector query filters on server-derived allowed scopes, then the
application checks returned scopes before using results. Deleting a document
removes its metadata and chunk records.

Original uploaded bytes are not retained. PDF uploads are limited to 10 MiB,
100 pages, and 500,000 extracted characters. DOCX uploads are limited to
10 MiB, 2,000 archive entries, 20 MiB expanded content, and 500,000 extracted
characters. Encrypted, malformed, empty, or unsupported documents are
rejected.

Embeddings are derived search data stored with chunk records in Atlas
`knowledge_chunks`; `MONGODB_VECTOR_INDEX` identifies the Atlas Vector Search
index, and `MONGODB_VECTOR_DIMENSIONS` must match the configured embedding
model. Each vector records its embedding-model identity so a model change
causes chunks to be re-embedded rather than silently mixing vector spaces.
Changing vector dimensions also requires updating the Atlas index definition.
Audit and user profile records continue to use local JSON files. Chat question
and answer history is not persisted.

The local JSON stores outside knowledge documents remain single-machine
development components. Backups, retention/deletion policy, encryption,
multi-process access, and production deployment controls require explicit
design and approval.
