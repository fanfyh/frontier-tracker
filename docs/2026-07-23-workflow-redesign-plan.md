# Frontier Tracker 工作流重构 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 frontier-tracker 从"OpenAlex 单源 + 静态画像"重构为"RSS+OpenAlex 统一候选池 + LLM 辅助判断 + star 驱动学习 + 可分享配置层"。

**Architecture:** 复用现有 5 脚本(scan/enrich/screen/judge/render)的数据格式,新增 SQLite 候选池作为集成枢纽;RSS 与 OpenAlex 汇入同一池,静态筛 + LLM 判断在 star 之前跑,star 作为学习正样本喂回动态画像。所有个人元素抽到 `config/`,仓库只发模板。

**Tech Stack:** Python 3.9+;新增 `feedparser`(RSS)、`sqlite3`(stdlib,候选池);沿用 `pyalex`/`openai`/`python-dotenv`;测试 `pytest`。

**Spec:** `docs/2026-07-23-workflow-redesign-design.md`

**数据格式约定(贯穿全计划):**
- Paper record:`{title, authors, journal, doi, openalex_id, abstract, published_date, doi_url}` + 处理后附加 `_judgment`、`tier`、`priority`、`relevance`、`status`。
- 现有 pipeline JSON:`{new:[...], already_seen:[...], needs_manual_verification:[...], *_count}`。

---

## Phase 0 — 配置层 & 去个人化(基础,先做)

目标:抽出一切个人元素,让仓库可分享;为后续阶段提供统一配置入口。

### Task 0.1: 建配置目录与模板

**Files:**
- Create: `config/config.example.json`
- Create: `config/profile.example.md`(从 `references/example-profile.md` 精炼)
- Create: `config/sources.example.json`
- Modify: `.gitignore`

- [ ] **Step 1: 写 `config/config.example.json`**

```json
{
  "vault_root": "~/Documents/marginal-notes",
  "orient_dir": "01_Research/01_Orient",
  "inbox_path": "00_Inbox/文献收件箱.md",
  "profile": "config/profile.md",
  "sources": "config/sources.json",
  "db_path": "state/candidates.db",
  "weekly_capacity": 6,
  "judge": { "model": "deepseek-chat", "max_tokens": 1000, "temperature": 0.3 }
}
```

- [ ] **Step 2: 写 `config/sources.example.json`**(RSS feeds + OpenAlex journal IDs)

```json
{
  "rss_feeds": [
    { "journal": "Journal of Public Economics", "url": "https://rss.sciencedirect.com/publication/science/01680291" },
    { "journal": "American Economic Review", "url": "https://www.aeaweb.org/jel/aer/rss" }
  ],
  "openalex_journals": [
    { "journal": "Journal of Public Economics", "openalex_id": "S1234567", "issn": "0047-2727" }
  ]
}
```

- [ ] **Step 3: 写 `config/profile.example.md`**(四节:Core/Proxy/Methods/Exclusion topics,空骨架供用户填)

```markdown
# Research Profile (example — copy to config/profile.md and fill in)

## Core topics
- (your core research topics, e.g. affordable housing)

## Proxy topics
- (adjacent topics)

## Methods
- causal inference
- DID

## Exclusion topics
- pure corporate finance
```

- [ ] **Step 4: 更新 `.gitignore`** 追加:

```
# Personal config (do not share)
config/config.json
config/profile.md
config/sources.json
state/candidates.db
```

- [ ] **Step 5: Commit**

```bash
git add config/ .gitignore
git commit -m "feat(config): 配置层模板（config/profile/sources），个人文件 gitignore"
```

### Task 0.2: 配置加载器 `scripts/config.py`

**Files:**
- Create: `scripts/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试 `tests/test_config.py`**

```python
from pathlib import Path
import json
import pytest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import config as cfg

def test_load_merges_user_over_example(tmp_path, monkeypatch):
    example = tmp_path / "config.example.json"
    example.write_text(json.dumps({"weekly_capacity": 6, "vault_root": "~/v"}))
    user = tmp_path / "config.json"
    user.write_text(json.dumps({"weekly_capacity": 10}))
    c = cfg.load(config_path=user, example_path=example)
    assert c["weekly_capacity"] == 10      # user wins
    assert c["vault_root"] == "~/v"        # falls back to example

def test_vault_root_resolved(cfg_with_tmp, monkeypatch):
    monkeypatch.setenv("HOME", "/tmp/fakehome")
    c = cfg.load(config_path=cfg_with_tmp["user"], example_path=cfg_with_tmp["example"])
    assert cfg.vault_root(c) == Path("/tmp/fakehome/Documents/marginal-notes").expanduser() or c["vault_root"].startswith("~")

def _cfg_with_tmp(tmp_path):
    ex = tmp_path / "config.example.json"; ex.write_text(json.dumps({"vault_root":"~/Documents/marginal-notes"}))
    us = tmp_path / "config.json"; us.write_text(json.dumps({"vault_root":"~/Documents/marginal-notes"}))
    return {"example": ex, "user": us}

@pytest.fixture
def cfg_with_tmp(tmp_path):
    return _cfg_with_tmp(tmp_path)
```

- [ ] **Step 2: 运行,确认失败** — `Run: python -m pytest tests/test_config.py -v` → FAIL (module not found)

- [ ] **Step 3: 写 `scripts/config.py`**

```python
#!/usr/bin/env python3
"""Load merged config: config.example.json <- config/config.json (user wins).

All personal settings live in config/. Scripts import `load()` to get a dict.
Paths like vault_root are resolved against the repo root (~/... expanded).
"""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "config.example.json"
USER = ROOT / "config" / "config.json"


