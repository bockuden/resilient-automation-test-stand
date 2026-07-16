import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="automation-test-stand",
        description="Run the deterministic browser automation target.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()

