import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
CHROMA_DIR = os.getenv("CHROMA_DIR", "./storage/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "telcomind_knowledge")
KNOWLEDGE_BASE_DIR = os.getenv("KNOWLEDGE_BASE_DIR", "./knowledge_base")
TOP_K = _int_env("TOP_K", 8)
RERANK_TOP_K = _int_env("RERANK_TOP_K", 4)
RAG_DEVICE = os.getenv("RAG_DEVICE", "auto")
CHROMA_UPSERT_BATCH_SIZE = _int_env("CHROMA_UPSERT_BATCH_SIZE", 1000)
