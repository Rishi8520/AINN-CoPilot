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


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(_int_env(name, default), maximum))


def _bounded_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(_float_env(name, default), maximum))


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


def _first_str_env(names: list[str], default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _base_url_env(primary: str, legacy: list[str] | None = None, default: str = "") -> str:
    value = _first_str_env([primary, *(legacy or [])], default)
    return value.rstrip("/") if value else default


def _synthesis_backend_env() -> str:
    raw = os.getenv("RAG_SYNTHESIS_BACKEND")
    if raw is None and _bool_env("LLM_ENABLED", False):
        value = "openai_compatible"
    else:
        value = (raw or "").strip().lower()
    if not value:
        return "deterministic"
    if value not in {"deterministic", "openai_compatible"}:
        raise ValueError("RAG_SYNTHESIS_BACKEND must be one of: deterministic, openai_compatible")
    return value


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
RAG_SYNTHESIS_BACKEND = _synthesis_backend_env()
LLM_PROVIDER = _str_env("LLM_PROVIDER", default="openai_compatible").lower()
LLM_BASE_URL = _base_url_env("LLM_BASE_URL", ["VLLM_BASE_URL", "LLM_ENDPOINT_URL"], "")
LLM_ENDPOINT_URL = LLM_BASE_URL
LLM_MODEL = _str_env("LLM_MODEL", default="")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_REQUIRED = _bool_env("LLM_REQUIRED", False)
LLM_FALLBACK_TO_DETERMINISTIC = False if LLM_REQUIRED else _bool_env(
    "LLM_FALLBACK_TO_DETERMINISTIC",
    True,
)
LLM_CONNECT_TIMEOUT_SECONDS = _bounded_float_env("LLM_CONNECT_TIMEOUT_SECONDS", 3.0, 0.1, 60.0)
LLM_READ_TIMEOUT_SECONDS = _bounded_float_env("LLM_READ_TIMEOUT_SECONDS", 30.0, 1.0, 300.0)
LLM_MAX_TOKENS = _bounded_int_env("LLM_MAX_TOKENS", 512, 1, 4096)
LLM_TEMPERATURE = _bounded_float_env("LLM_TEMPERATURE", 0.0, 0.0, 2.0)
LLM_TIMEOUT_SECONDS = int(LLM_READ_TIMEOUT_SECONDS)
LLM_ENABLED = RAG_SYNTHESIS_BACKEND == "openai_compatible"
