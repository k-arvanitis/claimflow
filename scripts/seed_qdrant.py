"""Index PDF policy documents into Qdrant.

Usage: uv run python scripts/seed_qdrant.py --policies data/policies/
Requires: Qdrant running (docker compose up -d qdrant)
"""
import argparse
from pathlib import Path

import fitz
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from claimflow.config import settings

CHUNK_SIZE = 400  # characters


def _extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    return "\n".join(page.get_text() for page in doc)


def _chunk(text: str, source: str) -> list[dict]:
    words = text.split()
    chunks = []
    buf = []
    for w in words:
        buf.append(w)
        if len(" ".join(buf)) >= CHUNK_SIZE:
            chunks.append({"text": " ".join(buf), "source": source})
            buf = buf[-20:]  # overlap
    if buf:
        chunks.append({"text": " ".join(buf), "source": source})
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policies", type=Path, default=Path("data/policies"))
    args = parser.parse_args()

    client = QdrantClient(url=settings.qdrant_url)

    # ponytail: recreate_collection resets the index; fine for a seed script
    client.recreate_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )

    pdfs = list(args.policies.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {args.policies}. Add policy documents and re-run.")
        return

    all_chunks = []
    for pdf in pdfs:
        text = _extract_text(pdf)
        all_chunks.extend(_chunk(text, pdf.name))

    client.add(
        collection_name=settings.qdrant_collection,
        documents=[c["text"] for c in all_chunks],
        metadata=[{"source": c["source"]} for c in all_chunks],
    )
    print(f"Indexed {len(all_chunks)} chunks from {len(pdfs)} policy PDFs.")


if __name__ == "__main__":
    main()
