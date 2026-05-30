from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    metadata: dict


def chunk_text(text: str, chunk_size: int = 1400, overlap: int = 220) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []

    chunks = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = max(0, end - overlap)
    return chunks
