import os
import hashlib
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
FALLBACK_VECTOR_SIZE = int(os.getenv("FALLBACK_VECTOR_SIZE", "384"))

print(f"Loading embedding model: {MODEL_NAME}")

model = None
VECTOR_SIZE = FALLBACK_VECTOR_SIZE

try:
    model = SentenceTransformer(MODEL_NAME)
    VECTOR_SIZE = model.get_sentence_embedding_dimension()
    print(f"Embedding model loaded successfully. VECTOR_SIZE={VECTOR_SIZE}")
except Exception as e:
    print(
        "Embedding model load failed, fallback embeddings enabled. "
        f"Reason: {str(e)} | VECTOR_SIZE={VECTOR_SIZE}"
    )


def _fallback_embed_text(text: str) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    seed = int.from_bytes(digest[:8], byteorder="little", signed=False)
    rng = np.random.default_rng(seed)
    vector = rng.standard_normal(VECTOR_SIZE)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector.tolist()


def embed_texts(texts):
    if model is not None:
        embeddings = model.encode(
            texts,
            normalize_embeddings=True
        )
        return embeddings.tolist()

    return [_fallback_embed_text(text) for text in texts]
