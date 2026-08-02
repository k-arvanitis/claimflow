"""Index PDF policy documents into Qdrant.

Usage: uv run python scripts/seed_qdrant.py --policies data/policies/
Requires: Qdrant running (docker compose up -d qdrant)

The actual chunking/indexing logic lives in claimflow.policy_index — shared with
the Settings > Policies API, so a policy added through either path is indexed
identically.
"""

import argparse
from pathlib import Path

from claimflow.policy_index import reindex


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policies", type=Path, default=Path("data/policies"))
    args = parser.parse_args()

    if not any(args.policies.glob("*.pdf")):
        print(f"No PDFs in {args.policies}. Add policy documents and re-run.")
        return

    count = reindex(args.policies)
    print(f"Indexed {count} chunks from {len(list(args.policies.glob('*.pdf')))} policy PDFs.")


if __name__ == "__main__":
    main()
