---
name: frontier-tracker
description: 文献前沿哨兵 — 自动扫描目标期刊最新论文，LLM 判断研究相关性，生成 Orient 待读队列。触发：扫描文献、追踪前沿、更新待读队列。
---

# Frontier Tracker

个人文献哨兵系统，自动监控公共经济学 / 城市经济学 / 住房政策领域前沿论文。

## 在 Marginal Notes 管线中的位置

```
Frontier Tracker    →    01_Orient/    →    你的判断    →    Zotero    →    02_Zotero/         →    04_Distill/
  自动扫描+筛选            stub 文件           Read/Skip        手动添加         reading-guide 导读      提炼 claim
```

## 管线步骤

每次运行按以下顺序执行：

### 0. check — 预检配置（不调 API、不花配额）

```bash
python scripts/check_config.py
```

验证 API key（`.env` 或环境）、Python 依赖、运行路径是否齐全。改了画像/换 key 后先跑这个，确认 0 失败再进入正式流程。所有必需项通过返回 exit 0，缺项时清晰列出该补什么。

### 1. scan — 扫描目标期刊

```bash
python scripts/scan_recent_papers.py \
  --days 7 \
  --state state/reading_state.json \
  --update-state \
  --output outputs/data/frontier_scan_$(date +%Y%m%d).json
```

**注意**：`--update-state` 必须传，否则 `seen` 集不会增长，下次扫描会把同一批论文当作 new 再处理一遍。

### 2. enrich — 补全摘要

```bash
python scripts/enrich_abstracts.py \
  --input outputs/data/frontier_scan_$(date +%Y%m%d).json \
  --output outputs/data/frontier_enriched_$(date +%Y%m%d).json \
  --field both
```

`--field both` 同时处理 `new` 和 `already_seen` 两个桶。

### 3. judge — DeepSeek LLM 翻译 + 相关性判断

```bash
python scripts/enrich_and_judge.py \
  --input outputs/data/frontier_enriched_$(date +%Y%m%d).json \
  --output outputs/data/frontier_judged_$(date +%Y%m%d).json
```

`DEEPSEEK_API_KEY` 和 `DEEPSEEK_BASE_URL` 从 `.env` 自动读取，无需在命令行传 `--api-key`/`--base-url`（仍可用 CLI 参数覆盖）。

LLM 输出六维判断：直接关联、间接关联、核心方法、数据来源、核心发现、阅读建议（MUST READ / SKIM / SKIP）。

### 4. screen — 按研究画像筛分

```bash
python scripts/screen_by_profile.py \
  --input outputs/data/frontier_judged_$(date +%Y%m%d).json \
  --profile references/fanfy-housing-fiscal.md \
  --output outputs/data/frontier_screened_$(date +%Y%m%d).json \
  --field both
```

研究画像 `fanfy-housing-fiscal.md` 定义四节：Core topics、Proxy topics、Methods、Exclusion topics。Exclusion 命中直接判 noise；core 命中 → tier=core/priority=P1；proxy 命中 → tier=proxy/P2；method 命中 ≥2 → tier=method/P2；其它 → tier=noise/P3。

### 5. render — 生成 Orient stub 文件

```bash
python scripts/render_display_outputs.py \
  --mode orient-stubs \
  --scan-json outputs/data/frontier_screened_$(date +%Y%m%d).json \
  --enriched-json outputs/data/frontier_judged_$(date +%Y%m%d).json
```

输出：`01_Research/01_Orient/YYYY-MM-DD_keyword.md`，外加 `_skipped_YYYY-MM-DD.md` 汇总被筛掉的论文（方便复核分类是否准确）。

每个 stub 文件内容：
- **Frontmatter**：title, authors, year, journal, doi, priority, class, relevance, status, date_added, tags
- **Abstract**：论文摘要（优先中文翻译，回退英文）
- **为什么值得读**：LLM 六维判断概要
- **Decision**：Read / Skip / Watch checkbox

**MUST READ 覆盖**：即便筛分判为 noise/skip，如果 LLM 给出 `MUST READ`，stub 仍会生成。

## 下一步：从 Orient 到 Distill

Frontier Tracker 产出 Orient stub 后，人工流程启动：

1. 打开 `01_Research/01_Orient/`，浏览 stub 文件（`_skipped_*.md` 用来抽检筛分质量）
2. 决定要读的：勾选 Read，将该论文添加到 Zotero
3. 在 Zotero 中阅读，用 reading-guide skill 生成导读到 `01_Research/02_Zotero/`
4. 在导读"我的笔记"和"核心收获"区填入理解
5. 提炼 claim 到 `01_Research/04_Distill/`（根下直接建文件，不嵌套子目录）

