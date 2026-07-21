# Advanced RAG

The retrieval pipeline uses both semantic and lexical evidence while preserving
the existing personal-document and global-document scope filters.

```mermaid
flowchart LR
    D["Document"] --> C["Section-aware chunking"]
    C --> M["Metadata: title, section, date, type"]
    M --> E["Dense embeddings"]
    M --> S["Sparse lexical vector"]
    E --> QD["Qdrant dense collection"]
    S --> QS["Qdrant lexical collection"]
    U["Question"] --> DE["Dense retrieval"]
    U --> SP["Sparse retrieval"]
    QD --> DE
    QS --> SP
    DE --> RRF["RRF fusion"]
    SP --> RRF
    RRF --> F["Scope and relevance filter"]
    F --> RR["Lightweight reranking and diversity"]
    RR --> CF["Context fusion"]
    CF --> LLM["Grounded answer with citations"]
```

## Retrieval stages

1. **Dense retrieval** finds semantically similar chunks using the configured
   embedding model.
2. **Sparse retrieval** finds exact terms, identifiers, file names, headings,
   and domain vocabulary. Title, section, and filename tokens receive a small
   boost during indexing.
3. **RRF fusion** rewards chunks that both retrieval channels agree on, without
   requiring their score scales to match.
4. **Filtering and reranking** discard weak candidates, limit repeated chunks
   from one document, and use MMR-style diversity to keep the context useful.
5. **Context fusion** joins selected chunks from the same document under one
   stable citation label. The LLM receives only this evidence and is instructed
   to cite factual claims as `[filename]`.

## Operations

- `documents` remains the existing dense Qdrant collection.
- `documents_lexical` is created automatically for sparse vectors. Override
  its name with `LEXICAL_COLLECTION_NAME` when needed.
- Documents uploaded after this change are indexed in both collections.
  Re-upload existing documents once to add them to the lexical collection; the
  dense collection keeps serving those documents until then.
- `RAG_SPARSE_SCORE_THRESHOLD` controls the lexical relevance floor.
  `RAG_RRF_K` controls fusion smoothness. `RAG_MMR_LAMBDA` balances relevance
  against duplicate context.
