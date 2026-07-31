import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIM_FIXTURE = ROOT / "CODE" / "Simulation" / "fixtures" / "replay" / "phase_bootstrap_normal"
RAG_QUICKSTART = ROOT / "CODE" / "RAG" / "quickstart"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _versioned_candidates() -> list[Path]:
    names: list[str] = []
    for args in [
        ["ls-files", "-z"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    ]:
        result = subprocess.run(
            ["git", "-c", f"core.excludesfile={os.devnull}", "-c", "core.quotePath=false", *args],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            check=True,
        )
        names.extend(result.stdout.decode("utf-8", errors="surrogateescape").split("\0"))
    return [ROOT / name for name in names if name.strip()]


def test_simulation_fixture_manifest_and_checksums_match_recorded_bytes():
    manifest_path = SIM_FIXTURE / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["live_simulation"] is False
    assert manifest["created_from_existing_repository_artifact"] is True
    for entry in manifest["files"]:
        path = SIM_FIXTURE / entry["filename"]
        assert path.exists(), entry["filename"]
        assert path.stat().st_size == entry["size_bytes"]
        assert _sha256(path) == entry["sha256"]


def test_simulation_runtime_directories_contain_only_placeholders():
    for rel in [
        "CODE/Simulation/app/scenarios/results",
        "CODE/Simulation/app/scenarios/generated",
    ]:
        files = {path.name for path in (ROOT / rel).iterdir() if path.is_file()}
        assert files <= {"README.md", ".gitkeep"}


def test_rag_quickstart_manifest_corpus_and_sources_validate():
    manifest_path = RAG_QUICKSTART / "manifest.json"
    corpus_path = RAG_QUICKSTART / "corpus.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lines = [line for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert manifest["chunk_count"] == len(lines)
    assert manifest["corpus_sha256"] == _sha256(corpus_path)
    assert corpus_path.stat().st_size < 2 * 1024 * 1024

    source_hashes = {source["source"]: source["sha256"] for source in manifest["sources"]}
    for source in manifest["sources"]:
        rel_source = Path(source["source"])
        assert not rel_source.is_absolute()
        assert ".." not in rel_source.parts
        source_path = ROOT / "CODE" / "RAG" / rel_source
        assert source_path.exists()
        assert source_path.stat().st_size == source["size_bytes"]
        assert _sha256(source_path) == source["sha256"]

    for line in lines:
        entry = json.loads(line)
        metadata = entry["metadata"]
        rel_source = Path(metadata["source"])
        assert not rel_source.is_absolute()
        assert ".." not in rel_source.parts
        assert entry["source_sha256"] == source_hashes[metadata["source"]]
        assert hashlib.sha256(entry["text"].encode("utf-8")).hexdigest() == entry["text_sha256"]


def test_rag_quickstart_lexical_scores_are_not_labelled_confidence():
    text = (ROOT / "CODE" / "RAG").read_text(encoding="utf-8", errors="replace") if False else ""
    for path in [
        ROOT / "CODE" / "RAG" / "app" / "lexical_retriever.py",
        ROOT / "CODE" / "RAG" / "app" / "rag_service.py",
    ]:
        text += path.read_text(encoding="utf-8", errors="replace")

    assert "bm25_raw" in text
    assert '"score_type": "confidence"' not in text
    assert "calibrated confidence" not in text.lower()


def test_deployment_artifacts_exist_and_no_runtime_archives_are_tracked_candidates():
    required = [
        "docker-compose.yml",
        "deploy.sh",
        "deploy.ps1",
        "test.sh",
        "test.ps1",
        "scripts/run_test_matrix.py",
        "tests/test_matrix.json",
        "scripts/smoke_test.py",
    ]
    for rel in required:
        assert (ROOT / rel).exists(), rel

    forbidden_suffixes = {".zip", ".mp4", ".mov", ".avi"}
    for path in _versioned_candidates():
        assert path.suffix.lower() not in forbidden_suffixes
