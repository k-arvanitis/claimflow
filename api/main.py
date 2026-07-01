import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile

from claimflow.graph import build_graph
from claimflow.tracing import get_callback

app = FastAPI(title="ClaimFlow", version="0.1.0")
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/claims")
async def process_claims(files: list[UploadFile]):
    with tempfile.TemporaryDirectory() as tmp:
        pkg_dir = Path(tmp) / "package"
        pkg_dir.mkdir()
        for f in files:
            dest = pkg_dir / f.filename
            with open(dest, "wb") as out:
                shutil.copyfileobj(f.file, out)

        result = _get_graph().invoke(
            {"package_dir": str(pkg_dir), "domain": None},
            config={"callbacks": get_callback()},
        )

    return {
        "decision": result.get("decision"),
        "domain": result.get("domain"),
        "extraction_overall_confidence": result.get("extraction_overall_confidence"),
        "validation_failures": result.get("validation_failures", []),
        "policy_answers": result.get("policy_answers", []),
        "review_reasons": result.get("review_reasons", []),
        "error": result.get("error"),
    }