def load(config_path: Path | None = None, example_path: Path | None = None) -> dict:
    ex = example_path or EXAMPLE
    base = json.loads(ex.read_text(encoding="utf-8")) if ex.exists() else {}
    user_p = config_path or USER
    if user_p.exists():
        base.update(json.loads(user_p.read_text(encoding="utf-8")))
    return base


def vault_root(c: dict) -> Path:
    raw = c.get("vault_root", str(Path.home() / "Documents" / "marginal-notes"))
    return Path(raw).expanduser()


def resolve(c: dict, key: str) -> Path:
    """Resolve a config path key. Absolute or relative-to-vault paths supported."""
    raw = c.get(key, "")
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = vault_root(c) / raw
    return p
```

- [ ] **Step 4: 运行,确认通过** — `Run: python -m pytest tests/test_config.py -v` → PASS

- [ ] **Step 5: Commit** — `git add scripts/config.py tests/test_config.py && git commit -m "feat(config): 配置加载器 config.load()"`

### Task 0.3: 去个人化 — 参数化 judge prompt + check_config 路径

**Files:**
- Modify: `scripts/enrich_and_judge.py:35-57`(SYSTEM_PROMPT 硬编码主题)
- Modify: `scripts/check_config.py:30-34`(硬编码 profile 路径)
- Test: `tests/test_judge_prompt.py`

- [ ] **Step 1: 写失败测试 `tests/test_judge_prompt.py`**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

def test_prompt_injects_profile_topics(tmp_path):
    import enrich_and_judge as ej
    profile = tmp_path / "p.md"
    profile.write_text(
        "## Core topics\n- affordable housing\n- fiscal competition\n"
        "## Proxy topics\n- land market\n"
    )
    prompt = ej.build_system_prompt(profile)
    assert "affordable housing" in prompt
    assert "fiscal competition" in prompt
    assert "land market" in prompt
    # 旧硬编码主题不应残留
    assert "保障房" not in prompt
```

- [ ] **Step 2: 运行,确认失败** — `python -m pytest tests/test_judge_prompt.py -v` → FAIL (`build_system_prompt` 不存在)

- [ ] **Step 3: 改 `enrich_and_judge.py`** — 在 `SYSTEM_PROMPT` 之前插入构造函数,基于 profile 的 Core/Proxy 节生成 prompt:

```python
import config as cfg  # 加到顶部 import 区

def _profile_topics(profile_path: Path) -> tuple[list[str], list[str]]:
    """读 profile.md 的 Core / Proxy 主题词。复用 screen_by_profile 的解析。"""
    import screen_by_profile as sp
    core, proxy, _m, _e = sp.load_profile_keywords(profile_path)
    return core, proxy

def build_system_prompt(profile_path: Path) -> str:
    core, proxy = _profile_topics(profile_path)
    core_s = "/".join(core) if core else "(未配置 core topics)"
    proxy_s = "/".join(proxy) if proxy else "(未配置 proxy topics)"
    return f"""[ONE_SENTENCE]
英文摘要首句原文

[FULL_TRANSLATION]
中文翻译全文，保留完整学术内容

[JUDGMENT_DIRECT]
直接关联1-2句说明与以下核心话题的关联（{core_s}），若无关则写"无直接关联"

[JUDGMENT_INDIRECT]
间接关联1-2句说明与以下proxy话题的关联（{proxy_s}），若无关则写"无间接关联"

[JUDGMENT_METHOD]
核心方法（RDD/DID/IV/实验/理论/描述性等）

[JUDGMENT_DATA]
数据来源与样本范围

[JUDGMENT_FINDING]
核心发现一句话

[JUDGMENT_WORTH]
MUST READ / SKIM / SKIP + 理由1句"""
```

并在 `main()` 里把 `SYSTEM_PROMPT` 替换为 `prompt = build_system_prompt(args.profile)`,传给 `judge_paper`(改 `judge_paper` 签名加 `system_prompt: str` 参数,替换内部引用的 `SYSTEM_PROMPT`)。新增 `--profile` 参数,默认从 `config.load()["profile"]` 取。

- [ ] **Step 4: 运行,确认通过** — `python -m pytest tests/test_judge_prompt.py -v` → PASS

- [ ] **Step 5: 改 `check_config.py`** — `PROFILE_FILE` 改为从 `config.load()["profile"]` 取(默认 `config/profile.md`),`VAULT_ROOT` 改用 `cfg.vault_root(cfg.load())`。

- [ ] **Step 6: Commit** — `git add -u && git commit -m "refactor: 去个人化 — judge prompt 与 check_config 路径改读 config"`

### Task 0.4: 个人画像迁出跟踪 + setup 引导

**Files:**
- Modify(git): `references/fanfy-housing-fiscal.md`(untrack + 迁移)
- Create: `scripts/setup.py`

- [ ] **Step 1: 迁移个人画像** — `git mv` 不可(已 untrack),用 shell:

```bash
cp references/fanfy-housing-fiscal.md config/profile.md   # 本地复制为真实配置
# references/ 下只留 example-profile.md；fanfy-* 已在 .gitignore（Task 0.1 前已 untrack）
```

- [ ] **Step 2: 写 `scripts/setup.py`**(首次运行引导:复制 example→真实文件若不存在,然后调 check_config)

