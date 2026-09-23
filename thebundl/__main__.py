"""Command-line interface for thebundl."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from .config import configuration_status, get_settings
from .pipeline import weekly_report, execute_pipeline


def _limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("limit must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m thebundl")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-config", help="check settings without revealing values")
    discover = commands.add_parser("discover", help="discover sources and save local results")
    discover.add_argument("--dry-run", action="store_true", required=True)
    discover.add_argument("--limit", type=_limit, required=True, help="maximum source pages processed")
    run = commands.add_parser("run", help="execute the bounded deal pipeline")
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--publish", action="store_true")
    run.add_argument("--limit", type=_limit, help="maximum source pages processed")
    report = commands.add_parser("report", help="report actual distinct deal count")
    report.add_argument("--days", type=_limit, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if args.command == "check-config":
        for key, present in configuration_status(settings).items():
            print(f"{key}: {'set' if present else 'missing'}")
        print("Campuses: Baruch College main campus; Columbia University Morningside campus (2.0-mile radius each)")
        return 0
    if args.command == "report":
        path = weekly_report(settings, args.days)
        count = json.loads(path.read_text())["distinct_new_deals"]
        print(f"Report written to {path}; distinct new deals: {count} (target: 10/week).")
        return 0
    publish = bool(getattr(args, "publish", False))
    path, result = execute_pipeline(settings, args.command, limit=args.limit, publish=publish)
    print(f"{args.command} {result['status']}. " + "; ".join(
        f"{key.replace('_', ' ')}: {value}" for key, value in result['counts'].items()))
    for error in result['errors']:
        print(f"Error in {error['stage']}: {error['message']}")
    print(f"Details: {path}")
    return 1 if result['status'] == 'failed' else 0



if __name__ == "__main__":
    raise SystemExit(main())
