from __future__ import annotations

from pathlib import Path
import argparse

from . import __version__
from .fixer import run_fix
from .indexer import scan_library


def parse_items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="music-metadata-tool")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="build or incrementally refresh metadata index")
    scan.add_argument("music_dir", type=Path)
    scan.add_argument("--index", type=Path, default=Path("music_metadata_index.csv"))
    scan.add_argument("--report-dir", type=Path, default=Path("report"))
    scan.add_argument("--full", action="store_true", help="ignore existing index and read all tags")
    scan.add_argument("--progress-every", type=int, default=100)

    fix = subparsers.add_parser("fix", help="apply conservative metadata fixes from index")
    fix.add_argument("--index", type=Path, required=True)
    fix.add_argument("--report", type=Path, default=Path("fix_report.csv"))
    fix.add_argument("--items", type=parse_items, default=["genre", "albumartist"])
    fix.add_argument("--fallback-genre", default="")
    fix.add_argument("--write", action="store_true")
    fix.add_argument("--progress-every", type=int, default=100)
    fix.add_argument("--flush-every", type=int, default=1000)
    fix.add_argument("--no-resume", action="store_true", help="ignore existing fix report and start over")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "scan":
        if not args.music_dir.exists():
            raise SystemExit(f"music directory does not exist: {args.music_dir}")
        if not args.music_dir.is_dir():
            raise SystemExit(f"music path is not a directory: {args.music_dir}")
        scan_library(args.music_dir, args.index, args.report_dir, args.full, args.progress_every)
    elif args.command == "fix":
        if not args.index.exists():
            raise SystemExit(f"index does not exist: {args.index}")
        run_fix(
            args.index,
            args.report,
            args.items,
            args.fallback_genre,
            args.write,
            args.progress_every,
            args.flush_every,
            not args.no_resume,
        )
    else:
        parser.print_help()