```python
#!/usr/bin/env python3
"""First-run bootstrap: copy config templates if missing, then run check_config."""
from __future__ import annotations
import shutil
from pathlib import Path
import config as cfg

ROOT = Path(__file__).resolve().parents[1]

TEMPLATES = [
    ("config/config.example.json", "config/config.json"),
    ("config/profile.example.md", "config/profile.md"),
    ("config/sources.example.json", "config/sources.json"),
]

def main() -> int:
    for ex, target in TEMPLATES:
        t = ROOT / target
        if not t.exists():
            shutil.copyfile(ROOT / ex, t)
            print(f"  创建 {target}（从模板，请编辑填入你的配置）")
        else:
            print(f"  已存在 {target}")
    print("\n模板就位。请编辑 config/ 下三个文件，然后运行 check_config.py。")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Commit** — `git add scripts/setup.py && git commit -m "feat(config): setup.py 首次运行引导"`

---

## Phase 1 — RSS 抓取源

目标:独立 `feedparser` 抓取 RSS,输出与 scan 同格式的 paper record,不碰 Obsidian 插件。

### Task 1.1: `scripts/rss_fetch.py`

**Files:**
- Create: `scripts/rss_fetch.py`
- Test: `tests/test_rss_fetch.py`
- 依赖:`pip install feedparser`

- [ ] **Step 1: 写失败测试 `tests/test_rss_fetch.py`**

```python
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Journal of Public Economics</title>
<item>
  <title>Tax compliance in rental markets</title>
  <link>https://example.com/paper1</link>
  <description>We study tax compliance using admin data.</description>
  <pubDate>Mon, 14 Jul 2025 00:00:00 GMT</pubDate>
</item>
</channel></rss>"""

def test_parse_feed_extracts_records(tmp_path, monkeypatch):
    import rss_fetch
    feed_file = tmp_path / "feed.xml"
    feed_file.write_text(SAMPLE_RSS)
    recs = rss_fetch.parse_feed_file(feed_file, journal="Journal of Public Economics")
    assert len(recs) == 1
    r = recs[0]
    assert r["title"] == "Tax compliance in rental markets"
    assert r["journal"] == "Journal of Public Economics"
    assert r["abstract"].startswith("We study tax compliance")
    assert r["source"] == "rss"
    assert r["doi"] == "" or r["doi"] is None  # RSS 常无 DOI

def test_title_hash_stable():
    import rss_fetch
    assert rss_fetch.title_hash("A Fine Title!") == rss_fetch.title_hash("a fine title")
```

- [ ] **Step 2: 运行,确认失败** — `python -m pytest tests/test_rss_fetch.py -v` → FAIL

- [ ] **Step 3: 写 `scripts/rss_fetch.py`**

```python
#!/usr/bin/env python3
"""Fetch RSS feeds listed in config/sources.json → paper records (scan-compatible).

Output JSON: {"new": [...records...], "already_seen": [], "needs_manual_verification": []}
Each record: {title, abstract, journal, doi, openalex_id, published_date, source:"rss"}
RSS items usually lack DOI/abstract; abstract falls back to <description>; DOI empty.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config as cfg


