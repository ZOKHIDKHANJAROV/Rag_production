import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "documents")

client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
_collection_ready = False

def collection_exists():
    collections = client.get_collections().collections
    return COLLECTION_NAME in [c.name for c in collections]

def _ensure_payload_indexes():
    for field in ("document_id", "is_deleted"):
        try:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
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

    _ensure_payload_indexes()
    _collection_ready = True
