#!/usr/bin/env python3
"""
Cross-match frontier-tracker papers against Zotero collections.

Instead of title similarity (which rarely finds exact matches across datasets),
this module:
1. Extracts topic keywords from Zotero COLLECTION NAMES (manually curated categories)
2. Looks for those keywords in scanned papers' title + abstract
3. Scores papers by how well they align with Zotero research interests

This gives a "Zotero relevance score" that can be used alongside
the profile-based screening in screen_by_profile.py.

Usage:
    python scripts/match_zotero.py \
        --input outputs/data/frontier_enriched_<date>.json \
        --output outputs/data/frontier_enriched_<date>.json

Requires: ZOTERO_API_KEY env var or config from paper-finder.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PAPER_FINDER_CONFIG = Path.home() / ".claude/tools/paper-finder/config.json"

# Core research collections (manually selected — maps to your research areas)
CORE_COLLECTIONS = [
    "保障性住房",
    "0住房补贴-人才流动",
    "国社科",
    "国社科申请",
    "政府竞争",
    "配置逻辑",
    "1. 住房制度转型相关研究",
    "2. 中国式分权与公共品供给相关研究",
    "3. 保障性住房供给影响因素相关研究",
    "4. 住房福利效应评估相关研究",
    "1府际关系",
]


def load_zotero_creds() -> tuple[str, str]:
    api_key = os.environ.get("ZOTERO_API_KEY", "")
    library_id = os.environ.get("ZOTERO_LIBRARY_ID", "")
    if not api_key and PAPER_FINDER_CONFIG.exists():
        try:
            cfg = json.loads(PAPER_FINDER_CONFIG.read_text(encoding="utf-8"))
            z = cfg.get("zotero", {})
            api_key = api_key or z.get("api_key", "")
            library_id = library_id or str(z.get("library_id", ""))
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    if not api_key or not library_id:
        sys.stderr.write("Zotero credentials not found.\n")
        sys.exit(1)
    return api_key, library_id


def fetch_json(url: str, api_key: str) -> list[dict]:
    items = []
    while url:
        req = Request(url, headers={"Zotero-API-Key": api_key})
        resp = urlopen(req, timeout=30)
        data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list):
            items.extend(data)
        link_header = resp.headers.get("Link", "")
        next_url = ""
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                break
        url = next_url if next_url else None
    return items


def build_collection_map(api_key: str, library_id: str) -> dict[str, str]:
    url = f"https://api.zotero.org/users/{library_id}/collections?limit=100"
    raw = fetch_json(url, api_key)
    return {c["data"]["key"]: c["data"]["name"] for c in raw if isinstance(c, dict)}


def fetch_items_from_collection(api_key: str, library_id: str, ckey: str) -> list[dict]:
    """Fetch all items from a single collection."""
    url = f"https://api.zotero.org/users/{library_id}/collections/{ckey}/items/top?limit=200"
    raw = fetch_json(url, api_key)
    items = []
    for item in raw:
        d = item.get("data", {})
        title = d.get("title", "")
        doi = d.get("DOI", "")
        if not doi:
            extra = d.get("extra", "")
            for line in extra.split("\n"):
                if line.lower().startswith("doi:"):
                    doi = line.split(":", 1)[1].strip()
        items.append({"title": title, "doi": doi})
    return items


def extract_keywords(text: str) -> list[str]:
    """Extract meaningful lowercase keywords from text."""
    if not text:
        return []
    text = text.lower()
    # Split on non-alphanumeric
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text)
    stopwords = {
        "the", "and", "for", "that", "this", "with", "from", "are", "was",
        "been", "have", "has", "had", "not", "but", "its", "all", "any",
        "can", "may", "more", "most", "some", "than", "also", "very",
        "just", "only", "new", "using", "based", "study", "research",
        "analysis", "approach", "data", "model", "effect", "evidence",
        "across", "within", "without", "among", "between", "over",
        "under", "such", "which", "while", "because", "through",
        "during", "after", "about", "into",
    }
    return [w for w in words if len(w) >= 4 and w not in stopwords]


def build_profile_from_collections(
    api_key: str, library_id: str,
) -> dict:
    """
    Fetch items from core Zotero collections, extract keyword profile
    (word frequency), and return the profile + collection names.
    """
    col_map = build_collection_map(api_key, library_id)
    name_to_key = {v: k for k, v in col_map.items()}

    keyword_scores = {}  # keyword -> count
    collection_papers = {}  # collection_name -> [titles]
    seen_dois = set()

    for cname in CORE_COLLECTIONS:
        if cname not in name_to_key:
            continue
        ckey = name_to_key[cname]
        items = fetch_items_from_collection(api_key, library_id, ckey)
        collection_papers[cname] = [i["title"] for i in items]

        for item in items:
            # Deduplicate by DOI
            doi = item.get("doi", "")
            doi_key = doi.lower().strip() if doi else item["title"]
            if doi_key in seen_dois:
                continue
            seen_dois.add(doi_key)

            title = item.get("title", "")
            kws = extract_keywords(title)
            for kw in kws:
                keyword_scores[kw] = keyword_scores.get(kw, 0) + 1

        time.sleep(0.1)

    # Normalize scores to frequencies
    total = sum(keyword_scores.values())
    if total > 0:
        keyword_scores = {k: round(v / total, 5) for k, v in keyword_scores.items()}

    return {
        "keyword_profile": keyword_scores,
        "collection_papers": collection_papers,
        "total_items": len(seen_dois),
    }


def score_paper(
    title: str,
    abstract: str,
    keyword_profile: dict[str, float],
    threshold: float = 0.05,
) -> dict:
    """Score a paper against the Zotero keyword profile."""
    text = f"{title} {abstract}"
    kws = extract_keywords(text)
    matched = {}
    for kw in kws:
        if kw in keyword_profile:
            matched[kw] = keyword_profile[kw]
    score = sum(matched.values())
    matched_words = sorted(matched, key=matched.get, reverse=True)[:20]
    return {
        "zotero_score": round(score, 4),
        "zotero_matches": matched_words,
        "zotero_relevant": score >= threshold,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Zotero cross-matching for frontier-tracker.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.05)
    args = parser.parse_args()

    api_key, library_id = load_zotero_creds()

    with args.input.open(encoding="utf-8") as f:
        data = json.load(f)

    # Build keyword profile from Zotero collections
    profile = build_profile_from_collections(api_key, library_id)
    print(f"Zotero collections: {len(profile['collection_papers'])}", file=sys.stderr)
    print(f"Total unique items: {profile['total_items']}", file=sys.stderr)
    print(f"Keyword types: {len(profile['keyword_profile'])}", file=sys.stderr)
    top10 = sorted(profile["keyword_profile"].items(), key=lambda x: -x[1])[:10]
    print(f"Top keywords: {', '.join(f'{k}({v:.4f})' for k,v in top10)}", file=sys.stderr)

    # Score all papers
    total_rel = 0
    for bucket in ("new", "already_seen", "needs_manual_verification"):
        papers = data.get(bucket) or []
        for paper in papers:
            result = score_paper(
                paper.get("title", ""),
                paper.get("abstract", ""),
                profile["keyword_profile"],
                args.threshold,
            )
            paper["zotero_score"] = result["zotero_score"]
            paper["zotero_matches"] = result["zotero_matches"]
            paper["zotero_relevant"] = result["zotero_relevant"]
        rel_count = sum(1 for p in papers if p.get("zotero_relevant"))
        print(f"  {bucket}: {len(papers)} papers, {rel_count} relevant", file=sys.stderr)
        total_rel += rel_count

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "zotero_collections": len(profile["collection_papers"]),
        "zotero_items": profile["total_items"],
        "papers_scored": sum(len(data.get(b, [])) for b in ("new", "already_seen", "needs_manual_verification")),
        "relevant": total_rel,
        "threshold": args.threshold,
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
