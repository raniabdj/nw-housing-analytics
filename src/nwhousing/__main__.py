"""Command line entry point.

    python -m nwhousing run                 # auto mode against the live APIs
    python -m nwhousing run --mode backfill # full reload
    python -m nwhousing run --demo          # offline run on synthetic data
    python -m nwhousing report              # rebuild the HTML report only
"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nwhousing", description="North West housing & interest rates pipeline")
    parser.add_argument("--config", help="path to pipeline.yaml")
    parser.add_argument("--data-dir", help="override the data directory")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run the full pipeline")
    run_p.add_argument("--mode", choices=["auto", "backfill", "incremental", "refresh"], default="auto")
    run_p.add_argument("--demo", action="store_true", help="use synthetic offline data")
    run_p.add_argument("--no-report", action="store_true")

    rep_p = sub.add_parser("report", help="rebuild the HTML report from the warehouse")
    rep_p.add_argument("--demo", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config, args.data_dir, demo=getattr(args, "demo", False))

    if args.command == "run":
        from .pipeline import run
        result = run(cfg, mode=args.mode, with_report=not args.no_report)
        return 0 if result.get("status") == "success" else 1
    if args.command == "report":
        from .report import build
        build(cfg)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
