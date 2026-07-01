from pathlib import Path

_CSV_PATH = Path(__file__).parent.parent.parent.parent / "data" / "lookups" / "cpt.csv"
_codes: set[str] | None = None


def _reset() -> None:
    global _codes
    _codes = None


def _load() -> set[str]:
    global _codes
    if _codes is not None:
        return _codes
    if not _CSV_PATH.exists():
        raise FileNotFoundError(f"CPT lookup not found at {_CSV_PATH}. Run scripts/download_lookups.py")
    _codes = set()
    with open(_CSV_PATH) as f:
        next(f)  # skip header
        for line in f:
            _codes.add(line.split(",")[0].strip())
    return _codes


def is_valid_cpt(code: str) -> bool:
    return code.strip() in _load()
