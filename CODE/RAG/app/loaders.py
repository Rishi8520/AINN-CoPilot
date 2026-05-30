import json
from pathlib import Path
from pypdf import PdfReader
from app.chunking import Chunk, chunk_text


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


def load_knowledge_base(root: str) -> list[Chunk]:
    base = Path(root)
    chunks: list[Chunk] = []

    for path in sorted(base.rglob("*.pdf")):
        chunks.extend(load_pdf(path))

    for path in sorted(base.rglob("*.json")):
        chunks.extend(load_json_runbook(path))

    return chunks
