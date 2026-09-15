"""Command-line interface for thebundl."""

from __future__ import annotations

import argparse
from typing import Sequence

from .config import configuration_status, get_settings
from .pipeline import weekly_report, write_run_artifact


def _limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("limit must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m thebundl")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-config", help="check settings without revealing values")
    discover = commands.add_parser("discover", help="discover sources (not implemented)")
    discover.add_argument("--dry-run", action="store_true", required=True)
    discover.add_argument("--limit", type=_limit, required=True, help="maximum source pages processed")
    run = commands.add_parser("run", help="discover when due, then collect (not implemented)")
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
        print(f"Report written to {path}; distinct new deals: 0 (target: 10/week).")
        return 0
    publish = bool(getattr(args, "publish", False))
    if publish and not configuration_status(settings, publish=True)["publish_ready"]:
        print("Publish config needs SUPABASE_URL and SUPABASE_KEY. No write occurred.")
        return 2
    path = write_run_artifact(settings, args.command, limit=args.limit, publish=publish)
    print(f"{args.command} is not implemented. No Supabase writes occurred. Details: {path}")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