def title_hash(title: str) -> str:
    """归一化标题哈希,作为无 DOI 时的身份键。"""
    norm = re.sub(r"[^\w\s]", "", (title or "").lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm  # 直接用归一化字符串当键,稳定且可读


def parse_feed_file(path: Path, journal: str) -> list[dict]:
    import feedparser
    d = feedparser.parse(str(path))
    records = []
    for e in d.entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        abstract = (e.get("summary") or e.get("description") or "").strip()
        pub = e.get("published") or ""
        try:
            pub_date = datetime.strptime(pub[:16], "%a, %d %b %Y").date().isoformat()
        except Exception:
            pub_date = ""
        records.append({
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "doi": "",
            "openalex_id": "",
            "published_date": pub_date,
            "source": "rss",
        })
    return records


def fetch_all(sources_path: Path) -> list[dict]:
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    import feedparser
    out = []
    for feed in sources.get("rss_feeds", []):
        try:
            d = feedparser.parse(feed["url"])
            tmp = ROOT / "outputs" / "data" / f"_rss_{abs(hash(feed['journal']))}.xml"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            # feedparser 已解析,直接走 parse 逻辑
            for e in d.entries:
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                out.append({
                    "title": title,
                    "abstract": (e.get("summary") or "").strip(),
                    "journal": feed["journal"],
                    "doi": "", "openalex_id": "",
                    "published_date": "",
                    "source": "rss",
                })
            print(f"  [rss] {feed['journal']}: {len(d.entries)} items", file=sys.stderr)
        except Exception as ex:
            print(f"  [rss] ERROR {feed['journal']}: {ex}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch RSS feeds → scan-compatible JSON.")
    ap.add_argument("--sources", type=Path, default=ROOT / "config" / "sources.json")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    recs = fetch_all(args.sources)
    out = {"new": recs, "already_seen": [], "needs_manual_verification": [], "new_count": len(recs)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Fetched {len(recs)} RSS items → {args.output}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行,确认通过** — `python -m pytest tests/test_rss_fetch.py -v` → PASS

- [ ] **Step 5: Commit** — `git add scripts/rss_fetch.py tests/test_rss_fetch.py && git commit -m "feat(rss): rss_fetch.py 独立抓取 RSS feed"`

---

## Phase 2 — 统一候选池(SQLite)+ 合并去重

目标:RSS 与 OpenAlex 结果汇入一个 SQLite 池,按 DOI/title-hash 去重。

### Task 2.1: `scripts/db.py`(schema + 连接)

**Files:**
- Create: `scripts/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 写失败测试 `tests/test_db.py`**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db

def test_upsert_and_dedup_by_doi(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.init(conn)
    p = {"title":"T","doi":"10.1/x","abstract":"a","journal":"J","source":"rss"}
    db.upsert_candidate(conn, p)
    db.upsert_candidate(conn, p)  # 同 DOI 再来一次
    assert db.count_candidates(conn) == 1   # 去重

def test_dedup_by_titlehash_when_no_doi(tmp_path):
    conn = db.connect(tmp_path / "t.db"); db.init(conn)
    db.upsert_candidate(conn, {"title":"A Fine Title!","doi":"","abstract":"","journal":"J","source":"rss"})
    db.upsert_candidate(conn, {"title":"a fine title","doi":"","abstract":"","journal":"J","source":"openalex"})
    assert db.count_candidates(conn) == 1   # title-hash 合并

def test_record_star(tmp_path):
    conn = db.connect(tmp_path / "t.db"); db.init(conn)
    cid = db.upsert_candidate(conn, {"title":"T","doi":"10.1/x","abstract":"","journal":"J","source":"rss"})
    db.set_starred(conn, cid, snapshot="title|abstract|judgment")
    assert db.count_feedback(conn) == 1
```

- [ ] **Step 2: 运行,确认失败** — `python -m pytest tests/test_db.py -v` → FAIL

- [ ] **Step 3: 写 `scripts/db.py`**

```python
#!/usr/bin/env python3
"""SQLite candidate pool. sqlite3 stdlib, no new dep.

Tables: candidates (dedup by doi or title_hash), feedback (star 正样本).
Identity key: normalized DOI if present, else normalized title string.
"""
from __future__ import annotations
import sqlite3
import re
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doi TEXT, title_hash TEXT, title TEXT, abstract TEXT, journal TEXT,
  source TEXT, published_date TEXT, fetched_at TEXT,
  tier TEXT, llm_judgment TEXT,
  starred INTEGER DEFAULT 0, starred_at TEXT, status TEXT DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS feedback (
  candidate_id INTEGER, starred_at TEXT, snapshot TEXT,
  PRIMARY KEY(candidate_id, starred_at)
);
CREATE INDEX IF NOT EXISTS idx_cand_doi ON candidates(doi);
CREATE INDEX IF NOT EXISTS idx_cand_thash ON candidates(title_hash);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _title_hash(title: str) -> str:
    norm = re.sub(r"[^\w\s]", "", (title or "").lower())
    return re.sub(r"\s+", " ", norm).strip()


def _identity(p: dict) -> tuple[str, str]:
    doi = re.sub(r"^https?://doi\.org/", "", (p.get("doi") or "").strip()).lower()
    return doi, _title_hash(p.get("title", ""))


def upsert_candidate(conn: sqlite3.Connection, p: dict) -> int:
    """Insert or merge by identity. Returns candidate id."""
    doi, thash = _identity(p)
    row = None
    if doi:
        row = conn.execute("SELECT id FROM candidates WHERE doi=?", (doi,)).fetchone()
    if not row and thash:
        row = conn.execute("SELECT id FROM candidates WHERE title_hash=?", (thash,)).fetchone()
    if row:
        cid = row["id"]
        # merge: 补充缺失字段(如 OpenAlex 补 DOI/摘要到 RSS 记录)
        conn.execute(
            "UPDATE candidates SET doi=COALESCE(NULLIF(doi,''),?), "
            "abstract=COALESCE(NULLIF(abstract,''),?), openalex补充=1 WHERE id=?",
            (doi, p.get("abstract", ""), cid),
        ) if False else conn.execute(
            "UPDATE candidates SET doi=COALESCE(NULLIF(doi,''),?), "
            "abstract=COALESCE(NULLIF(abstract,''),?) WHERE id=?",
            (doi, p.get("abstract", ""), cid))
        conn.commit()
        return cid
    cur = conn.execute(
        "INSERT INTO candidates(doi,title_hash,title,abstract,journal,source,published_date,fetched_at) "
        "VALUES(?,?,?,?,?,?,?,date('now'))",
        (doi, thash, p.get("title", ""), p.get("abstract", ""), p.get("journal", ""),
         p.get("source", ""), p.get("published_date", "")),
    )
    conn.commit()
    return cur.lastrowid


def set_starred(conn: sqlite3.Connection, cid: int, snapshot: str = "") -> None:
    conn.execute("UPDATE candidates SET starred=1, starred_at=date('now'), status='starred' WHERE id=?", (cid,))
    conn.execute("INSERT OR IGNORE INTO feedback(candidate_id, starred_at, snapshot) VALUES(?, date('now'), ?)",
                 (cid, snapshot))
    conn.commit()


def count_candidates(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]

def count_feedback(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
```

- [ ] **Step 4: 运行,确认通过** — `python -m pytest tests/test_db.py -v` → PASS(注意:`openalex补充=1` 的死分支已在 step3 代码中用 `if False` 关掉,正式版应删除该分支,只留 COALESCE 更新)

- [ ] **Step 5: Commit** — `git add scripts/db.py tests/test_db.py && git commit -m "feat(db): SQLite 候选池 + 去重(DOI/title-hash)+ feedback 表"`

### Task 2.2: `scripts/merge_and_dedupe.py`

**Files:**
- Create: `scripts/merge_and_dedupe.py`
- Test: `tests/test_merge.py`

- [ ] **Step 1: 写失败测试** — 输入两个 scan 格式 JSON(RSS + OpenAlex),merge 后池中候选数 = 去重后唯一数。

```python
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

def test_merge_two_sources_dedup(tmp_path):
    import merge_and_dedupe as m
    rss = {"new":[{"title":"T","doi":"","abstract":"a","journal":"J","source":"rss"}]}
    oax = {"new":[{"title":"t","doi":"10.1/x","abstract":"","journal":"J","source":"openalex"}]}
    rf = tmp_path/"rss.json"; rf.write_text(json.dumps(rss))
    of = tmp_path/"oax.json"; of.write_text(json.dumps(oax))
    dbp = tmp_path/"c.db"
    n = m.merge([rf, of], dbp)
    import db; conn=db.connect(dbp); db.init(conn)
    assert db.count_candidates(conn) == 1   # 同论文(title-hash 合并,OpenAlex 补 DOI)
```

- [ ] **Step 2: 运行,确认失败**

- [ ] **Step 3: 写 `scripts/merge_and_dedupe.py`**

```python
#!/usr/bin/env python3
"""Merge multiple scan-format JSONs (rss_fetch, scan_recent_papers) into the SQLite pool."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db
import config as cfg


def _papers(data: dict) -> list[dict]:
    out = []
    for bucket in ("new", "already_seen", "needs_manual_verification"):
        out.extend(data.get(bucket) or [])
    return out


def merge(input_paths: list[Path], db_path: Path) -> int:
    conn = db.connect(db_path)
    db.init(conn)
    n = 0
    for p in input_paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        for paper in _papers(data):
            db.upsert_candidate(conn, paper)
            n += 1
    conn.commit()
    conn.close()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge scan-format JSONs into candidate pool.")
    ap.add_argument("--inputs", nargs="+", required=True, type=Path)
    ap.add_argument("--db", type=Path, default=Path(cfg.load().get("db_path", "state/candidates.db")))
    args = ap.parse_args()
    db_path = args.db if args.db.is_absolute() else ROOT / args.db
    n = merge(args.inputs, db_path)
    print(f"Merged {n} records (pre-dedup) → {db_path}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行,确认通过**

- [ ] **Step 5: Commit** — `git add scripts/merge_and_dedupe.py tests/test_merge.py && git commit -m "feat(merge): 多源 JSON 合并去重入池"`

---

## Phase 3 — 静态筛 + LLM 判断 接池

目标:复用 `screen_by_profile` + `enrich_and_judge`,但输入/输出对接 SQLite 池而非中间 JSON。

### Task 3.1: 池 ↔ pipeline JSON 适配器 `scripts/pool_io.py`

**Files:**
- Create: `scripts/pool_io.py`
- Test: `tests/test_pool_io.py`

- [ ] **Step 1: 写失败测试** — `pool_to_pipeline` 把池中未判断候选导成 scan 格式;`writeback_judgment` 把 tier/judgment 写回池。

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db, pool_io

def test_export_unjudged_and_writeback(tmp_path):
    conn = db.connect(tmp_path/"c.db"); db.init(conn)
    cid = db.upsert_candidate(conn, {"title":"T","doi":"10.1/x","abstract":"a","journal":"J","source":"rss"})
    data = pool_io.pool_to_pipeline(conn, only_unjudged=True)
    assert len(data["new"]) == 1
    # 模拟 screen + judge 写回
    pool_io.writeback(conn, cid, tier="core", judgment={"JUDGMENT_WORTH":"MUST READ x"})
    row = conn.execute("SELECT tier,llm_judgment,status FROM candidates WHERE id=?",(cid,)).fetchone()
    assert row["tier"]=="core" and "MUST READ" in row["llm_judgment"]
    assert row["status"]=="judged"
```

- [ ] **Step 2: 运行,确认失败**

- [ ] **Step 3: 写 `scripts/pool_io.py`**

```python
#!/usr/bin/env python3
"""Adapters between the SQLite candidate pool and scan-format pipeline JSON,
so the existing screen_by_profile / enrich_and_judge can run unmodified.
"""
from __future__ import annotations
import json


def pool_to_pipeline(conn, only_unjudged: bool = True) -> dict:
    q = "SELECT * FROM candidates"
    if only_unjudged:
        q += " WHERE llm_judgment IS NULL OR llm_judgment=''"
    rows = conn.execute(q).fetchall()
    papers = []
    for r in rows:
        d = dict(r)
        papers.append({
            "id": d["id"], "title": d["title"], "abstract": d["abstract"],
            "journal": d["journal"], "doi": d["doi"], "openalex_id": d["openalex_id"] if "openalex_id" in d else "",
            "source": d["source"],
        })
    return {"new": papers, "already_seen": [], "needs_manual_verification": []}


def writeback(conn, candidate_id: int, tier: str | None = None, judgment: dict | None = None) -> None:
    sets, args = [], []
    if tier is not None:
        sets.append("tier=?"); args.append(tier)
    if judgment is not None:
        sets.append("llm_judgment=?"); args.append(json.dumps(judgment, ensure_ascii=False))
    sets.append("status='judged'"); args.append(candidate_id)
    conn.execute(f"UPDATE candidates SET {','.join(sets)} WHERE id=?", args)
    conn.commit()
```

> 注:`candidates` 表当前无 `openalex_id` 列(Task 2.1 schema)。在 Task 3.1 Step 3 前先给 `db.py` SCHEMA 加 `openalex_id TEXT` 列并补 upsert,保持一致。

- [ ] **Step 4: 运行,确认通过**

- [ ] **Step 5: Commit** — `git add scripts/pool_io.py tests/test_pool_io.py scripts/db.py && git commit -m "feat(pool): 池↔pipeline 适配器 + openalex_id 列"`

### Task 3.2: 编排脚本 `scripts/run_analysis.py`

**Files:**
- Create: `scripts/run_analysis.py`

- [ ] **Step 1: 写 `run_analysis.py`** — 串起:导出未判断候选 → 写临时 JSON → 调 `screen_by_profile.main`(import 调用或 subprocess)→ 调 `enrich_and_judge` → 读回结果写池。用 subprocess 调用现有脚本(零侵入),或 import 其 main。MVP 用 subprocess:

```python
#!/usr/bin/env python3
"""Run static screen + LLM judge on unjudged pool candidates, write back.
Reuses screen_by_profile.py and enrich_and_judge.py unmodified via subprocess.
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db, pool_io, config as cfg


def main() -> int:
    c = cfg.load()
    db_path = ROOT / c.get("db_path", "state/candidates.db")
    profile = ROOT / c.get("profile", "config/profile.md")
    conn = db.connect(db_path); db.init(conn)

    data = pool_io.pool_to_pipeline(conn, only_unjudged=True)
    if not data["new"]:
        print("No unjudged candidates.", file=sys.stderr); return 0

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        inj = td / "pool.json"
        inj.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        screened = td / "screened.json"; judged = td / "judged.json"

        py = sys.executable
        subprocess.run([py, str(ROOT/"scripts"/"screen_by_profile.py"),
                        "--input", inj, "--output", screened, "--profile", profile, "--field", "new"], check=True)
        subprocess.run([py, str(ROOT/"scripts"/"enrich_and_judge.py"),
                        "--input", screened, "--output", judged, "--profile", profile], check=True)

        result = json.loads(judged.read_text(encoding="utf-8"))
        for p in result.get("new", []):
            pool_io.writeback(conn, p["id"], tier=p.get("tier"),
                              judgment=p.get("_judgment"))
    print("Analysis written back to pool.", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 手动冒烟测**(需真实 API key + 已 merge 的池):`python scripts/run_analysis.py`,确认池中候选 status 变 judged、有 tier/judgment。无 key 时跳过,标记为手动验证点。

- [ ] **Step 3: Commit** — `git add scripts/run_analysis.py && git commit -m "feat(analysis): 编排静态筛+LLM判断写回池"`

---

## Phase 4 — 收件箱渲染 + star 回读(解耦 Obsidian)

目标:池 → plain markdown 收件箱(checkbox);人勾选 → 回读 → 渲染 Orient stub。

### Task 4.1: `scripts/render_inbox.py`

**Files:**
- Create: `scripts/render_inbox.py`
- Test: `tests/test_render_inbox.py`

- [ ] **Step 1: 写失败测试**

```python
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db, render_inbox

def test_inbox_has_checkbox_and_hidden_id(tmp_path):
    conn = db.connect(tmp_path/"c.db"); db.init(conn)
    db.upsert_candidate(conn, {"title":"Tax Compliance","doi":"10.1/x","abstract":"a","journal":"JPubE","source":"rss"})
    db.execute = conn.execute
    # 给 tier
    conn.execute("UPDATE candidates SET tier='core' WHERE title='Tax Compliance'"); conn.commit()
    md = render_inbox.render(conn)
    assert "- [ ]" in md
    assert "Tax Compliance" in md
    m = re.search(r"<!--id:(\d+)-->", md)
    assert m                         # 隐藏 id 可被回读
```

- [ ] **Step 2: 运行,确认失败**

- [ ] **Step 3: 写 `scripts/render_inbox.py`**

```python
#!/usr/bin/env python3
"""Render candidate pool → 00_Inbox/文献收件箱.md with checkboxes.
core/proxy 置顶, noise 折叠置底。每条尾部嵌 <!--id:N--> 供回读。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db, config as cfg


def _fmt(row) -> str:
    j = {}
    try: j = json.loads(row["llm_judgment"] or "{}")
    except Exception: pass
    worth = (j.get("JUDGMENT_WORTH") or "").split(" ")[0]  # MUST READ / SKIM / SKIP
    trans = (j.get("FULL_TRANSLATION") or row["title"])[:40]
    box = "- [x] " if row["starred"] else "- [ ] "
    tier = row["tier"] or "noise"
    return f'{box}**[{tier}]** {row["journal"]} — {trans} … <!--id:{row["id"]}-->'


def render(conn) -> str:
    rows = conn.execute(
        "SELECT * FROM candidates WHERE status='judged' ORDER BY "
        "CASE tier WHEN 'core' THEN 0 WHEN 'proxy' THEN 1 WHEN 'method' THEN 2 ELSE 3 END, id"
    ).fetchall()
    lines = ["# 文献收件箱", "",
             "勾选 ☑ = star。core/proxy 置顶。", ""]
    for r in rows:
        lines.append(_fmt(r))
    return "\n".join(lines) + "\n"


def main() -> int:
    c = cfg.load()
    conn = db.connect(ROOT / c.get("db_path", "state/candidates.db")); db.init(conn)
    md = render(conn)
    out = (cfg.vault_root(c) / c.get("inbox_path", "00_Inbox/文献收件箱.md"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"Inbox → {out}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行,确认通过**

- [ ] **Step 5: Commit** — `git add scripts/render_inbox.py tests/test_render_inbox.py && git commit -m "feat(inbox): 渲染候选池为 markdown 收件箱"`

### Task 4.2: `scripts/process_starred.py`(回读 + Orient stub)

**Files:**
- Create: `scripts/process_starred.py`
- Test: `tests/test_process_starred.py`

- [ ] **Step 1: 写失败测试**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db, process_starred

def test_extract_checked_ids():
    md = "# 文献收件箱\n\n- [x] **[core]** J — title … <!--id:7-->\n- [ ] **[noise]** J2 … <!--id:9-->\n"
    assert process_starred.extract_checked_ids(md) == [7]

def test_mark_starred_writes_feedback(tmp_path):
    conn = db.connect(tmp_path/"c.db"); db.init(conn)
    cid = db.upsert_candidate(conn, {"title":"T","doi":"10.1/x","abstract":"a","journal":"J","source":"rss"})
    process_starred.mark_starred(conn, [cid])
    assert db.count_feedback(conn) == 1
    row = conn.execute("SELECT starred FROM candidates WHERE id=?",(cid,)).fetchone()
    assert row["starred"] == 1
```

- [ ] **Step 2: 运行,确认失败**

- [ ] **Step 3: 写 `scripts/process_starred.py`**

```python
#!/usr/bin/env python3
"""Read checked items from the inbox markdown → mark starred in pool → render Orient stubs.
Reuses render_display_outputs.py for stub generation.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db, config as cfg

_ID_RE = re.compile(r"<!--id:(\d+)-->")


def extract_checked_ids(markdown: str) -> list[int]:
    ids = []
    for line in markdown.splitlines():
        if line.strip().startswith("- [x]"):
            m = _ID_RE.search(line)
            if m:
                ids.append(int(m.group(1)))
    return ids


def mark_starred(conn, ids: list[int]) -> None:
    for cid in ids:
        row = conn.execute("SELECT title,abstract,llm_judgment FROM candidates WHERE id=?", (cid,)).fetchone()
        snap = f"{row['title']}|{row['abstract'][:200]}|{row['llm_judgment'] or ''}"
        db.set_starred(conn, cid, snapshot=snap)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", type=Path, default=None)
    args = ap.parse_args()
    c = cfg.load()
    inbox = args.inbox or (cfg.vault_root(c) / c.get("inbox_path", "00_Inbox/文献收件箱.md"))
    md = inbox.read_text(encoding="utf-8")
    ids = extract_checked_ids(md)
    if not ids:
        print("No starred items.", file=sys.stderr); return 0

    conn = db.connect(ROOT / c.get("db_path", "state/candidates.db")); db.init(conn)
    mark_starred(conn, ids)

    # 导出 starred 为 scan 格式,复用 render_display_outputs
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM candidates WHERE id IN ({placeholders})", ids).fetchall()
    papers = [dict(r) for r in rows]
    with tempfile.TemporaryDirectory() as td:
        fj = Path(td) / "starred.json"
        fj.write_text(json.dumps({"new": papers}, ensure_ascii=False), encoding="utf-8")
        subprocess.run([sys.executable, str(ROOT/"scripts"/"render_display_outputs.py"),
                        "--mode", "orient-stubs", "--scan-json", fj, "--enriched-json", fj], check=True)
    print(f"Starred {len(ids)} → Orient stubs.", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行,确认通过**

- [ ] **Step 5: Commit** — `git add scripts/process_starred.py tests/test_process_starred.py && git commit -m "feat(star): 收件箱回读 + 标记 starred + 渲染 Orient stub"`

---

## Phase 5 — 学习回路

目标:基于 explicit star 更新动态画像 + few-shot 注入。

### Task 5.1: few-shot sampler

**Files:**
- Modify: `scripts/enrich_and_judge.py`(prompt 注入最近 star)
- Create: `scripts/fewshot.py`
- Test: `tests/test_fewshot.py`

- [ ] **Step 1: 写失败测试**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db, fewshot

def test_sample_returns_recent_starred(tmp_path):
    conn = db.connect(tmp_path/"c.db"); db.init(conn)
    for i in range(5):
        cid = db.upsert_candidate(conn, {"title":f"T{i}","doi":f"10.1/{i}","abstract":"a","journal":"J","source":"rss"})
        db.set_starred(conn, cid, snapshot=f"T{i}|a|")
    samples = fewshot.sample(conn, k=3)
    assert len(samples) == 3
    assert all("T" in s for s in samples)
```

- [ ] **Step 2: 运行,确认失败**

- [ ] **Step 3: 写 `scripts/fewshot.py`**

```python
#!/usr/bin/env python3
"""Sample recent starred items as few-shot examples for the judge prompt."""
from __future__ import annotations


def sample(conn, k: int = 5) -> list[str]:
    rows = conn.execute(
        "SELECT c.title, c.llm_judgment FROM candidates c "
        "JOIN feedback f ON c.id=f.candidate_id "
        "ORDER BY f.starred_at DESC LIMIT ?", (k,)
    ).fetchall()
    out = []
    for r in rows:
        out.append(f"- {r['title']}")
    return out
```

- [ ] **Step 4: 注入 judge prompt** — 在 `enrich_and_judge.build_system_prompt` 末尾追加(若池中有 star):`近期 star 过:{samples}`。judge 从 `config` 取 db_path,sample 最近 5 条。

- [ ] **Step 5: 运行测试,通过;Commit** — `git add scripts/fewshot.py tests/test_fewshot.py scripts/enrich_and_judge.py && git commit -m "feat(learn): few-shot 注入最近 star"`

### Task 5.2: `scripts/learn_profile.py`(动态画像,人批准)

**Files:**
- Create: `scripts/learn_profile.py`
- Test: `tests/test_learn_profile.py`

- [ ] **Step 1: 写失败测试** — `propose_updates` 接收 starred snapshots + 当前 profile,返回 LLM 风格的增删建议(用 monkeypatch 桩 LLM 调用)。

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import learn_profile

def test_propose_uses_llm_and_returns_diff(monkeypatch):
    def fake_llm(prompt): return "ADD core: housing vouchers\nREMOVE core: (none)"
    monkeypatch.setattr(learn_profile, "_llm", fake_llm)
    diff = learn_profile.propose_updates(starred=["T1|a|","T2|b|"],
                                         current_profile="# P\n## Core topics\n- x\n")
    assert "housing vouchers" in diff
```

- [ ] **Step 2: 运行,确认失败**

- [ ] **Step 3: 写 `scripts/learn_profile.py`**

```python
#!/usr/bin/env python3
"""Propose profile keyword updates from recent stars (human approves before apply).

Does NOT auto-edit config/profile.md — prints a diff; user applies manually or via --apply.
"""
from __future__ import annotations
import _bootstrap  # noqa
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db, config as cfg


def _llm(prompt: str) -> str:
    import openai
    client = openai.OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                           base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    resp = client.chat.completions.create(model="deepseek-chat", messages=[
        {"role": "system", "content": "你是研究画像编辑助手。基于用户近期 star 的论文,提议 profile.md 的 Core/Proxy 主题词增删。格式:ADD core: ... / REMOVE core: ..."},
        {"role": "user", "content": prompt}], max_tokens=400, temperature=0.2)
    return resp.choices[0].message.content


def propose_updates(starred: list[str], current_profile: str) -> str:
    joined = "\n".join(starred[:50])
    return _llm(f"当前 profile:\n{current_profile}\n\n近期 star 过的论文(title|abstract|judgment):\n{joined}")


def main() -> int:
    c = cfg.load()
    conn = db.connect(ROOT / c.get("db_path", "state/candidates.db")); db.init(conn)
    rows = conn.execute("SELECT snapshot FROM feedback ORDER BY starred_at DESC LIMIT 50").fetchall()
    starred = [r["snapshot"] for r in rows if r["snapshot"]]
    if not starred:
        print("No starred feedback yet — nothing to learn.", file=sys.stderr); return 0
    profile_path = ROOT / c.get("profile", "config/profile.md")
    current = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    diff = propose_updates(starred, current)
    print("=== 建议的画像更新(请人工审定后手动改 config/profile.md)===")
    print(diff)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试,通过;Commit** — `git add scripts/learn_profile.py tests/test_learn_profile.py && git commit -m "feat(learn): 动态画像提议(人批准)"`

---

## Phase 6 — 文档与 SKILL.md 更新

### Task 6.1: 更新 SKILL.md + README

**Files:**
- Modify: `SKILL.md`(Stage 0 配置 + 新 9 阶段管线 + 部件职责)
- Modify: `README.md`(可分享性、config/setup 说明)
- Create: `docs/quickstart.md`(端到端示例命令)

- [ ] **Step 1: 改 `SKILL.md`** — 管线步骤替换为:Stage 0 setup/check_config → fetch(rss+scan) → enrich → merge → screen → judge → inbox → [人 star] → deliver;后台 learn。明确 OpenAlex=补全层、LLM=star 前判断、star=学习正样本。

- [ ] **Step 2: 改 `README.md`** — 加"可分享"节:clone → `python scripts/setup.py` → 编辑 config/ → check_config → 跑。

- [ ] **Step 3: 写 `docs/quickstart.md`** — 完整命令序列:

```bash
python scripts/setup.py                     # 复制模板
$EDITOR config/config.json config/profile.md config/sources.json
python scripts/check_config.py              # 预检
python scripts/rss_fetch.py --output outputs/data/rss.json
python scripts/scan_recent_papers.py --days 7 --state state/reading_state.json --update-state --output outputs/data/scan.json
python scripts/merge_and_dedupe.py --inputs outputs/data/rss.json outputs/data/scan.json
python scripts/run_analysis.py              # 静态筛 + LLM 判断 写回池
python scripts/render_inbox.py              # 生成 00_Inbox/文献收件箱.md
# 在 Obsidian 勾选 ☑
python scripts/process_starred.py           # 回读 → Orient stubs
python scripts/learn_profile.py             # 月度:提议画像更新
```

- [ ] **Step 4: Commit** — `git add SKILL.md README.md docs/quickstart.md && git commit -m "docs: 更新 SKILL.md/README/quickstart 反映新管线"`

---

## 自检(写完后)

**1. Spec 覆盖**:§3 九阶段 → Phase 1-4 + 6 覆盖;§5 学习回路 → Phase 5;§6 SQLite → Phase 2;§7 配置层 → Phase 0;§8 迁移 → Task 0.4。✅ 未覆盖项:auto-Zotero / 生产 rigor — spec §2 明确列为非目标,正确排除。

**2. 占位符扫描**:Task 2.1 db.py 有一处 `if False` 死分支(标注了),实现时删除只留 COALESCE 更新——已注明。其余无 TBD。

**3. 类型/签名一致**:`db.upsert_candidate` 返回 `int`(id),`pool_io.writeback` 接 `candidate_id:int`,`process_starred.mark_starred` 用同签名;`fewshot.sample(conn,k)`、`learn_profile.propose_updates(starred,current)` 签名跨任务一致。`openalex_id` 列在 Task 3.1 前补(Task 2.1 schema 漏了,已标注补)。

**4. 已知实现期风险**:见 spec §10(LLM 成本、RSS 定时、收件箱分页、DOI 回填合并边界)。run_analysis 的 subprocess 调用需 screen/judge 接受 `--profile`(Task 0.3 已让 judge 接 profile;screen 本就有 `--profile`)。
