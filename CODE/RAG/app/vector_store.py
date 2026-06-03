import hashlib
import json
import urllib.request
import torch
import chromadb
from sentence_transformers import CrossEncoder, SentenceTransformer
from app import config
from app.chunking import Chunk


def _batch_slices(total: int, batch_size: int):
    for start in range(0, total, batch_size):
        yield slice(start, min(start + batch_size, total))


class TelcoVectorStore:
    def __init__(self):
        device = self._choose_device()
        self.embedding_model = SentenceTransformer(config.EMBEDDING_MODEL, device=device)
        self.reranker = self._load_reranker(device)
        self.client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        self.collection = self.client.get_or_create_collection(
            name=config.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _choose_device(self) -> str:
        if config.RAG_DEVICE in {"cpu", "cuda"}:
            return config.RAG_DEVICE
        return "cuda" if torch.cuda.is_available() else "cpu"

    def _load_reranker(self, device: str):
        if config.RERANKER_BACKEND == "disabled":
            return None
        try:
            return CrossEncoder(config.RERANKER_MODEL, device=device)
        except Exception:
            return None

    def _post_json(self, url: str, payload: dict, timeout_seconds: int) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _local_embeddings(self, texts: list[str], show_progress_bar: bool = False) -> list[list[float]]:
        return self.embedding_model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=show_progress_bar,
        ).tolist()

    def _parse_embedding_response(self, payload: dict, expected_count: int) -> list[list[float]]:
        embeddings = payload.get("embeddings")
        if embeddings is None and isinstance(payload.get("data"), list):
            embeddings = [item.get("embedding") for item in payload["data"] if isinstance(item, dict)]

        if not isinstance(embeddings, list) or len(embeddings) != expected_count:
            raise ValueError("Embedding service returned an invalid number of embeddings.")

        parsed = []
        for embedding in embeddings:
            if not isinstance(embedding, list) or not embedding:
                raise ValueError("Embedding service returned an invalid embedding.")
            parsed.append([float(value) for value in embedding])
        return parsed

    def _external_embeddings(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": config.EMBEDDING_MODEL,
            "input": texts,
        }
        response = self._post_json(
            config.EMBEDDING_ENDPOINT_URL,
            payload,
            config.EMBEDDING_TIMEOUT_SECONDS,
        )
        return self._parse_embedding_response(response, len(texts))

    def _encode_texts(self, texts: list[str], show_progress_bar: bool = False) -> list[list[float]]:
        if config.EMBEDDING_BACKEND == "external" and config.EMBEDDING_ENDPOINT_URL.strip():
            try:
                return self._external_embeddings(texts)
            except Exception:
                pass
        return self._local_embeddings(texts, show_progress_bar=show_progress_bar)

    def _local_rerank_scores(self, query: str, candidates: list[dict]) -> list[float] | None:
        if not self.reranker:
            return None
        pairs = [(query, item["text"]) for item in candidates]
        return [float(score) for score in self.reranker.predict(pairs)]

    def _parse_reranker_response(self, payload: dict, expected_count: int) -> list[float]:
        scores = payload.get("scores")
        if scores is None and isinstance(payload.get("results"), list):
            scores = [None] * expected_count
            for item in payload["results"]:
                if not isinstance(item, dict):
                    raise ValueError("Reranker service returned an invalid result.")
                index = int(item["index"])
                if index < 0 or index >= expected_count:
                    raise ValueError("Reranker service returned an out-of-range index.")
                scores[index] = float(item["score"])

        if not isinstance(scores, list) or len(scores) != expected_count:
            raise ValueError("Reranker service returned an invalid number of scores.")
        return [float(score) for score in scores]

    def _external_rerank_scores(self, query: str, candidates: list[dict]) -> list[float]:
        payload = {
            "model": config.RERANKER_MODEL,
            "query": query,
            "documents": [item["text"] for item in candidates],
        }
        response = self._post_json(
            config.RERANKER_ENDPOINT_URL,
            payload,
            config.RERANKER_TIMEOUT_SECONDS,
        )
        return self._parse_reranker_response(response, len(candidates))

    def _rerank_scores(self, query: str, candidates: list[dict]) -> list[float] | None:
        if config.RERANKER_BACKEND == "disabled":
            return None
        if config.RERANKER_BACKEND == "external" and config.RERANKER_ENDPOINT_URL.strip():
            try:
                return self._external_rerank_scores(query, candidates)
            except Exception:
                pass
        return self._local_rerank_scores(query, candidates)

    def count(self) -> int:
        return self.collection.count()

    def _upsert_batch_size(self) -> int:
        configured_batch_size = max(1, config.CHROMA_UPSERT_BATCH_SIZE)
        get_max_batch_size = getattr(self.client, "get_max_batch_size", None)
        if callable(get_max_batch_size):
            try:
                return max(1, min(configured_batch_size, int(get_max_batch_size())))
            except Exception:
                return configured_batch_size

        max_batch_size = getattr(self.client, "max_batch_size", None)
        if isinstance(max_batch_size, int):
            return max(1, min(configured_batch_size, max_batch_size))
        return configured_batch_size

    def ingest(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0

        ids = []
        texts = []
        metadatas = []
        for chunk in chunks:
            digest = hashlib.sha256(
                f"{chunk.metadata.get('source')}:{chunk.metadata.get('section')}:{chunk.text}".encode("utf-8")
            ).hexdigest()[:24]
            ids.append(digest)
            texts.append(chunk.text)
            metadatas.append(chunk.metadata)

        embeddings = self._encode_texts(texts, show_progress_bar=True)

        upsert_batch_size = self._upsert_batch_size()
        for batch_slice in _batch_slices(len(ids), upsert_batch_size):
            self.collection.upsert(
                ids=ids[batch_slice],
                documents=texts[batch_slice],
                embeddings=embeddings[batch_slice],
                metadatas=metadatas[batch_slice],
            )
        return len(ids)

    def search(self, query: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or config.TOP_K
        query_embedding = self._encode_texts([query])[0]

        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        candidates = []
        for idx, doc in enumerate(result.get("documents", [[]])[0]):
            metadata = result.get("metadatas", [[]])[0][idx]
            distance = result.get("distances", [[]])[0][idx]
            candidates.append(
                {
                    "id": result.get("ids", [[]])[0][idx],
                    "text": doc,
                    "metadata": metadata,
                    "score": 1.0 - float(distance),
                }
            )

        if candidates:
            rerank_scores = self._rerank_scores(query, candidates)
        else:
            rerank_scores = None

        if rerank_scores is not None:
            for item, score in zip(candidates, rerank_scores):
                item["score"] = float(score)
            candidates.sort(key=lambda x: x["score"], reverse=True)

        return candidates[: config.RERANK_TOP_K]
