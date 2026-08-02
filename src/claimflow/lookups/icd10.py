from pathlib import Path

_CSV_PATH = (
    Path(__file__).parent.parent.parent.parent / "data" / "lookups" / "icd10.csv"
)
_codes: set[str] | None = None


def _reset() -> None:
    global _codes
    _codes = None


def _load() -> set[str]:
    global _codes
    if _codes is not None:
        return _codes
    if not _CSV_PATH.exists():
        raise FileNotFoundError(
            f"ICD-10 lookup not found at {_CSV_PATH}. Run scripts/download_lookups.py"
        )
    _codes = set()
    with open(_CSV_PATH) as f:
        next(f)  # skip header
        for line in f:
            code = line.split(",")[0].strip().upper()
            _codes.add(code)
            stripped = code.replace(".", "")
            _codes.add(stripped)  # no-dot form (e.g. J069)
            if len(stripped) > 3:
                _codes.add(
                    stripped[:3] + "." + stripped[3:]
                )  # dotted form (e.g. J06.9)
    return _codes


def is_valid_icd10(code: str) -> bool:
    normalized = code.strip().upper()
    return normalized in _load()
