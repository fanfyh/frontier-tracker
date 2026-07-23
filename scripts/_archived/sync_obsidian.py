#!/usr/bin/env python3
"""Sync frontier-tracker obsidian notes to the Obsidian vault.

Usage:
    python sync_obsidian.py --notes-dir ~/.hermes/skills/frontier-tracker/outputs/notes/2026-05-14/obsidian_notes/ --vault ~/Documents/deadweight-notes/Literature/frontier-tracker/
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def parse_frontmatter(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    fm = {}
    in_front = False
    for line in content.split("\n"):
        if line.strip() == "---":
            if not in_front:
                in_front = True
                continue
            else:
                break
        if in_front and ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def slugify(title: str) -> str:
    """Convert title to safe filename."""
    # Remove chars that are problematic in filenames
    s = title.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s]+", "-", s)
    return s[:100]


def copy_note_to_vault(note_path: Path, vault_notes: Path) -> None:
    """Copy a note, updating its frontmatter with vault-specific fields."""
    fm = parse_frontmatter(note_path)
    content = note_path.read_text(encoding="utf-8")

    # Keep existing frontmatter, ensure these fields
    title = fm.get("title", note_path.stem)
    journal = fm.get("journal", "Unknown")
    published = fm.get("published", "")

    # Write as-is (Obsidian vault format is already compatible)
    dest = vault_notes / note_path.name
    dest.write_text(content, encoding="utf-8")


def group_by_journal(notes_dir: Path) -> dict[str, list[Path]]:
    """Group notes by journal for summary output."""
    grouped = {}
    for f in notes_dir.glob("*.md"):
        if f.name.startswith("."):
            continue
        fm = parse_frontmatter(f)
        journal = fm.get("journal", "Unknown")
        grouped.setdefault(journal, []).append(f)
    return grouped


def main():
    parser = argparse.ArgumentParser(description="Sync frontier-tracker notes to Obsidian vault")
    parser.add_argument("--notes-dir", required=True, help="Source obsidian_notes directory")
    parser.add_argument("--vault", required=True, help="Target vault Literature/frontier-tracker directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    notes_dir = Path(args.notes_dir)
    vault_notes = Path(args.vault)

    if not notes_dir.exists():
        print(f"Notes dir not found: {notes_dir}")
        sys.exit(1)

    vault_notes.mkdir(parents=True, exist_ok=True)

    grouped = group_by_journal(notes_dir)
    print(f"Found {len(grouped)} journals, {sum(len(v) for v in grouped.values())} notes total:")
    for j, fs in sorted(grouped.items()):
        print(f"  {j}: {len(fs)} papers")

    if args.dry_run:
        print("\nDry run — no files written.")
        return

    copied = 0
    for f in sorted(notes_dir.glob("*.md")):
        copy_note_to_vault(f, vault_notes)
        copied += 1

    print(f"\nSynced {copied} notes to {vault_notes}")


if __name__ == "__main__":
    main()
