from __future__ import annotations

import argparse
import sys

from laser_platform.server import run_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Laser Measurement Platform Python backend")
    parser.add_argument("--server", action="store_true", help="run the local HTTP/SSE backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)

    if not args.server:
        parser.error("Use `npm run dev` to run the app, or pass --server for backend only")

    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
