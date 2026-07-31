# TelcoMind RAG Quickstart Corpus

This directory contains the default offline RAG quickstart corpus.

- `corpus.jsonl` is a small provenance-traceable chunk bundle.
- `manifest.json` records source files, source SHA-256 hashes, extraction methods, corpus hash, and chunk count.
- `demo_queries.json` contains grounded offline evaluator queries.

The corpus is generated from committed files under `CODE/RAG/knowledge_base` by:

```bash
python scripts/build_quickstart_corpus.py
```

Verify without rewriting:

```bash
python scripts/build_quickstart_corpus.py --verify
```

The quickstart backend uses lexical BM25-style ranking. Its scores are raw ranking scores, not confidence, probability, or semantic similarity. Full semantic BGE/Chroma/reranker retrieval remains available only with `RAG_PROFILE=full`.
