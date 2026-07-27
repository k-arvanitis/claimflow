"""Index PDF policy documents into Qdrant.

Usage: uv run python scripts/seed_qdrant.py --policies data/policies/
Requires: Qdrant running (docker compose up -d qdrant)
"""

import argparse
from pathlib import Path

import fitz
from qdrant_client import QdrantClient

from claimflow.config import settings

CHUNK_SIZE = 400  # characters


def _policy_domain(pdf_path: Path) -> str:
    name = pdf_path.name.lower()
    if name.startswith(("health_", "cms_", "medicare_")):
        return "health"
    if name.startswith("property_"):
        return "property"
    if name.startswith(("loan_", "sba_")):
        return "loan"
    return "unknown"


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

    collections = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection in collections:
        client.delete_collection(settings.qdrant_collection)
    # No manual create_collection — client.add()/client.query() (FastEmbed's managed API,
    # also used in retrieve.py) auto-creates the collection with the named-vector schema
    # they expect. A manually created unnamed-vector collection is incompatible with them.

    pdfs = list(args.policies.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {args.policies}. Add policy documents and re-run.")
        return

    all_chunks = []
    for pdf in pdfs:
        text = _extract_text(pdf)
        domain = _policy_domain(pdf)
        all_chunks.extend(
            {
                **chunk,
                "domain": domain,
                "authority": (
                    "official_cms"
                    if pdf.name.lower().startswith("cms_")
                    else "synthetic"
                ),
            }
            for chunk in _chunk(text, pdf.name)
        )

    client.add(
        collection_name=settings.qdrant_collection,
        documents=[c["text"] for c in all_chunks],
        metadata=[
            {
                "source": c["source"],
                "domain": c["domain"],
                "authority": c["authority"],
            }
            for c in all_chunks
        ],
    )
    print(f"Indexed {len(all_chunks)} chunks from {len(pdfs)} policy PDFs.")


if __name__ == "__main__":
    main()
