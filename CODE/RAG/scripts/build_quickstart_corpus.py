#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RAG_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = RAG_ROOT / "quickstart"
CORPUS_PATH = OUTPUT_DIR / "corpus.jsonl"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"


@dataclass(frozen=True)
class SourceSpec:
    source: str
    kind: str
    source_type: str
    title: str
    section: str
    extraction_method: str
    page: int | None = None
    text_key: str | None = None
    heading: str | None = None
    include_terms: tuple[str, ...] = ()
    window_before: int = 260
    window_after: int = 760


SOURCES = [
    SourceSpec(
        source="knowledge_base/runbooks/live_experiment_guidance.json", kind="runbook", source_type="runbook",
        title="TelcoMind Traffic Burst Interpretation", section="traffic_burst",
        extraction_method="json.text", text_key="traffic",
    ),
    SourceSpec(
        source="knowledge_base/runbooks/live_experiment_guidance.json", kind="runbook", source_type="runbook",
        title="TelcoMind Resource Comparison Interpretation", section="resource_comparison",
        extraction_method="json.text", text_key="resources",
    ),
    SourceSpec(
        source="knowledge_base/runbooks/live_experiment_guidance.json", kind="runbook", source_type="runbook",
        title="TelcoMind Mobility Handover Interpretation", section="mobility_handover",
        extraction_method="json.text", text_key="mobility",
    ),
    SourceSpec(
        source="knowledge_base/runbooks/baseline_measurement_runbook.json",
        kind="runbook", source_type="runbook",
        title="TelcoMind Baseline Measurement Interpretation",
        section="Stationary baseline throughput and delay",
        extraction_method="json.text", text_key="text",
    ),
    SourceSpec(
        source="knowledge_base/runbooks/handover_failure_runbook.json",
        kind="runbook",
        source_type="runbook",
        title="Handover Failure Runbook",
        section="handover_failure",
        extraction_method="json.text",
        text_key="text",
    ),
    SourceSpec(
        source="knowledge_base/runbooks/interference_runbook.json",
        kind="runbook",
        source_type="runbook",
        title="Interference and Hotspot Runbook",
        section="interference_hotspot",
        extraction_method="json.text",
        text_key="text",
    ),
    SourceSpec(
        source="knowledge_base/runbooks/energy_optimization_runbook.json",
        kind="runbook",
        source_type="runbook",
        title="Energy Optimization Runbook",
        section="energy_optimization",
        extraction_method="json.text",
        text_key="text",
    ),
    SourceSpec(
        source="knowledge_base/scenarios/simulation_scenario_mapping.md",
        kind="scenario",
        source_type="scenario",
        title="Simulation Scenario Mapping for RAG",
        section="handover_failure",
        extraction_method="markdown.heading",
        heading="handover_failure",
    ),
    SourceSpec(
        source="knowledge_base/scenarios/simulation_scenario_mapping.md",
        kind="scenario",
        source_type="scenario",
        title="Simulation Scenario Mapping for RAG",
        section="energy_optimization",
        extraction_method="markdown.heading",
        heading="energy_optimization",
    ),
    SourceSpec(
        source="knowledge_base/scenarios/simulation_scenario_mapping.md",
        kind="scenario",
        source_type="scenario",
        title="Simulation Scenario Mapping for RAG",
        section="interference_hotspot",
        extraction_method="markdown.heading",
        heading="interference_hotspot",
    ),
    SourceSpec(
        source="knowledge_base/specs/3gpp_ts_38_300_nr_ng_ran_overall_description.pdf",
        kind="pdf",
        source_type="spec",
        title="3GPP TS 38.300 NR and NG-RAN Overall Description",
        section="Handover preparation",
        extraction_method="pypdf.page.term_window",
        page=100,
        include_terms=("Handover Request", "target gNB", "source gNB"),
    ),
    SourceSpec(
        source="knowledge_base/specs/3gpp_ts_28_552_5g_performance_measurements.pdf",
        kind="pdf",
        source_type="spec",
        title="3GPP TS 28.552 5G Performance Measurements",
        section="Handover performance measurements",
        extraction_method="pypdf.page.term_window",
        page=74,
        include_terms=("failed legacy handover", "performance assurance"),
    ),
    SourceSpec(
        source="knowledge_base/specs/3gpp_ts_28_541_5g_network_resource_model.pdf",
        kind="pdf",
        source_type="spec",
        title="3GPP TS 28.541 5G Network Resource Model",
        section="NRM scope",
        extraction_method="pypdf.page.term_window",
        page=43,
        include_terms=("Network Resource Model", "NR", "NG-RAN"),
    ),
    SourceSpec(
        source="knowledge_base/specs/etsi_ts_103_982_oran_architecture_description.pdf",
        kind="pdf",
        source_type="spec",
        title="ETSI TS 103 982 O-RAN Architecture Description",
        section="O-RAN architecture security and interfaces",
        extraction_method="pypdf.page.term_window",
        page=24,
        include_terms=("O-RAN ALLIANCE", "secure", "interoperable RAN"),
    ),
    SourceSpec(
        source="knowledge_base/specs/etsi_ts_103_982_oran_architecture_description.pdf",
        kind="pdf", source_type="spec",
        title="ETSI TS 103 982 O-RAN Architecture Description",
        section="O-RAN overview and objectives",
        extraction_method="pypdf.page.term_window", page=11,
        include_terms=("O-RAN activities",), window_before=0,
    ),
    SourceSpec(
        source="knowledge_base/specs/etsi_ts_103_982_oran_architecture_description.pdf",
        kind="pdf", source_type="spec",
        title="ETSI TS 103 982 O-RAN Architecture Description",
        section="O-RAN overview abbreviation",
        extraction_method="pypdf.page.term_window", page=10,
        include_terms=("O-RAN Open RAN",), window_before=0, window_after=14,
    ),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def clean_text(text: str) -> str:
    return " ".join(text.split())


def chunk_id(spec: SourceSpec, index: int) -> str:
    stem = Path(spec.source).stem.lower().replace("_", "-")
    section = re.sub(r"[^a-z0-9]+", "-", spec.section.lower()).strip("-")
    return f"qs-{stem}-{section}-{index:02d}"


def load_json_text(path: Path, key: str) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return clean_text(str(data[key]))


def load_markdown_heading(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"Heading not found: {heading}")
    start = match.start()
    next_match = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return clean_text(text[start:end])


def load_pdf_window(path: Path, page: int, terms: tuple[str, ...], before: int = 260, after: int = 760) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = clean_text(reader.pages[page - 1].extract_text() or "")
    lowered = text.lower()
    positions = [lowered.find(term.lower()) for term in terms if lowered.find(term.lower()) >= 0]
    if not positions:
        raise RuntimeError(f"No include terms found in {path.name} page {page}")
    center = min(positions)
    start = max(0, center - before)
    end = min(len(text), center + after)
    return clean_text(text[start:end])


def build_entries() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    source_records: dict[str, dict[str, Any]] = {}
    per_source_counter: dict[str, int] = {}

    for spec in SOURCES:
        source_path = RAG_ROOT / spec.source
        if not source_path.exists():
            raise RuntimeError(f"Missing source: {spec.source}")
        source_sha = sha256_file(source_path)
        source_records.setdefault(
            spec.source,
            {
                "source": spec.source,
                "sha256": source_sha,
                "size_bytes": source_path.stat().st_size,
                "extraction_methods": [],
            },
        )
        if spec.extraction_method not in source_records[spec.source]["extraction_methods"]:
            source_records[spec.source]["extraction_methods"].append(spec.extraction_method)

        if spec.extraction_method == "json.text":
            text = load_json_text(source_path, spec.text_key or "text")
        elif spec.extraction_method == "markdown.heading":
            text = load_markdown_heading(source_path, spec.heading or spec.section)
        elif spec.extraction_method == "pypdf.page.term_window":
            if spec.page is None:
                raise RuntimeError("PDF source requires page")
            text = load_pdf_window(source_path, spec.page, spec.include_terms, spec.window_before, spec.window_after)
        else:
            raise RuntimeError(f"Unknown extraction method: {spec.extraction_method}")

        per_source_counter[spec.source] = per_source_counter.get(spec.source, 0) + 1
        index = per_source_counter[spec.source]
        metadata = {
            "source": spec.source,
            "title": spec.title,
            "section": spec.section,
            "chunk": index,
            "kind": spec.kind,
            "source_type": spec.source_type,
            "extraction_method": spec.extraction_method,
        }
        if spec.page is not None:
            metadata["page"] = spec.page
        entries.append(
            {
                "id": chunk_id(spec, index),
                "text": text,
                "metadata": metadata,
                "source_sha256": source_sha,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )

    return sorted(entries, key=lambda item: item["id"]), sorted(source_records.values(), key=lambda item: item["source"])


def write_outputs() -> None:
    entries, source_records = build_entries()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n" for entry in entries)
    CORPUS_PATH.write_text(body, encoding="utf-8", newline="\n")
    manifest = {
        "corpus_id": "telcomind-rag-quickstart",
        "version": "2026-10-13.live-scenarios",
        "description": "Small offline lexical RAG corpus derived from repository knowledge_base sources.",
        "chunk_count": len(entries),
        "corpus_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "strict_provenance_supported": True,
        "generated_by": "scripts/build_quickstart_corpus.py",
        "sources": source_records,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_outputs() -> None:
    entries, source_records = build_entries()
    expected_body = "".join(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n" for entry in entries)
    expected_manifest = {
        "corpus_id": "telcomind-rag-quickstart",
        "version": "2026-10-13.live-scenarios",
        "description": "Small offline lexical RAG corpus derived from repository knowledge_base sources.",
        "chunk_count": len(entries),
        "corpus_sha256": hashlib.sha256(expected_body.encode("utf-8")).hexdigest(),
        "strict_provenance_supported": True,
        "generated_by": "scripts/build_quickstart_corpus.py",
        "sources": source_records,
    }
    if CORPUS_PATH.read_text(encoding="utf-8") != expected_body:
        raise SystemExit("Quickstart corpus differs from deterministic build output.")
    if json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) != expected_manifest:
        raise SystemExit("Quickstart manifest differs from deterministic build output.")
    print(f"verified {len(entries)} chunks; corpus={CORPUS_PATH.stat().st_size} bytes")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="verify existing generated outputs without rewriting")
    args = parser.parse_args()
    if args.verify:
        verify_outputs()
    else:
        write_outputs()
        verify_outputs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
