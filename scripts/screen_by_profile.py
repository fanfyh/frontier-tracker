#!/usr/bin/env python3
"""Screen frontier scan results by research profile using keyword-based tiering.

Each paper is classified into one tier and assigned downstream-facing fields:

  tier     -> priority / relevance / status
  ---------------------------------------------------
  core     -> P1 / core      / to-screen
  proxy    -> P2 / proxy     / to-screen
  method   -> P2 / method    / to-screen
  noise    -> P3 / noise     / skip       (exclusion hit or no keyword hit)

Profile markdown is expected to expose these sections:
  ## Core topics
  ## Proxy topics
  ## Methods
  ## Exclusion topics

Usage:
  python -X utf8 scripts/screen_by_profile.py \
    --input outputs/data/frontier_judged_<date>.json \
    --profile references/fanfy-housing-fiscal.md \
    --output outputs/data/frontier_screened_<date>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TIER_TO_FIELDS = {
    "core":   {"priority": "P1", "relevance": "core",   "status": "to-screen"},
    "proxy":  {"priority": "P2", "relevance": "proxy",  "status": "to-screen"},
    "method": {"priority": "P2", "relevance": "method", "status": "to-screen"},
    "noise":  {"priority": "P3", "relevance": "noise",  "status": "skip"},
}


def extract_section(text: str, heading: str) -> list[str]:
    """Return keywords listed under `## heading` in a lowered markdown text.

    Supports `- item`, `* item`, `1. item` bullets and plain-text lines.
    """
    pattern = rf"#+\s*{re.escape(heading)}.*?\n(.*?)(?=\n#+\s|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []
    body = match.group(1)
    items = re.findall(
        r"(?:^|\n)\s*(?:[-*]|\d+[.)])\s+(.+?)(?=\n\s*(?:[-*]|\d+[.)])|\Z)",
        body,
        re.DOTALL,
    )
    if items:
        return [s.strip().strip('"').strip("'") for s in items if s.strip()]
    lines = [line.strip() for line in body.strip().split("\n") if line.strip()]
    return [s.strip('"').strip("'") for s in lines]


def load_profile_keywords(
    profile_path: Path | None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (core, proxy, methods, exclusion) keyword lists from the profile.

    If the profile is missing, returns empty lists — caller will then treat every
    paper as noise. We intentionally do not ship a domain fallback to avoid
    silently classifying with the wrong vocabulary.
    """
    if not profile_path or not profile_path.exists():
        return [], [], [], []

    text = profile_path.read_text(encoding="utf-8").lower()
    core = extract_section(text, "core topics") or extract_section(text, "core")
    proxy = extract_section(text, "proxy topics") or extract_section(text, "proxy")
    methods = extract_section(text, "methods") or extract_section(text, "method")
    exclusion = (
        extract_section(text, "exclusion topics")
        or extract_section(text, "exclusion")
        or extract_section(text, "exclude")
    )
    return core, proxy, methods, exclusion


def _kw_match(kw: str, text: str) -> bool:
    """Match keyword with word boundaries to avoid substring false positives."""
    return bool(re.search(r"\b" + re.escape(kw) + r"\b", text))


def classify_paper(
    title: str,
    abstract: str,
    core_kw: list[str],
    proxy_kw: list[str],
    method_kw: list[str],
    exclusion_kw: list[str],
) -> str:
    """Classify a paper. Exclusion overrides everything."""
    text = (title + " " + abstract).lower()

    if exclusion_kw and any(_kw_match(kw, text) for kw in exclusion_kw):
        return "noise"

    core_hits = sum(1 for kw in core_kw if _kw_match(kw, text))
    proxy_hits = sum(1 for kw in proxy_kw if _kw_match(kw, text))
    method_hits = sum(1 for kw in method_kw if _kw_match(kw, text))

    if core_hits:
        return "core"
    if proxy_hits:
        return "proxy"
    if method_hits >= 2:
        # Methodological-only papers are useful when several method markers
        # co-occur; a single isolated keyword is too weak to surface.
        return "method"
    return "noise"


def screen_papers(
    papers: list[dict],
    core_kw: list[str],
    proxy_kw: list[str],
    method_kw: list[str],
    exclusion_kw: list[str],
) -> list[dict]:
    scored = []
    for p in papers:
        title = p.get("title") or ""
        abstract = p.get("abstract") or ""
        tier = classify_paper(title, abstract, core_kw, proxy_kw, method_kw, exclusion_kw)
        p = dict(p)
        p["tier"] = tier
        p.update(TIER_TO_FIELDS[tier])
        scored.append(p)
    return scored


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Screen scan results by profile keywords.")
    parser.add_argument("--input", type=Path, required=True, help="Enriched/judged scan JSON.")
    parser.add_argument("--profile", type=Path, help="Profile markdown with Core/Proxy/Methods/Exclusion sections.")
    parser.add_argument("--output", type=Path, help="Output screened JSON.")
    parser.add_argument(
        "--field",
        default="both",
        choices=["new", "already_seen", "needs_manual_verification", "both", "all"],
        help="Which bucket(s) to screen. 'both' = new + already_seen; 'all' = include needs_manual_verification too.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    core_kw, proxy_kw, method_kw, exclusion_kw = load_profile_keywords(args.profile)

    if not core_kw and not proxy_kw and not method_kw:
        print(
            f"WARNING: profile {args.profile} produced empty keyword lists — every paper will be tier=noise.",
            file=sys.stderr,
        )

    print(
        f"Profile: core={len(core_kw)} proxy={len(proxy_kw)} method={len(method_kw)} exclusion={len(exclusion_kw)}",
        file=sys.stderr,
    )

    if args.field == "both":
        fields = ["new", "already_seen"]
    elif args.field == "all":
        fields = ["new", "already_seen", "needs_manual_verification"]
    else:
        fields = [args.field]

    stats = {"total": 0, "core": 0, "proxy": 0, "method": 0, "noise": 0}
    for field in fields:
        papers = data.get(field, [])
        if not papers:
            continue
        scored = screen_papers(papers, core_kw, proxy_kw, method_kw, exclusion_kw)
        data[field] = scored
        for p in scored:
            stats["total"] += 1
            stats[p["tier"]] = stats.get(p["tier"], 0) + 1

    data["_screened"] = True
    data["_profile_stats"] = stats

    print(
        f"Total: {stats['total']} | core={stats['core']} proxy={stats['proxy']} "
        f"method={stats['method']} noise={stats['noise']}",
        file=sys.stderr,
    )

    output_path = args.output or args.input
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
