from sentence_transformers import SentenceTransformer
import os
import torch

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

device = "cuda" if torch.cuda.is_available() else "cpu"

print(f"Loading embedding model: {MODEL_NAME} on {device}")

model = SentenceTransformer(
    MODEL_NAME,
    device=device
)

VECTOR_SIZE = model.get_sentence_embedding_dimension()


def embed_texts(texts: list[str]) -> list[list[float]]:

    embeddings = model.encode(
        texts,
        batch_size=64,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False
    )

    return embeddings.tolist()