## 研究画像

当前使用的画像文件：`references/fanfy-housing-fiscal.md`

核心领域：保障房、住房补贴、技能错配、财政竞争、人口流动。

目标期刊：JPubE、JUE、JoLE、AEJ:Policy、REStat、JDE、EER、JEG、JCE、JHE、Land Econ、REE、JRS 共 13 种，加 NBER。

每周阅读容量：6 篇。

## 脚本参考

| 脚本 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `check_config.py` | 预检配置（key/依赖/路径，不调 API） | `.env` + 环境 | 终端报告，exit 0/1 |
| `scan_recent_papers.py` | 扫描期刊最新论文 | state JSON | scan JSON |
| `enrich_abstracts.py` | 补全缺失摘要 | scan JSON | enriched JSON |
| `enrich_and_judge.py` | DeepSeek LLM 翻译+判断 | enriched JSON | judged JSON (含 `_judgment`) |
| `screen_by_profile.py` | 按研究画像分类 | judged JSON | screened JSON (含 `tier`/`priority`/`relevance`/`status`) |
| `render_display_outputs.py` | 渲染为 Orient stub / Excel / Web app / Codex 预览 | scan/state JSON | .md / .xlsx / .html |
| `cleanup_outputs.py` | 删除过期中间 JSON（默认 30 天） | outputs/data | 删除计数 |

`_bootstrap.py`（加载 `.env`）和 `build_top_family_watchlist.py`（重建 watchlist）是辅助脚本，不在主流程命令里。`_archived/` 下的脚本属于旧管线遗产，不参与当前流程。

可用 `--mode` 值：`orient-stubs`（vault 主用途）、`excel`、`app`、`codex`。`_archived/` 下的脚本（`match_zotero.py`、`sync_obsidian.py`、`write_feishu.py`、`cross_ref_zotero.py`）属于旧管线遗产，不参与当前流程。

## 依赖

- Python 3.9+，包：`openpyxl`、`openai`、`pyalex`、`python-dotenv`
- **API key 全部集中在 `.env`**（已 gitignore，模板见 `.env.example`）。所有脚本通过 `scripts/_bootstrap.py` 在启动时加载 `.env`，无需手动 `export`。shell/环境里已有的变量优先级高于 `.env`。
  - `OPENALEX_API_KEY` — 必需。OpenAlex 自 2026-02-13 起需要 key 才有完整配额（<https://openalex.org/settings/api>）
  - `DEEPSEEK_API_KEY` — 必需（LLM judge），`DEEPSEEK_BASE_URL` 可选（默认官方端点）
  - `ELSEVIER_API_KEY` + `ELSEVIER_INSTTOKEN` — 可选，仅用于补全新发 Elsevier 期刊（JUE/JPubE/JHE/JDE/EER/JEEM/JIE）摘要
- **Elsevier 说明**：OpenAlex/Crossref/S2 对新发 Elsevier 论文几乎拿不到摘要，必须走 Elsevier 自家接口。免费学术 key 在 <https://dev.elsevier.com/> 注册；**仅 API Key 只能拿到 title，必须再申请机构 insttoken**（联系 CUFE 图书馆电子资源部）。替代方案：从 CUFE 校园 IP 或校园 VPN 内调用，IP-based 鉴权也能返回摘要。两者都没有时 enrich 会自动跳过 Elsevier 这一步。
- 配置是否齐全用 `python scripts/check_config.py` 一键预检（见步骤 0）。

> Crossref / Semantic Scholar 仍是公共访问、无需 key；只有 OpenAlex 需要。

## 定期运行

建议每周运行一次（扫描最近 7 天）。首轮建议扫描 30 天以建立基准：

```bash
# 首轮（建立基准）
python scripts/scan_recent_papers.py --days 30 --state state/reading_state.json --update-state --output outputs/data/frontier_scan_$(date +%Y%m%d).json

# 后续每周
python scripts/scan_recent_papers.py --days 7 --state state/reading_state.json --update-state --output outputs/data/frontier_scan_$(date +%Y%m%d).json
```

### 清理过期中间文件

`outputs/data/` 会无限堆积每次运行的 JSON（scan/enriched/judged/screened）。定期删掉过期的：

```bash
# 先 dry-run 看会删什么（不真删）
python scripts/cleanup_outputs.py --dry-run

# 确认后删除 30 天前的文件（默认窗口）
python scripts/cleanup_outputs.py

# 或自定义保留窗口，如只留最近 14 天
python scripts/cleanup_outputs.py --days 14
```

只删 `outputs/data/` 下的过期 `.json`，不碰 `state/`、`references/`、vault。
