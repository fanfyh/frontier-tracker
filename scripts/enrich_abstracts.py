#!/usr/bin/env python3
"""Enrich frontier scan results with abstracts from multiple APIs.

Three-way concurrent fallback:
  1. OpenAlex  (via pyalex — API key + automatic abstract decoding)
  2. Crossref  (abstract field, HTML tags stripped)
  3. Semantic Scholar (abstract field, or AI tldr fallback)
  4. Elsevier ScienceDirect (for fresh Elsevier papers, requires insttoken)
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  — loads .env into os.environ (API keys)

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyalex
from pyalex import Works

OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "")
if OPENALEX_API_KEY:
    pyalex.config.api_key = OPENALEX_API_KEY
pyalex.config.mailto = "fanfyh210@gmail.com"

ELSEVIER_API_KEY = os.environ.get("ELSEVIER_API_KEY", "")
ELSEVIER_INSTTOKEN = os.environ.get("ELSEVIER_INSTTOKEN", "")
ELSEVIER_DOI_PREFIX = "10.1016/"

ROOT = Path(__file__).resolve().parents[1]

USER_AGENT = "frontier-tracker/2.0 (abstract-enricher; multi-source)"


def request_json(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _warn(source: str, doi: str, exc: Exception) -> None:
    sys.stderr.write(f"  [{source}] {doi}: {type(exc).__name__}: {exc}\n")


# --------------- OpenAlex (pyalex) ---------------

def fetch_openalex_abstract(doi: str) -> str | None:
    """Fetch abstract from OpenAlex by DOI. Singleton requests are free (0 credits)."""
    try:
        work = Works()[f"https://doi.org/{doi}"]
        abstract = work["abstract"]  # pyalex decodes inverted index automatically
        return abstract if abstract else None
    except Exception as e:
        _warn("openalex", doi, e)
        return None


# --------------- Crossref ---------------

def fetch_crossref_abstract(doi: str) -> str | None:
    """Fetch abstract from Crossref API by DOI. Strips HTML tags."""
    q = urllib.parse.quote(doi, safe="")
    url = f"https://api.crossref.org/works/{q}"
    try:
        data = request_json(url)
        abstract = (data.get("message", {}).get("abstract") or "").strip()
        if abstract:
            abstract = re.sub(r"<[^>]+>", " ", abstract)
            abstract = re.sub(r"\s+", " ", abstract).strip()
        return abstract if abstract else None
    except Exception as e:
        _warn("crossref", doi, e)
        return None


# --------------- Semantic Scholar ---------------

def fetch_s2_abstract(doi: str) -> str | None:
    """Fetch abstract from Semantic Scholar. Falls back to AI tldr."""
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=abstract,tldr"
    try:
        data = request_json(url)
        abstract = (data.get("abstract") or "").strip()
        if abstract:
            return abstract
        tldr = (data.get("tldr") or {}).get("text", "").strip()
        return f"[Highlight] {tldr}" if tldr else None
    except Exception as e:
        _warn("semantic_scholar", doi, e)
        return None


# --------------- Elsevier ScienceDirect ---------------

def fetch_elsevier_abstract(doi: str, api_key: str = "", insttoken: str = "") -> str | None:
    """Fetch abstract from Elsevier ScienceDirect. Requires insttoken for full access."""
    key = api_key or ELSEVIER_API_KEY
    inst = insttoken or ELSEVIER_INSTTOKEN
    if not key or not inst:
        return None
    url = f"https://api.elsevier.com/content/abstract/doi/{doi}?view=FULL"
    try:
        headers = {
            "X-ELS-APIKey": key,
            "X-ELS-Insttoken": inst,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        coredata = (data.get("abstracts-retrieval-response") or {}).get("coredata") or {}
        abstract = (coredata.get("dc:description") or "").strip()
        abstract = re.sub(r"^Abstract\s*", "", abstract)
        abstract = re.sub(r"<[^>]+>", " ", abstract)
        abstract = re.sub(r"\s+", " ", abstract).strip()
        return abstract if abstract else None
    except Exception as e:
        _warn("elsevier", doi, e)
        return None


# --------------- Multi-source concurrent fallback ---------------

def _fetch_multi(doi: str) -> tuple[str, str]:
    """OpenAlex first; then Crossref + S2 in parallel; then Elsevier for 10.1016/ DOIs."""
    abstract = fetch_openalex_abstract(doi)
    if abstract:
        return abstract, "openalex"

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        futures = {
            pool.submit(fetch_crossref_abstract, doi): "crossref",
            pool.submit(fetch_s2_abstract, doi): "semantic_scholar",
        }
        for future in as_completed(futures, timeout=15):
            try:
                result = future.result()
                if result:
                    return result, futures[future]
            except Exception:
                pass
    finally:
        # cancel_futures=True drops unstarted tasks; already-running threads
        # finish in the background without blocking the main thread (wait=False).
        pool.shutdown(wait=False, cancel_futures=True)

    if doi.startswith(ELSEVIER_DOI_PREFIX) and ELSEVIER_API_KEY:
        abstract = fetch_elsevier_abstract(doi)
        if abstract:
            return abstract, "elsevier"

    return "", "unavailable"


def enrich_single(paper: dict) -> dict:
    if paper.get("abstract"):
        paper.setdefault("abstract_source", "openalex")
        return paper

    doi = paper.get("doi", "").strip()
    if not doi:
        paper = dict(paper)
        paper.setdefault("abstract", "")
        paper.setdefault("abstract_source", "unavailable")
        return paper

    enriched_abstract, source = _fetch_multi(doi)
    paper = dict(paper)
    paper["abstract"] = enriched_abstract
    paper["abstract_source"] = source
    return paper


def enrich_papers(papers: list[dict], sleep_seconds: float = 0.15, force: bool = False) -> list[dict]:
    enriched = []
    total = len(papers)
    for i, p in enumerate(papers):
        if not force and p.get("abstract"):
            enriched.append(p)
        else:
            enriched.append(enrich_single(p))
        if (i + 1) % 20 == 0:
            print(f"  ... {i+1}/{total}", file=sys.stderr)
        time.sleep(sleep_seconds)
    has_abstract = sum(1 for p in enriched if p.get("abstract"))
    sources: dict[str, int] = {}
    for p in enriched:
        s = p.get("abstract_source", "unavailable")
        sources[s] = sources.get(s, 0) + 1
    print(f"  Abstracts: {has_abstract}/{total}  Sources: {sources}", file=sys.stderr)
    return enriched


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enrich scan results with abstracts (OpenAlex + Crossref + Semantic Scholar + Elsevier)."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--field", default="both", help="already_seen | new | both")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    print(f"Enriching from: {args.input.name}", file=sys.stderr)

    if args.field == "both":
        fields_to_enrich = ["already_seen", "new"]
    elif args.field in ("new", "already_seen"):
        fields_to_enrich = [args.field]
    else:
        print(f"Unknown field: {args.field}", file=sys.stderr)
        return 1

    total = 0
    for field in fields_to_enrich:
        papers = data.get(field, [])
        if papers:
            print(f"Enriching {field}: {len(papers)} papers...", file=sys.stderr)
            data[field] = enrich_papers(papers, args.sleep, force=args.force)
            total += len(papers)

    data["_enriched"] = True
    data["_enriched_fields"] = fields_to_enrich

    output_path = args.output or args.input
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved: {output_path} ({total} papers enriched)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
