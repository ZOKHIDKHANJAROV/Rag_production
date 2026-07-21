import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Modifier, SparseIndexParams, SparseVectorParams, VectorParams

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "documents")
LEXICAL_COLLECTION_NAME = os.getenv("LEXICAL_COLLECTION_NAME", f"{COLLECTION_NAME}_lexical")
LEXICAL_VECTOR_NAME = "lexical"

client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
_collection_ready = False

def collection_exists(collection_name=COLLECTION_NAME):
    collections = client.get_collections().collections
    return collection_name in [c.name for c in collections]

def _ensure_payload_indexes(collection_name):
    for field in ("document_id", "is_deleted", "scope_key", "owner_username", "knowledge_base"):
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema="keyword"
            )
        except Exception:
            pass


def init_collection(vector_size: int):
    global _collection_ready

    if _collection_ready:
        return

    collections = client.get_collections().collections
    names = [c.name for c in collections]

    if COLLECTION_NAME not in names:
        print(f"Creating collection: {COLLECTION_NAME}")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=vector_size,
                distance=Distance.COSINE
            )
        )
    else:
        print(f"Collection already exists: {COLLECTION_NAME}")

    _ensure_payload_indexes(COLLECTION_NAME)
    _collection_ready = True


def init_lexical_collection():
    """Create the sparse BM25-like collection without changing the existing dense schema."""
    collections = client.get_collections().collections
    names = [collection.name for collection in collections]

    if LEXICAL_COLLECTION_NAME not in names:
        print(f"Creating lexical collection: {LEXICAL_COLLECTION_NAME}")
        client.create_collection(
            collection_name=LEXICAL_COLLECTION_NAME,
            vectors_config={},
            sparse_vectors_config={
                LEXICAL_VECTOR_NAME: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False),
                    modifier=Modifier.IDF,
                )
            },
        )

    _ensure_payload_indexes(LEXICAL_COLLECTION_NAME)
