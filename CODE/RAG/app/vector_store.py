import hashlib
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
        try:
            return CrossEncoder(config.RERANKER_MODEL, device=device)
        except Exception:
            return None

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

        embeddings = self.embedding_model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=True,
        ).tolist()

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
        query_embedding = self.embedding_model.encode(
            [query],
            normalize_embeddings=True,
        ).tolist()[0]

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

        if self.reranker and candidates:
            pairs = [(query, item["text"]) for item in candidates]
            rerank_scores = self.reranker.predict(pairs)
            for item, score in zip(candidates, rerank_scores):
                item["score"] = float(score)
            candidates.sort(key=lambda x: x["score"], reverse=True)

        return candidates[: config.RERANK_TOP_K]
