from sentence_transformers import SentenceTransformer
import os
from functools import lru_cache

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))


@lru_cache(maxsize=1)
def get_model():
    print(f"Loading embedding model: {MODEL_NAME}", flush=True)
    return SentenceTransformer(MODEL_NAME)

def get_vector_size():
    return get_model().get_sentence_embedding_dimension()

def embed_texts(texts):
    embeddings = get_model().encode(
        texts,
        normalize_embeddings=True,
        batch_size=EMBEDDING_BATCH_SIZE,
        show_progress_bar=False
    )
    return embeddings.tolist()
