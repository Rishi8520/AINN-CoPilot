from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import config


class CorpusValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class QuickstartChunk:
    id: str
    text: str
    metadata: dict[str, Any]
    text_sha256: str
    source_sha256: str


@dataclass(frozen=True)
class QuickstartCorpus:
    corpus_id: str
    version: str
    chunks: list[QuickstartChunk]
    manifest: dict[str, Any]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_project_path(path: Path) -> Path:
    root = config.RAG_ROOT.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CorpusValidationError(
            "Quickstart corpus path must resolve inside CODE/RAG."
        ) from exc
    return resolved


def _reject_absolute_or_traversal(value: str, field: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise CorpusValidationError(f"{field} must be a source-relative path without traversal.")


def load_quickstart_corpus(
    corpus_path: Path | None = None,
    manifest_path: Path | None = None,
    *,
    strict_provenance: bool | None = None,
) -> QuickstartCorpus:
    strict = config.RAG_STRICT_PROVENANCE if strict_provenance is None else strict_provenance
    corpus_file = _safe_project_path(corpus_path or config.RAG_QUICKSTART_CORPUS_PATH)
    manifest_file = _safe_project_path(manifest_path or corpus_file.with_name("manifest.json"))

    if not corpus_file.exists():
        raise CorpusValidationError(f"Quickstart corpus is missing: {corpus_file.name}")
    if not manifest_file.exists():
        raise CorpusValidationError(f"Quickstart manifest is missing: {manifest_file.name}")

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusValidationError(f"Quickstart manifest is malformed: {exc}") from exc

    corpus_id = str(manifest.get("corpus_id") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not corpus_id or not version:
        raise CorpusValidationError("Quickstart manifest must include corpus_id and version.")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CorpusValidationError("Quickstart manifest must include at least one source.")

    source_hashes: dict[str, str] = {}
    source_sizes: dict[str, int] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise CorpusValidationError("Quickstart manifest source entries must be objects.")
        rel_source = str(source.get("source") or "")
        _reject_absolute_or_traversal(rel_source, "manifest source")
        source_path = config.RAG_ROOT / rel_source
        if not source_path.exists():
            raise CorpusValidationError(f"Quickstart source is missing: {rel_source}")
        expected_hash = str(source.get("sha256") or "")
        expected_size = int(source.get("size_bytes") or -1)
        if strict:
            actual_hash = _sha256_file(source_path)
            actual_size = source_path.stat().st_size
            if actual_hash != expected_hash:
                raise CorpusValidationError(f"Quickstart source hash changed: {rel_source}")
            if actual_size != expected_size:
                raise CorpusValidationError(f"Quickstart source size changed: {rel_source}")
        source_hashes[rel_source] = expected_hash
        source_sizes[rel_source] = expected_size

    chunks: list[QuickstartChunk] = []
    seen_ids: set[str] = set()
    try:
        lines = corpus_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CorpusValidationError(f"Quickstart corpus cannot be read: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorpusValidationError(f"Quickstart corpus line {line_number} is invalid JSON.") from exc
        if not isinstance(entry, dict):
            raise CorpusValidationError(f"Quickstart corpus line {line_number} must be an object.")

        chunk_id = str(entry.get("id") or "").strip()
        text = str(entry.get("text") or "")
        metadata = entry.get("metadata")
        text_sha = str(entry.get("text_sha256") or "")
        source_sha = str(entry.get("source_sha256") or "")
        if not chunk_id or not text.strip() or not isinstance(metadata, dict):
            raise CorpusValidationError(f"Quickstart corpus line {line_number} is missing required fields.")
        if chunk_id in seen_ids:
            raise CorpusValidationError(f"Duplicate quickstart chunk id: {chunk_id}")
        seen_ids.add(chunk_id)

        source = str(metadata.get("source") or "")
        _reject_absolute_or_traversal(source, "chunk source")
        if source not in source_hashes:
            raise CorpusValidationError(f"Chunk {chunk_id} references an unknown source: {source}")
        if strict and source_sha != source_hashes[source]:
            raise CorpusValidationError(f"Chunk {chunk_id} source hash does not match manifest.")
        if strict and text_sha != _sha256_text(text):
            raise CorpusValidationError(f"Chunk {chunk_id} text hash does not match.")

        chunks.append(
            QuickstartChunk(
                id=chunk_id,
                text=text,
                metadata=metadata,
                text_sha256=text_sha,
                source_sha256=source_sha,
            )
        )

    if not chunks:
        raise CorpusValidationError("Quickstart corpus contains no chunks.")

    manifest_count = manifest.get("chunk_count")
    if manifest_count is not None and int(manifest_count) != len(chunks):
        raise CorpusValidationError("Quickstart manifest chunk_count does not match corpus.")

    return QuickstartCorpus(
        corpus_id=corpus_id,
        version=version,
        chunks=chunks,
        manifest=manifest,
    )
