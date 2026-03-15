"""Shared embedding utilities for OpenMemory and signal processing."""
import json, math, os, struct, sys
from urllib.request import urlopen, Request
from urllib.error import URLError

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/embeddings")
OLLAMA_MODEL = "nomic-embed-text"


def get_embedding(text):
    """Get embedding vector from Ollama. Returns None if unavailable."""
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": text}).encode()
    req = Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("embedding")
    except (URLError, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"embedding: {type(e).__name__} — {e}", file=sys.stderr)
        return None


def cosine_similarity(vec_a, vec_b):
    """Cosine similarity between two vectors."""
    if len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embedding_to_blob(vec):
    """Serialize float vector to binary blob for SQLite storage."""
    return struct.pack(f"<{len(vec)}f", *vec)


def blob_to_embedding(blob):
    """Deserialize binary blob back to float list."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))
