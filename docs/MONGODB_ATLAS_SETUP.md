# MongoDB Atlas connection setup

Knowledge document metadata, extracted chunks, and search vectors are stored
in MongoDB Atlas. Audit and other runtime records remain in their existing
stores. New document uploads remain disabled until Atlas Vector Search has
been configured and verified.

## 1. Prepare Atlas access

In Atlas:

1. Create a project and cluster. Choose a region near the backend runtime.
   Since the production runtime is not decided yet, use the development
   environment for now and select a tier that Atlas currently supports for
   Vector Search.
2. Under **Security → Database Access**, create a password-authenticated
   database user. Give it `readWrite` on the `knowledgeops` database. This
   is separate from your Atlas website login.
3. Under **Security → Network Access**, add the current development machine's
   public IP. Do not use `0.0.0.0/0`; add the production backend's network
   separately when it is known.
4. Copy the cluster's Python driver connection string. Replace its username
   and password placeholders locally; percent-encode reserved characters in
   the password if needed.

## 2. Configure the backend

Put the connection string in the ignored repository-root `.env` file, not in
frontend configuration or source control:

```dotenv
MONGODB_URI=mongodb+srv://<database-user>:<encoded-password>@<cluster-host>/?retryWrites=true&w=majority
MONGODB_DATABASE=knowledgeops
KNOWLEDGE_STORE_BACKEND=mongodb
MONGODB_DOCUMENTS_COLLECTION=knowledge_documents
MONGODB_CHUNKS_COLLECTION=knowledge_chunks
MONGODB_VECTOR_INDEX=knowledge_vector_index
MONGODB_VECTOR_DIMENSIONS=768
ATLAS_VECTOR_MIN_SCORE=0.0
RAG_BACKEND=atlas
KNOWLEDGE_INGESTION_ENABLED=false
```

Keep the URI secret and do not paste it into chat, issues, or logs. The backend
uses PyMongo's default connection pool settings; tune them only after the
deployment and expected concurrency are known.
The default `nomic-embed-text:latest` Ollama embedding model returns 768
dimensions. If you select another embedding model, set
`MONGODB_VECTOR_DIMENSIONS` to its actual output size and use the same value
in the Atlas vector index definition.

## 3. Verify connectivity

From the repository root, install the updated backend dependencies if needed,
then run:

```powershell
python -m pip install -e .
python -m backend.app.storage.mongodb
```

The check reports success only after MongoDB responds to `ping`. It does not
create collections, upload documents, or expose the connection string. If it
fails, verify the database username/password, the Atlas network access list,
and that the URI is copied from the intended cluster.

## 4. Prepare collections and Atlas Vector Search

From the project root, create the two empty collections and their ordinary
indexes:

```powershell
python -m backend.app.storage.mongodb_prepare
```

This prepares `knowledge_documents` and `knowledge_chunks` without writing
document content. In Atlas, open **Database → Search & Vector Search** (or
**Atlas Search**) and create a **Vector Search** index on
`knowledgeops.knowledge_chunks`. Use the index name
`knowledge_vector_index` and this definition for the default Ollama model:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 768,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "access_scope"
    }
  ]
}
```

If you change embedding model or dimensions, adjust `numDimensions` and
`MONGODB_VECTOR_DIMENSIONS` together. Wait for the index status to become
**Ready** before starting retrieval. Atlas Vector Search applies the
authenticated user's allowed scopes as a server-side filter and checks the
returned scope again in the application. The minimum score defaults to `0.0`
so no relevance threshold is assumed before evaluation; adjust
`ATLAS_VECTOR_MIN_SCORE` only after reviewing retrieval results.

The selected M0 cluster is suitable for connection and vector-query testing.
MongoDB's [deployment guidance](https://www.mongodb.com/docs/vector-search/deployment/deployment-options/)
recommends Flex for a small proof-of-concept and M10/M20 for application
prototyping; evaluate cost and capacity before upgrading.

## 5. Verify the app before enabling uploads

Start the backend and frontend using the existing local setup. Confirm chat
retrieves only expected fictional seed content and that a user without the
matching scope receives no restricted sources. The first retrieval initializes
the Atlas index and writes only the repository's fictional seed chunks to
`knowledge_chunks`. If Atlas reports a missing index, confirm the index name,
collection, dimensions, and Ready status.

Keep `KNOWLEDGE_INGESTION_ENABLED=false` until that check succeeds. Then set it
to `true` in the backend `.env` to allow authorized uploads. Existing JSON
document files and local Qdrant data are not automatically migrated; retain
them for recovery and migrate only through a separately verified procedure.

If `data/runtime/knowledge.json` already contains uploaded documents, run the
migration command first in its default dry-run mode:

```powershell
python -m backend.app.storage.migrate_knowledge_to_mongodb
```

It reports document and chunk counts by access scope and does not connect to
Atlas. Review the counts and confirm the vector index is **Ready**, then run
the explicit write mode:

```powershell
python -m backend.app.storage.migrate_knowledge_to_mongodb --apply
```

The migration preserves `access_scope`, verifies existing destination records
before writing, re-embeds imported chunks, and leaves the JSON source untouched.
If it stops on a conflict, do not delete either copy; resolve the conflict
before rerunning. The write command is resumable for documents that already
match, but records already stored with different metadata or chunks require
manual review.
