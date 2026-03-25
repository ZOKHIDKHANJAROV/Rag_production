from sentence_transformers import SentenceTransformer
import os

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

print(f"Loading embedding model: {MODEL_NAME}")

model = SentenceTransformer(MODEL_NAME)

VECTOR_SIZE = model.get_sentence_embedding_dimension()

def embed_texts(texts):
    embeddings = model.encode(
        texts,
        normalize_embeddings=True
    )
    return embeddings.tolist()
