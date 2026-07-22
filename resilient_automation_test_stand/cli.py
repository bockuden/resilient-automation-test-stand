import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from resilient_automation_test_stand.main import app, configure_scenario_defaults
from resilient_automation_test_stand.presets import (
    PresetConfigError,
    PresetDocument,
    ScenarioDefaults,
    load_preset_document,
    preset_url,
)


def _load_document(parser: argparse.ArgumentParser, path: Path | None) -> PresetDocument:
    if path is None:
        parser.error("--config is required for preset operations")
    try:
        return load_preset_document(path)
    except PresetConfigError as error:
        parser.error(str(error))


def _select_preset(
    parser: argparse.ArgumentParser,
    document: PresetDocument,
    name: str,
) -> ScenarioDefaults:
    try:
        return document.presets[name]
    except KeyError:
        available = ", ".join(sorted(document.presets))
        parser.error(f"unknown preset '{name}'; available presets: {available}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="automation-test-stand",
        description="Run the deterministic browser automation target.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--config", type=Path, help="TOML file containing presets")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--preset", help="Use a preset as the server defaults")
    actions.add_argument(
        "--list-presets",
        action="store_true",
        help="List config presets and exit",
    )
    actions.add_argument(
        "--print-url",
        metavar="PRESET",
        help="Print a reproducible catalog URL for a preset and exit",
    )
    args = parser.parse_args(argv)

    document = _load_document(parser, args.config) if args.config else None

    if args.list_presets:
        document = document or _load_document(parser, args.config)
        for name in sorted(document.presets):
            print(name)
        return

    if args.print_url:
        document = document or _load_document(parser, args.config)
        preset = _select_preset(parser, document, args.print_url)
        print(
            preset_url(
                args.print_url,
                preset,
                f"http://localhost:{args.port}/catalog",
            )
        )
        return

    defaults = ScenarioDefaults()
    if args.preset:
        document = document or _load_document(parser, args.config)
        defaults = _select_preset(parser, document, args.preset)
    configure_scenario_defaults(defaults)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
