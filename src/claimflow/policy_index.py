"""Manage the policy PDF corpus and its Qdrant index.

Shared by `scripts/seed_qdrant.py` (CLI) and the Settings > Policies API — both
need identical chunking and domain/authority resolution so a policy indexed one
way behaves the same as one indexed the other way.

Domain/authority used to be inferred purely from filename prefixes. New files
added through the API carry that metadata explicitly (`_meta.json`, keyed by
filename) since a user picks it from a form, not a filename convention. Files
that predate the API (the original seed set) have no entry there, so
`_domain_from_filename`/`_authority_from_filename` remain the fallback.
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz

from claimflow.config import settings

CHUNK_SIZE = 400  # characters
POLICIES_DIR = Path("data/policies")
META_PATH = POLICIES_DIR / "_meta.json"
DOMAINS = ("health", "property", "loan")
AUTHORITIES = ("official_cms", "synthetic")


def _domain_from_filename(name: str) -> str:
    name = name.lower()
    if name.startswith(("health_", "cms_", "medicare_")):
        return "health"
    if name.startswith("property_"):
        return "property"
    if name.startswith(("loan_", "sba_")):
        return "loan"
    return "unknown"


def _authority_from_filename(name: str) -> str:
    return "official_cms" if name.lower().startswith("cms_") else "synthetic"


def _load_meta() -> dict[str, dict]:
    if not META_PATH.exists():
        return {}
    return json.loads(META_PATH.read_text())


def _save_meta(meta: dict[str, dict]) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2))


def _resolve(name: str, meta: dict[str, dict]) -> tuple[str, str]:
    entry = meta.get(name)
    if entry:
        return entry["domain"], entry["authority"]
    return _domain_from_filename(name), _authority_from_filename(name)


def list_policy_files(policies_dir: Path = POLICIES_DIR) -> list[dict]:
    meta = _load_meta()
    files = []
    for pdf in sorted(policies_dir.glob("*.pdf")):
        domain, authority = _resolve(pdf.name, meta)
        files.append(
            {
                "filename": pdf.name,
                "domain": domain,
                "authority": authority,
                "size_bytes": pdf.stat().st_size,
            }
        )
    return files


def save_policy_file(
    filename: str, contents: bytes, domain: str, authority: str
) -> None:
    """Write the uploaded PDF and record its domain/authority. Overwrites an
    existing file of the same name (an "update")."""
    safe_name = Path(filename).name
    POLICIES_DIR.mkdir(parents=True, exist_ok=True)
    (POLICIES_DIR / safe_name).write_bytes(contents)
    meta = _load_meta()
    meta[safe_name] = {"domain": domain, "authority": authority}
    _save_meta(meta)


def policy_file_path(filename: str) -> Path | None:
    """Resolve a policy filename to its on-disk path, or None if it doesn't exist.
    `Path(...).name` strips any directory components, so a path-traversal attempt
    just resolves to a (likely nonexistent) filename inside POLICIES_DIR."""
    path = POLICIES_DIR / Path(filename).name
    return path if path.exists() else None


def delete_policy_file(filename: str) -> bool:
    safe_name = Path(filename).name
    path = POLICIES_DIR / safe_name
    if not path.exists():
        return False
    path.unlink()
    meta = _load_meta()
    meta.pop(safe_name, None)
    _save_meta(meta)
    return True


def _extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    return "\n".join(page.get_text() for page in doc)


def _chunk(text: str, source: str) -> list[dict]:
    words = text.split()
    chunks = []
    buf: list[str] = []
    for w in words:
        buf.append(w)
        if len(" ".join(buf)) >= CHUNK_SIZE:
            chunks.append({"text": " ".join(buf), "source": source})
            buf = buf[-20:]  # overlap
    if buf:
        chunks.append({"text": " ".join(buf), "source": source})
    return chunks


def reindex(policies_dir: Path = POLICIES_DIR) -> int:
    """Rebuild the Qdrant collection from every PDF in `policies_dir`. Returns
    the number of chunks indexed. Full delete-and-rebuild rather than an
    incremental update — simple and fast enough at this corpus size (a handful
    of PDFs); revisit if the policy corpus grows into the hundreds of files."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=settings.qdrant_url)

    collections = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection in collections:
        client.delete_collection(settings.qdrant_collection)

    pdfs = list(policies_dir.glob("*.pdf"))
    if not pdfs:
        return 0

    meta = _load_meta()
    all_chunks = []
    for pdf in pdfs:
        text = _extract_text(pdf)
        domain, authority = _resolve(pdf.name, meta)
        all_chunks.extend(
            {**chunk, "domain": domain, "authority": authority}
            for chunk in _chunk(text, pdf.name)
        )

    if not all_chunks:
        return 0

    # No manual create_collection — client.add()/client.query() (FastEmbed's managed
    # API, also used in retrieve.py) auto-creates the collection with the named-vector
    # schema they expect. A manually created unnamed-vector collection is incompatible.
    client.add(
        collection_name=settings.qdrant_collection,
        documents=[c["text"] for c in all_chunks],
        metadata=[
            {"source": c["source"], "domain": c["domain"], "authority": c["authority"]}
            for c in all_chunks
        ],
    )
    return len(all_chunks)
