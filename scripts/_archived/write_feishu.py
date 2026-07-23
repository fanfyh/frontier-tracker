#!/usr/bin/env python3
"""Write frontier-tracker notes to Feishu docs, grouped by journal."""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

# ── Feishu config ────────────────────────────────────────────────────────────
APP_ID = "cli_a967419b07f8dbb3"
APP_SECRET = "5XiTdDJl5VaU5QwPRHCYaftlukXXtz4z"
FEISHU_BASE = "https://open.feishu.cn/open-apis"


def get_token() -> str:
    resp = requests.post(
        f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["tenant_access_token"]


def create_doc(token: str, title: str) -> str:
    resp = requests.post(
        f"{FEISHU_BASE}/docx/v1/documents",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["data"]["document"]["document_id"]


def write_blocks(token: str, doc_token: str, blocks: list) -> None:
    url = f"{FEISHU_BASE}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"children": blocks},
        timeout=10,
    )
    resp.raise_for_status()
    if resp.json().get("code") != 0:
        raise RuntimeError(f"Feishu write error: {resp.json()}")


# ── Block builders ───────────────────────────────────────────────────────────
def h1(text: str) -> dict:
    return {"block_type": 3, "heading1": {"elements": [{"text_run": {"content": text}}]}}


def h2(text: str) -> dict:
    return {"block_type": 4, "heading2": {"elements": [{"text_run": {"content": text}}]}}


def para(text: str) -> dict:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": text}}]}}


def bullet(text: str) -> dict:
    return {"block_type": 12, "bullet": {"elements": [{"text_run": {"content": text}}]}}


def divider() -> dict:
    return {"block_type": 22}  # divider block type


def blank() -> dict:
    return {"block_type": 2, "text": {"elements": [{"text_run": {"content": ""}}]}}


# ── Parse note file ────────────────────────────────────────────────────────────
def parse_note(path: Path) -> tuple[dict, dict]:
    """Returns (frontmatter, sections)."""
    content = path.read_text(encoding="utf-8")
    frontmatter = {}
    body_lines = []
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
            frontmatter[k.strip()] = v.strip().strip('"')
        elif in_front:
            body_lines.append(line)

    sections = {}
    current = None
    for line in content.split("\n"):
        m = re.match(r"(#{1,3})\s+(.+)", line)
        if m:
            current = m.group(2).strip()
            sections[current] = []
        elif current and line.strip():
            sections[current].append(line.rstrip())

    return frontmatter, sections


def render_paper_blocks(meta: dict, sections: dict) -> list[dict]:
    blocks = []
    title = meta.get("title", "Untitled")
    journal = meta.get("journal", "")
    published = meta.get("published", "")
    doi = meta.get("doi", "")
    status = meta.get("status", "")
    priority = meta.get("priority", "")
    relevance = meta.get("relevance", "")
    authors_raw = sections.get("基本信息", [])
    authors = ""
    for line in authors_raw:
        m = re.search(r"作者[：:]\s*(.+)", line)
        if m:
            authors = m.group(1).strip()
            break

    # Title
    blocks.append(h1(title))
    blocks.append(blank())

    # Meta row
    meta_parts = [f"期刊：{journal}", f"日期：{published}"]
    if doi:
        meta_parts.append(f"DOI：https://doi.org/{doi}" if not doi.startswith("http") else f"DOI：{doi}")
    blocks.append(para(" | ".join(meta_parts)))
    if authors:
        blocks.append(para(f"作者：{authors}"))
    blocks.append(para(f"筛选状态：{status} | 优先级：{priority} | 相关度：{relevance}"))
    blocks.append(blank())

    # 一句话判断
    if "一句话判断" in sections:
        blocks.append(h2("一句话判断"))
        for line in sections["一句话判断"]:
            blocks.append(bullet(line))
        blocks.append(blank())

    # 与我研究的关系
    if "与我研究的关系" in sections:
        blocks.append(h2("与我研究的关系"))
        for line in sections["与我研究的关系"]:
            blocks.append(bullet(line))
        blocks.append(blank())

    # 核心问题
    if "核心问题" in sections:
        blocks.append(h2("核心问题"))
        for line in sections["核心问题"]:
            blocks.append(bullet(line))
        blocks.append(blank())

    # 可提取内容
    if "可提取内容" in sections:
        blocks.append(h2("可提取内容"))
        for line in sections["可提取内容"]:
            blocks.append(bullet(line))
        blocks.append(blank())

    # 我的下一步
    if "我的下一步" in sections:
        blocks.append(h2("我的下一步"))
        for line in sections["我的下一步"]:
            blocks.append(bullet(line))

    return blocks


# ── Journal grouping ─────────────────────────────────────────────────────────
def group_by_journal(notes_dir: Path) -> dict[str, list[Path]]:
    grouped = {}
    for f in sorted(notes_dir.glob("*.md")):
        if f.name.startswith("."):
            continue
        _, sections = parse_note(f)
        journal = sections.get("基本信息", ["期刊：Unknown"])[0]
        m = re.search(r"期刊[：:]\s*(.+)", journal)
        j = m.group(1).strip() if m else "Unknown"
        grouped.setdefault(j, []).append(f)
    return grouped


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Write frontier-tracker notes to Feishu")
    parser.add_argument("--notes-dir", required=True, help="Path to obsidian_notes directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without writing")
    args = parser.parse_args()

    notes_dir = Path(args.notes_dir)
    if not notes_dir.exists():
        print(f"Notes dir not found: {notes_dir}")
        sys.exit(1)

    grouped = group_by_journal(notes_dir)
    print(f"Found {len(grouped)} journals:")
    for j, fs in sorted(grouped.items()):
        print(f"  {j}: {len(fs)} papers")

    if args.dry_run:
        print("\nDry run — no docs created.")
        return

    token = get_token()
    print(f"\nFeishu token obtained")

    for journal, files in sorted(grouped.items()):
        # Create journal doc
        doc_title = f"{journal} 2026"
        try:
            doc_token = create_doc(token, doc_title)
            print(f"\nCreated: {doc_title} ({doc_token})")
        except Exception as e:
            print(f"Error creating {doc_title}: {e}")
            continue

        # Write all papers into one doc
        all_blocks = []
        for f in files:
            meta, sections = parse_note(f)
            blocks = render_paper_blocks(meta, sections)
            all_blocks.extend(blocks)
            all_blocks.append(divider())
            all_blocks.append(blank())

        try:
            write_blocks(token, doc_token, all_blocks)
            print(f"  Wrote {len(all_blocks)} blocks from {len(files)} papers")
            print(f"  URL: https://pkupm.feishu.cn/docx/{doc_token}")
        except Exception as e:
            print(f"Error writing blocks: {e}")


if __name__ == "__main__":
    main()
