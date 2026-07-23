"""Export declared runtime and development dependencies for pip-audit."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = [*project["dependencies"], *project["optional-dependencies"]["dev"]]
    args.output.write_text("\n".join(requirements) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
