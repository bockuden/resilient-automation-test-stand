"""Export or verify the committed FastAPI OpenAPI contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = REPOSITORY_ROOT / "docs" / "api" / "openapi.json"
sys.path.insert(0, str(REPOSITORY_ROOT))

from resilient_automation_test_stand.main import app  # noqa: E402


def rendered_schema() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export or verify docs/api/openapi.json.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when the committed snapshot is stale.",
    )
    args = parser.parse_args()

    expected = rendered_schema()
    if args.check:
        if not SNAPSHOT_PATH.exists() or SNAPSHOT_PATH.read_text(encoding="utf-8") != expected:
            print(
                "OpenAPI snapshot is stale; run: python scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"OpenAPI snapshot is current: {SNAPSHOT_PATH}")
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Wrote {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
