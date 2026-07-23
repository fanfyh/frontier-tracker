#!/usr/bin/env python3
"""
Fetch papers from Zotero library collections for cross-matching with frontier-tracker.

Returns a flat list of dicts with: title, doi, collection_name, collection_key.

Usage:
    python scripts/cross_ref_zotero.py --output outputs/data/zotero_items.json
    python scripts/cross_ref_zotero.py --collection "保障性住房" --output outputs/data/zotero_items.json

Config from paper-finder config (Zotero API key) is read from config.json if available,
or can be set via env ZOTERO_API_KEY / ZOTERO_LIBRARY_ID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
PAPER_FINDER_CONFIG = Path.home() / ".claude/tools/paper-finder/config.json"


def load_zotero_creds() -> tuple[str, str]:
    """Load Zotero API key and library ID from paper-finder config or env."""
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
        sys.stderr.write(
            "Zotero credentials not found. Set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID env, "
            "or ensure ~/.claude/tools/paper-finder/config.json exists.\n"
        )
        sys.exit(1)

    return api_key, library_id


def fetch_json(url: str, api_key: str) -> list[dict] | dict:
    """Fetch a Zotero API URL and return parsed JSON. Handles pagination."""
    items = []
    while url:
        req = Request(url, headers={"Zotero-API-Key": api_key})
        try:
            resp = urlopen(req, timeout=30)
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                items.extend(data)
            else:
                return data
            # Check for next page
            link_header = resp.headers.get("Link", "")
            next_url = ""
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip().strip("<>")
                    break
            url = next_url if next_url else None
        except HTTPError as e:
            sys.stderr.write(f"HTTP {e.code}: {url}\n")
            break
        except json.JSONDecodeError:
            sys.stderr.write(f"JSON decode error: {url}\n")
            break
    return items


def build_collections_map(api_key: str, library_id: str) -> dict[str, str]:
    """Fetch all collections: {collection_key: collection_name}."""
    url = f"https://api.zotero.org/users/{library_id}/collections?limit=100"
    raw = fetch_json(url, api_key)
    if not isinstance(raw, list):
        return {}
    result = {}
    for c in raw:
        d = c.get("data", {})
        result[d["key"]] = d.get("name", "?")
    return result


def fetch_items_from_collections(
    api_key: str,
    library_id: str,
    collections_map: dict[str, str],
    target_collections: list[str] | None = None,
    since_days: int = 90,
) -> list[dict]:
    """
    Fetch items from specified collections (or all if None).
    Returns [{title, doi, collection_name, collection_key}].
    """
    items = []
    if target_collections:
        # Filter to matching collection keys
        target_keys = [
            k for k, n in collections_map.items() if n in target_collections
        ]
    else:
        target_keys = list(collections_map.keys())

    for ckey in target_keys:
        cname = collections_map.get(ckey, "?")
        url = (
            f"https://api.zotero.org/users/{library_id}"
            f"/collections/{ckey}/items/top?limit=100&sort=dateAdded&direction=desc"
        )
        raw = fetch_json(url, api_key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            d = item.get("data", {})
            title = d.get("title", "")
            # Extract DOI from extra field or from DOI field
            doi = d.get("DOI", "")
            if not doi:
                # Try parsing from extra
                extra = d.get("extra", "")
                for line in extra.split("\n"):
                    if line.lower().startswith("doi:"):
                        doi = line.split(":", 1)[1].strip()
            items.append({
                "title": title,
                "doi": doi,
                "collection_name": cname,
                "collection_key": ckey,
            })
        time.sleep(0.1)  # Rate limiter

    return items


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Zotero items for cross-matching with frontier-tracker."
    )
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Output JSON path."
    )
    parser.add_argument(
        "--collection", type=str, action="append",
        help="Filter by collection name(s). Can be specified multiple times. "
             "If omitted, fetches ALL collections."
    )
    parser.add_argument(
        "--since-days", type=int, default=90,
        help="Only fetch items added within this many days (default: 90)."
    )
    args = parser.parse_args()

    api_key, library_id = load_zotero_creds()

    collections_map = build_collections_map(api_key, library_id)
    if not collections_map:
        sys.stderr.write("No collections found or API error.\n")
        return 1

    print(f"Collections: {len(collections_map)}", file=sys.stderr)
    if args.collection:
        # Validate
        missing = [c for c in args.collection if c not in collections_map.values()]
        if missing:
            sys.stderr.write(f"Collections not found: {missing}\n")
            available = ", ".join(sorted(set(collections_map.values())))
            sys.stderr.write(f"Available: {available}\n")

    items = fetch_items_from_collections(
        api_key, library_id, collections_map,
        target_collections=args.collection,
        since_days=args.since_days,
    )

    # Deduplicate by DOI (prefer first occurrence)
    seen_dois = set()
    seen_titles = set()
    deduped = []
    for item in items:
        key = item["doi"] if item["doi"] else item["title"].lower().strip()
        if key and key not in seen_dois and key not in seen_titles:
            if item["doi"]:
                seen_dois.add(key)
            else:
                seen_titles.add(key)
            deduped.append(item)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(deduped, f, ensure_ascii=False, indent=2)

    print(f"\nFetched: {len(deduped)} unique items (from {len(items)} raw)", file=sys.stderr)
    print(f"Saved to: {args.output}", file=sys.stderr)

    # Print summary to stdout for pipeline
    print(json.dumps({
        "total_collections": len(collections_map),
        "fetched": len(items),
        "unique": len(deduped),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
