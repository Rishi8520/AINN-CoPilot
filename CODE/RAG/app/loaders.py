import json
import re
from pathlib import Path
from pypdf import PdfReader
from app.chunking import Chunk, chunk_text

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def load_pdf(path: Path) -> list[Chunk]:
    reader = PdfReader(str(path))
    chunks: list[Chunk] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for chunk_index, text_chunk in enumerate(chunk_text(text), start=1):
            chunks.append(
                Chunk(
                    text=text_chunk,
                    metadata={
                        "source": str(path),
                        "title": path.stem,
                        "section": f"page {page_index}",
                        "chunk": chunk_index,
                        "kind": "pdf",
                        "source_type": "spec",
                        "page": page_index,
                    },
                )
            )
    return chunks


def load_json_runbook(path: Path) -> list[Chunk]:
    data = json.loads(path.read_text(encoding="utf-8"))
    text = data.get("text", "")
    title = data.get("title", path.stem)
    source = data.get("source", str(path))
    section = data.get("section", "runbook")

    return [
        Chunk(
            text=text_chunk,
            metadata={
                "source": source,
                "title": title,
                "section": section,
                "chunk": chunk_index,
                "kind": "runbook",
            },
        )
        for chunk_index, text_chunk in enumerate(chunk_text(text), start=1)
    ]


def _markdown_title(path: Path, text: str) -> str:
    for line in text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match and len(match.group(1)) == 1:
            return match.group(2).strip()
    return path.stem


def _markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = "scenario_mapping"
    current_lines: list[str] = []

    for line in text.splitlines():
        match = HEADING_RE.match(line.strip())
        if match:
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = match.group(2).strip() or "scenario_mapping"
            current_lines = [line]
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    return [(heading, body) for heading, body in sections if body]


def load_scenario_text(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    title = _markdown_title(path, text) if path.suffix.lower() == ".md" else path.stem
    sections = _markdown_sections(text) if path.suffix.lower() == ".md" else [("scenario_mapping", text)]
    chunks: list[Chunk] = []

    for section, section_text in sections:
        content = f"{title}\n\nSection: {section}\n\n{section_text}"
        for chunk_index, text_chunk in enumerate(chunk_text(content), start=1):
            chunks.append(
                Chunk(
                    text=text_chunk,
                    metadata={
                        "source": str(path),
                        "title": title,
                        "section": section,
                        "chunk": chunk_index,
                        "kind": "scenario",
                        "source_type": "scenario",
                    },
                )
            )

    return chunks


def load_knowledge_base(root: str) -> list[Chunk]:
    base = Path(root)
    chunks: list[Chunk] = []

    for path in sorted(base.rglob("*.pdf")):
        chunks.extend(load_pdf(path))

    for path in sorted(base.rglob("*.json")):
        chunks.extend(load_json_runbook(path))

    scenarios_dir = base / "scenarios"
    if scenarios_dir.exists():
        for path in sorted(scenarios_dir.glob("*.md")):
            chunks.extend(load_scenario_text(path))
        for path in sorted(scenarios_dir.glob("*.txt")):
            chunks.extend(load_scenario_text(path))

    return chunks
