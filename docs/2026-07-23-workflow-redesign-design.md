# Frontier Tracker 工作流重构设计

> 日期：2026-07-23
> 状态：设计已锁定，待实现
> 基准：以现有 frontier-tracker（Python）为底座重构，不照搬 PaperEcho 的 JS 代码，只移植设计思路。

## 1. 背景与问题

当前文献入口有**两套并行系统扫几乎同一批顶刊**，都喂 `01_Research/01_Orient/`：

| | RSS-Orient 管线 | frontier-tracker |
|---|---|---|
| 源 | 15 顶刊 RSS | OpenAlex 扫 13 期刊 + NBER（高度重叠） |
| 判断 | 人工 star（高精度、当天） | LLM 6 维 + 静态画像筛选（自动、几天滞后） |
| 依赖 | **焊死在 Obsidian RSS Dashboard 插件**（脚本读插件 `data.json`） | 独立 Python，零 Obsidian 依赖 |

三个问题：
1. **冗余**：两套扫同一批刊，走不同判断，撞同一个出口。
2. **焊死**：RSS 轨依赖 Obsidian 插件（须开 Obsidian、插件正常、`data.json` 格式稳定），可移植性差。
3. **不学习**：静态画像不会随口味进化；LLM 判断不吸收 star 反馈。

## 2. 目标 / 非目标

**目标（本期交付）**
- 统一候选池：RSS + OpenAlex + NBER 单池去重，不再双系统并行。
- 解耦 Obsidian：独立抓 RSS，star 行为保留（plain markdown 收件箱），插件可退役、引擎不依赖。
- LLM 辅助判断：star **之前**对全池（静态筛后）跑 LLM，给翻译 + 分级 + 建议。
- 学习回路：基于 explicit star 更新动态画像 + few-shot 注入，判断随口味进化。
- 配置层：抽出一切个人元素到 `config/`，仓库只发模板，可复制可分享。

**非目标（后期可选，本期不做）**
- 自动写回 Zotero（Read 后自动入库）。
- 生产化 rigor：确定性 runner、邮件通知、留存策略升级（保留现有 `cleanup_outputs.py`）。
- 扩源到 PubMed/PMC（经济学暂不需要）。
- A/B/C/D 分级（沿用现有 tier/priority）。
- PaperEcho JS 代码移植。

## 3. 目标工作流

```
Stage 0  CONFIGURE   setup / check_config —— 首次配置 + 预检（API key / 画像 / 期刊 / vault 路径）
Stage 1  FETCH       rss_fetch.py【新】 + scan_recent_papers.py【复用】
                     → 各源输出统一格式候选
Stage 2  ENRICH      enrich_abstracts.py【复用】（OpenAlex/Crossref/S2/Elsevier 补摘要+DOI）
Stage 3  MERGE       merge_and_dedupe.py【新】→ 统一候选池（去重，DOI 主键，title-hash 回退）
Stage 4  SCREEN      screen_by_profile.py【复用】静态关键词 → tier(core/proxy/method/noise)
Stage 5  JUDGE       enrich_and_judge.py【复用】对 non-noise 跑 LLM → 翻译+6维+建议
Stage 6  INBOX       render_inbox.py【新】→ 00_Inbox/文献收件箱.md（☐ + 期刊 + tier + LLM建议 + 摘要）
                     noise 项折叠/置底不删（保留复核权），core/proxy 项置顶
Stage 7  STAR        人在 Obsidian 勾选 ☐ = star（保留此行为）
Stage 8  DELIVER     process_starred.py【新】回读 ☑ → render_display_outputs.py【复用】→ 01_Orient/ stub
                     → 人工 Read/Skip

后台    LEARN        learn_profile.py【新】定期复盘 star → 提议画像更新（人批准）
                     few-shot sampler【新】判断时注入最近 star 示例
```

## 4. 部件职责

| 部件 | 职责 | 是否冗余 |
|---|---|---|
| RSS | 发现源（最快、覆盖顶刊） | 否 |
| OpenAlex | **补全层**：给 RSS 的裸 title 补摘要/DOI；Elsevier/ScienceDirect RSS 无摘要尤其靠它 | 否 |
| 静态画像筛 | 砍明显 noise，省 LLM 成本，给收件箱当 tier 标签 | 否 |
| LLM | star 前判断（翻译+相关性+建议），且基于 star 历史学习 | 否 |
| 人的 star | 主把关 + **学习正样本**（ground truth） | 否 |
| Orient stub | 交付 | 否 |

**关键澄清**：OpenAlex 不是发现源（那是 RSS 的活），是补全层——没有它，Elsevier 系论文 LLM 无摘要可判。

## 5. 学习回路

学习信号：**仅 explicit star 作正样本；未 star 不当负样本**（"没 star"可能只是还没看，不等于 reject，避免噪音）。

