import os


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _base_url_env(primary: str, legacy: str = "", default: str = "") -> str:
    value = os.getenv(primary) or (os.getenv(legacy) if legacy else "") or default
    value = value.strip().rstrip("/")
    return value or default


EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "local").strip().lower()
EMBEDDING_ENDPOINT_URL = os.getenv("EMBEDDING_ENDPOINT_URL", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
EMBEDDING_TIMEOUT_SECONDS = _int_env("EMBEDDING_TIMEOUT_SECONDS", 30)
RERANKER_BACKEND = os.getenv("RERANKER_BACKEND", "local").strip().lower()
RERANKER_ENDPOINT_URL = os.getenv("RERANKER_ENDPOINT_URL", "")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
RERANKER_TIMEOUT_SECONDS = _int_env("RERANKER_TIMEOUT_SECONDS", 30)
CHROMA_DIR = os.getenv("CHROMA_DIR", "./storage/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "telcomind_knowledge")
KNOWLEDGE_BASE_DIR = os.getenv("KNOWLEDGE_BASE_DIR", "./knowledge_base")
TOP_K = _int_env("TOP_K", 8)
RERANK_TOP_K = _int_env("RERANK_TOP_K", 4)
RAG_DEVICE = os.getenv("RAG_DEVICE", "auto")
CHROMA_UPSERT_BATCH_SIZE = _int_env("CHROMA_UPSERT_BATCH_SIZE", 1000)
LLM_ENABLED = _bool_env("LLM_ENABLED", False)
LLM_ENDPOINT_URL = _base_url_env("VLLM_BASE_URL", "LLM_ENDPOINT_URL", "")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
LLM_TIMEOUT_SECONDS = _int_env("LLM_TIMEOUT_SECONDS", 30)
