#!/usr/bin/env python3
"""Retention cleanup for Frontier Tracker intermediate data.

Deletes files under outputs/data older than --days (default 30) so the directory
does not accumulate indefinitely. Only the derived per-run JSON artifacts
(frontier_*.json / smoke_*.json) are targeted; nothing under state/, references/,
or the vault is ever touched.

Usage:
    # Dry run first — lists what would be deleted, deletes nothing:
    python scripts/cleanup_outputs.py --dry-run

    # Actually delete files older than 30 days (default):
    python scripts/cleanup_outputs.py

    # Custom window, e.g. keep only the last 14 days:
    python scripts/cleanup_outputs.py --days 14
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import _bootstrap  # noqa: F401  — keeps behavior consistent across scripts

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "outputs" / "data"
DAY_SECONDS = 86_400


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete old per-run JSON artifacts from outputs/data.")
    parser.add_argument("--days", type=int, default=30, help="Delete files older than N days (default: 30).")
    parser.add_argument("--dry-run", action="store_true", help="List what would be deleted without deleting.")
    parser.add_argument("--dir", type=Path, default=DATA_DIR, help="Target directory (default: outputs/data).")
    args = parser.parse_args()

    if args.days < 0:
        print("Error: --days must be >= 0", file=sys.stderr)
        return 1

    target = args.dir
    if not target.exists():
        print(f"Target directory does not exist: {target} — nothing to clean.")
        return 0

    cutoff = time.time() - args.days * DAY_SECONDS
    targets = []
    for entry in target.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() != ".json":
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            targets.append((entry, mtime))

    targets.sort(key=lambda pair: pair[1])
    if not targets:
        print(f"No files older than {args.days} day(s) in {target}.")
        return 0

    verb = "Would delete" if args.dry_run else "Deleting"
    print(f"{verb} {len(targets)} file(s) older than {args.days} day(s) in {target}:\n")
    deleted = 0
    for entry, _mtime in targets:
        if args.dry_run:
            print(f"  [dry-run] {entry.name}")
        else:
            try:
                entry.unlink()
                print(f"  deleted   {entry.name}")
                deleted += 1
            except OSError as exc:
                print(f"  FAILED    {entry.name}: {exc}", file=sys.stderr)

    if args.dry_run:
        print(f"\nDry run — nothing was deleted. Re-run without --dry-run to remove {len(targets)} file(s).")
    else:
        print(f"\nDeleted {deleted}/{len(targets)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
