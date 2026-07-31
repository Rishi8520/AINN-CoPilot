from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app import config
from app.quickstart_corpus import QuickstartCorpus, load_quickstart_corpus


TOKEN_RE = re.compile(r"[a-zA-Z0-9]+(?:[-_][a-zA-Z0-9]+)*")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "about",
    "before",
    "can",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "of",
    "or",
    "should",
    "this",
    "the",
    "to",
    "using",
    "what",
    "when",
    "which",
    "why",
    "with",
}
ACRONYM_ALIASES = {
    "oran": {"o-ran", "oran"},
    "o-ran": {"o-ran", "oran"},
    "ngran": {"ng-ran", "ngran", "ng", "ran"},
    "ng-ran": {"ng-ran", "ngran", "ng", "ran"},
    "5g": {"5g", "nr"},
    "nr": {"nr", "5g"},
    "handover": {"handover", "hand-over"},
    "hand-over": {"handover", "hand-over"},
    "sinr": {"sinr"},
    "rsrp": {"rsrp"},
    "rsrq": {"rsrq"},
    "prb": {"prb"},
    "kpi": {"kpi", "measurement", "measurements"},
}


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text.lower()):
        normalized = raw.replace("_", "-")
        variants = {normalized, normalized.replace("-", "")}
        variants.update(ACRONYM_ALIASES.get(normalized, set()))
        variants.update(ACRONYM_ALIASES.get(normalized.replace("-", ""), set()))
        for token in sorted(variants):
            if token and token not in STOP_WORDS:
                tokens.append(token)
    return tokens


class LexicalBM25Retriever:
    retrieval_backend = "lexical_bm25"
    corpus_profile = "quickstart"
    score_type = "bm25_raw"

    def __init__(
        self,
        corpus_path: Path | None = None,
        *,
        strict_provenance: bool | None = None,
        top_k: int | None = None,
    ):
        self.corpus: QuickstartCorpus = load_quickstart_corpus(
            corpus_path,
            strict_provenance=strict_provenance,
        )
        self.default_top_k = top_k or config.RAG_QUICKSTART_TOP_K
        self._doc_tokens = [tokenize(chunk.text) for chunk in self.corpus.chunks]
        self._doc_lengths = [len(tokens) for tokens in self._doc_tokens]
        self._avgdl = sum(self._doc_lengths) / len(self._doc_lengths)
        self._term_counts = [Counter(tokens) for tokens in self._doc_tokens]
        self._doc_freq: Counter[str] = Counter()
        for counts in self._term_counts:
            self._doc_freq.update(counts.keys())

    def count(self) -> int:
        return len(self.corpus.chunks)

    def capabilities(self) -> dict[str, Any]:
        return {
            "rag_profile": self.corpus_profile,
            "retrieval_backend": self.retrieval_backend,
            "corpus_id": self.corpus.corpus_id,
            "corpus_version": self.corpus.version,
            "chunk_count": len(self.corpus.chunks),
            "score_type": self.score_type,
        }

    def search(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(int(top_k or self.default_top_k), 20))
        query_terms = tokenize(query)
        if not query_terms:
            return []
        query_counts = Counter(query_terms)
        scores: list[tuple[float, int]] = []
        n_docs = len(self.corpus.chunks)
        k1 = 1.5
        b = 0.75

        for doc_index, counts in enumerate(self._term_counts):
            score = 0.0
            doc_len = self._doc_lengths[doc_index] or 1
            for term, query_weight in query_counts.items():
                tf = counts.get(term, 0)
                if tf <= 0:
                    continue
                df = self._doc_freq.get(term, 0)
                idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                denom = tf + k1 * (1.0 - b + b * doc_len / self._avgdl)
                score += idf * ((tf * (k1 + 1.0)) / denom) * query_weight
            if score > 0:
                scores.append((score, doc_index))

        ranked = sorted(scores, key=lambda item: (-item[0], self.corpus.chunks[item[1]].id))
        results: list[dict[str, Any]] = []
        for score, doc_index in ranked[:limit]:
            chunk = self.corpus.chunks[doc_index]
            metadata = dict(chunk.metadata)
            metadata.update(
                {
                    "retrieval_backend": self.retrieval_backend,
                    "corpus_profile": self.corpus_profile,
                    "corpus_id": self.corpus.corpus_id,
                    "corpus_version": self.corpus.version,
                    "score_type": self.score_type,
                }
            )
            results.append(
                {
                    "id": chunk.id,
                    "text": chunk.text,
                    "metadata": metadata,
                    "score": float(score),
                    "score_type": self.score_type,
                }
            )
        return results
