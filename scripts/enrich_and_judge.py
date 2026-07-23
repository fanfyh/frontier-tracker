#!/usr/bin/env python3
"""
Call DeepSeek to generate Chinese translation + research judgment for each paper
in the enriched JSON. Results are written back into the JSON as _judgment fields.

Usage:
    python enrich_and_judge.py \\
        --input outputs/data/frontier_enriched_20260514.json \\
        --output outputs/data/frontier_enriched_judged_20260514.json \\
        --api-key sk-... \\
        --base-url https://api.deepseek.com

The output JSON is the same as input, with an added _judgment dict per paper.
Then use with render_display_outputs.py --enriched-json to generate Obsidian notes.
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  — loads .env into os.environ (API keys)

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import openai
except ImportError:
    sys.stderr.write("openai not installed. Run: pip install openai\n")
    sys.exit(1)

SYSTEM_PROMPT = """[ONE_SENTENCE]
英文摘要首句原文

[FULL_TRANSLATION]
中文翻译全文，保留完整学术内容

[JUDGMENT_DIRECT]
直接关联1-2句说明与以下核心话题的关联（保障房/住房补贴/技能错配/空间错配/人力资本外部性/劳动力流动/城市间迁移/财政竞争/税收竞争/地方政府竞争/公共品供给），若无关则写"无直接关联"

[JUDGMENT_INDIRECT]
间接关联1-2句说明与以下proxy话题的关联（place-based policy/城市生产率/房地产/基础设施/土地市场/政府债务），若无关则写"无间接关联"

[JUDGMENT_METHOD]
核心方法（RDD/DID/IV/实验/理论/描述性等）

[JUDGMENT_DATA]
数据来源与样本范围

[JUDGMENT_FINDING]
核心发现一句话

[JUDGMENT_WORTH]
MUST READ / SKIM / SKIP + 理由1句"""


def parse_response(text: str) -> dict:
    """Parse [KEY] value blocks from LLM response (multi-line values supported)."""
    result = {}
    pattern = r'\[([A-Z_]+)\]\s*\n?(.*?)(?=\n\[|$)'
    for key, value in re.findall(pattern, text, re.DOTALL):
        result[key] = value.strip()
    return result


_REQUIRED_KEYS = {"FULL_TRANSLATION", "JUDGMENT_WORTH", "JUDGMENT_FINDING"}
_MAX_RETRIES = 2


def judge_paper(title: str, journal: str, abstract: str, client) -> dict | None:
    """Call DeepSeek for one paper. Retries up to _MAX_RETRIES times on incomplete responses."""
    for attempt in range(1 + _MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"标题：{title}\n期刊：{journal}\n\n摘要：\n{abstract}",
                    },
                ],
                max_tokens=1000,
                temperature=0.3,
            )
            parsed = parse_response(resp.choices[0].message.content)
            if _REQUIRED_KEYS.issubset(parsed.keys()):
                return parsed
            sys.stderr.write(
                f"  [judge] Incomplete response (attempt {attempt + 1},"
                f" got keys: {set(parsed.keys())}): {title[:40]}\n"
            )
        except Exception as e:
            sys.stderr.write(f"  [judge] Error (attempt {attempt + 1}): {e}\n")
        if attempt < _MAX_RETRIES:
            time.sleep(2.0)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Chinese translation + LLM judgment for enriched papers."
    )
    parser.add_argument(
        "--input", type=Path, required=True,
        help="Enriched JSON from enrich_abstracts.py (must contain abstract field)."
    )
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Output path for the judged JSON."
    )
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="DeepSeek API key (defaults to DEEPSEEK_API_KEY env var)."
    )
    parser.add_argument(
        "--base-url", type=str,
        default=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        help="DeepSeek API base URL (defaults to DEEPSEEK_BASE_URL env, then the official endpoint)."
    )
    parser.add_argument(
        "--max-papers", type=int, default=0,
        help="Max papers to process (0 = all). Use for testing."
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip papers that already have a _judgment field."
    )
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: DeepSeek API key required (--api-key or DEEPSEEK_API_KEY env var)", file=sys.stderr)
        return 1
    client = openai.OpenAI(api_key=api_key, base_url=args.base_url)

    with args.input.open(encoding="utf-8") as f:
        data = json.load(f)

    # Collect all papers across buckets
    all_buckets = ("new", "already_seen", "needs_manual_verification")
    all_papers = []
    for bucket in all_buckets:
        for paper in data.get(bucket) or []:
            all_papers.append((bucket, paper))

    total = len(all_papers)
    to_process = [
        (b, p) for b, p in all_papers
        if p.get("abstract") and (not args.skip_existing or not p.get("_judgment"))
    ]

    if args.max_papers > 0:
        to_process = to_process[: args.max_papers]

    print(f"Total papers: {total}, to process: {len(to_process)}")

    for i, (bucket, paper) in enumerate(to_process):
        abstract = paper.get("abstract", "")
        if not abstract:
            print(f"  [{i+1}/{len(to_process)}] Skip (no abstract): {paper.get('title','')[:40]}")
            continue

        judgment = judge_paper(
            title=paper.get("title", ""),
            journal=paper.get("journal", ""),
            abstract=abstract,
            client=client,
        )

        if judgment:
            paper["_judgment"] = judgment
            print(f"  [{i+1}/{len(to_process)}] ✓ {paper.get('title','')[:45]}")
        else:
            print(f"  [{i+1}/{len(to_process)}] ✗ {paper.get('title','')[:45]}")

        time.sleep(1.2)  # Rate limit

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
