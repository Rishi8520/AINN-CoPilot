#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from app.lexical_retriever import LexicalBM25Retriever  # noqa: E402


QUERY_PATH = RAG_ROOT / "quickstart" / "demo_queries.json"


def main() -> int:
    retriever = LexicalBM25Retriever()
    queries = json.loads(QUERY_PATH.read_text(encoding="utf-8"))
    rows = []
    for entry in queries:
        start = time.perf_counter()
        results = retriever.search(entry["query"], top_k=5)
        latency_ms = (time.perf_counter() - start) * 1000
        returned_ids = [item["id"] for item in results]
        expected_ids = entry.get("expected_chunk_ids", [])
        expected_source_types = set(entry.get("expected_source_types", []))
        source_types = [item["metadata"].get("source_type") for item in results]
        evidence_hit = (
            any(chunk_id in returned_ids for chunk_id in expected_ids)
            if expected_ids
            else not results
        )
        if expected_source_types and not evidence_hit:
            evidence_hit = bool(expected_source_types.intersection(source_types))
        rows.append(
            {
                "query": entry["query"],
                "returned_chunk_ids": returned_ids,
                "source_types": source_types,
                "rank_positions": {
                    chunk_id: returned_ids.index(chunk_id) + 1
                    for chunk_id in expected_ids
                    if chunk_id in returned_ids
                },
                "expected_evidence_appeared": evidence_hit,
                "profile": "quickstart",
                "backend": retriever.retrieval_backend,
                "latency_ms": round(latency_ms, 3),
            }
        )
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
