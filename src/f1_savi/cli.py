from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import RacePackError, build_race_pack, verify_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="f1-savi", description="Build and validate an F1 SAVI League race pack.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build a race pack from individual and cumulative CSV files.")
    build.add_argument("--individual", required=True, type=Path)
    build.add_argument("--cumulative", required=True, type=Path)
    build.add_argument("--output", required=True, type=Path)
    build.add_argument("--expected-competitors", type=int, default=46)
    build.add_argument("--graph-url", default="https://creative-innovation-labs-bmc.github.io/f1-savi-league/")
    build.add_argument("--flourish-races-id", type=int, default=23536150)
    build.add_argument("--flourish-leaderboard-id", type=int, default=23537908)

    verify = subparsers.add_parser("verify", help="Verify a generated race pack against its SHA-256 manifest.")
    verify.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            payload = build_race_pack(
                args.individual,
                args.cumulative,
                args.output,
                expected_competitors=args.expected_competitors,
                graph_url=args.graph_url,
                flourish_races_id=args.flourish_races_id,
                flourish_leaderboard_id=args.flourish_leaderboard_id,
            )
            metadata = payload["metadata"]
            print(json.dumps({"status": "pass", "metadata": metadata, "output": str(args.output)}, ensure_ascii=False))
            return 0
        manifest = verify_manifest(args.output)
        print(json.dumps({"status": "pass", "manifest": manifest}, ensure_ascii=False))
        return 0
    except RacePackError as error:
        print(json.dumps({"status": "fail", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
