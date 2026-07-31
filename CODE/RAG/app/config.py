import os
from pathlib import Path


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


RAG_ROOT = Path(__file__).resolve().parents[1]


def _str_env(primary: str, legacy: str = "", default: str = "") -> str:
    value = os.getenv(primary)
    if value is None and legacy:
        value = os.getenv(legacy)
    if value is None:
        value = default
    value = value.strip()
    return value if value else default


def _path_env(primary: str, legacy: str = "", default: str = "") -> Path:
    value = _str_env(primary, legacy, default)
    path = Path(value)
    if not path.is_absolute():
        path = RAG_ROOT / path
    return path.resolve()


def _profile_env() -> str:
    value = (os.getenv("RAG_PROFILE") or "").strip().lower()
    if not value:
        return "quickstart"
    if value not in {"quickstart", "full"}:
        raise ValueError("RAG_PROFILE must be one of: quickstart, full")
    return value


def _base_url_env(primary: str, legacy: str = "", default: str = "") -> str:
    value = os.getenv(primary) or (os.getenv(legacy) if legacy else "") or default
    value = value.strip().rstrip("/")
    return value or default


RAG_PROFILE = _profile_env()
RAG_QUICKSTART_CORPUS_PATH = _path_env(
    "RAG_QUICKSTART_CORPUS_PATH",
    default="quickstart/corpus.jsonl",
)
RAG_QUICKSTART_MANIFEST_PATH = RAG_QUICKSTART_CORPUS_PATH.with_name("manifest.json")
RAG_QUICKSTART_TOP_K = max(1, min(_int_env("RAG_QUICKSTART_TOP_K", 5), 20))
RAG_FULL_INDEX_PATH = _path_env("RAG_FULL_INDEX_PATH", "CHROMA_DIR", "./storage/chroma")
RAG_AUTO_INGEST = _bool_env("RAG_AUTO_INGEST", False)
RAG_STRICT_PROVENANCE = _bool_env("RAG_STRICT_PROVENANCE", True)

EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "local").strip().lower()
EMBEDDING_ENDPOINT_URL = os.getenv("EMBEDDING_ENDPOINT_URL", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
EMBEDDING_TIMEOUT_SECONDS = _int_env("EMBEDDING_TIMEOUT_SECONDS", 30)
RERANKER_BACKEND = os.getenv("RERANKER_BACKEND", "local").strip().lower()
RERANKER_ENDPOINT_URL = os.getenv("RERANKER_ENDPOINT_URL", "")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
RERANKER_TIMEOUT_SECONDS = _int_env("RERANKER_TIMEOUT_SECONDS", 30)
CHROMA_DIR = str(RAG_FULL_INDEX_PATH)
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