两条机制（无需 fine-tune）：

1. **动态画像**：`learn_profile.py` 定期（如每月 / on-demand）读最近 star 反馈，让 LLM 提议 `config/profile.md` 的 core/proxy/method 主题词增删 → **人批准后**落盘。画像随口味进化，取代当前静态 `fanfy-housing-fiscal.md`。
2. **Few-shot 注入**：Stage 5 判断时，sampler 取最近 K 条（如 5）star 论文（title + 为何相关）塞进 prompt，LLM 照口味判。

star 越多 → 画像越准、few-shot 越对味。

## 6. 数据模型

候选池用 **SQLite**（`sqlite3` 标准库，无新依赖；比单 JSON 更适合去重 + 反馈累积，避免重蹈插件 835KB `data.json` 覆辙）。

**`candidates` 表**
- `id`：内部主键
- `doi`（可空）、`title_hash`：身份键
- `title`, `abstract`, `journal`, `published_date`, `source`(rss/openalex/nber), `source_ref`
- `fetched_at`, `tier`(static), `keywords_hit`
- `llm_judgment`(JSON: translation/relevance/recommendation/dimensions)
- `starred`(bool), `starred_at`, `status`(new/enriched/judged/starred/delivered/skipped)

**`feedback` 表**（学习专用）
- `candidate_id`, `starred`, `starred_at`, `snapshot`(star 时刻的 title+abstract+judgment)

**身份 / 去重键**：归一化 DOI 为主键；RSS 项常无 DOI → 先用归一化 title hash，Stage 2 OpenAlex 补出 DOI 后提升为 DOI 身份并合并。

## 7. 配置层与可分享性

原则：**个人的一切进 `config/`，仓库只发模板，真实配置 gitignore。**

| 个人元素 | 现位置 | 改成 |
|---|---|---|
| 研究画像（主题词） | `references/fanfy-housing-fiscal.md` | `config/profile.md` + `profile.example.md` |
| 目标期刊（RSS feed + OpenAlex ID） | 散在 scan 脚本 / 画像 | `config/sources.json` |
| API keys | `.env` | `.env`（保留）+ `.env.example` |
| 输出 vault 根 | 硬编码 `~/Documents/marginal-notes` | `config.json` |
| Orient 输出目录 | 硬编码 | `config.json` |
| 阅读容量（6/周） | 画像 | `config.json` |

**首次运行配置（Stage 0）**：
- `setup`（或扩展现有 `check_config.py`）：复制模板 → 引导填空（画像/期刊/key/vault 路径）→ 校验全过才放行。
- SKILL.md 列为 Stage 0 前置，对标 policy-report 首问 `project_root` 的套路。
- 参照 PaperEcho `config/README.md` + `paperecho-setup-template.md`（搬思路）。

`.gitignore` 追加：`config.json`、`config/profile.md`、`*.db`（候选池）、`.env`（已有）。

## 8. 复用 vs 新建（印证"以 frontier-tracker 为基准"）

**复用 5 个**：`scan_recent_papers` / `enrich_abstracts` / `screen_by_profile` / `enrich_and_judge` / `render_display_outputs`（+ `cleanup_outputs` 留存）。
**新建 6 个**：`rss_fetch` / `merge_and_dedupe` / `render_inbox` / `process_starred` / `learn_profile` / few-shot sampler（外加 setup/check_config 扩展）。
**退役**：RSS Dashboard 插件（fetch 角色被 `rss_fetch` 取代，star 行为由 markdown 收件箱保留）+ `rss_to_orient.py`（被 `process_starred` 取代）。

> 现有 frontier-tracker 的 `_archived/` 旧脚本不参与，维持现状。

## 9. SKILL.md 更新点

- Stage 0 前置配置说明。
- 管线步骤从"7 步线性"改为"fetch→enrich→merge→screen→judge→inbox→[人star]→deliver + 后台 learn"。
- 明确 OpenAlex = 补全层、LLM = star 前判断、star = 学习正样本。

## 10. 未决 / 风险

- **LLM 成本**：star 前对全 non-noise 池跑 LLM，可能每周数百次调用。静态筛要够狠地砍 noise。可加"仅 tier∈{core,proxy} 才进 LLM"的开关。
- **RSS 抓取频率**：独立 `feedparser` 需定时触发（cron 或手动）；插件原先在 Obsidian 内自动刷新。
- **收件箱膨胀**：每周数百条需分页 / 按期刊折叠；`render_inbox` 要设计成可读。
- **DOI 回填合并**：title-hash → DOI 提升时若发生重复需干净合并，边界要测。

## 11. 范围边界（重申）

本期核心 = 统一源 + 学习回路 + 配置层。auto-Zotero、生产化 rigor、扩源、A/B/C/D 分级、PaperEcho JS 移植均列为后期可选，不在本 spec。
