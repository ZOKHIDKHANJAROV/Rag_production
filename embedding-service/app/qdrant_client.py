import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "documents")

client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

def init_collection(vector_size: int):
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
