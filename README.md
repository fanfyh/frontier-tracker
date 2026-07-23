# frontier-tracker

文献前沿哨兵 skill —— 自动扫描目标期刊最新论文，LLM 判断研究相关性，生成 Orient 待读队列。

## 结构

| 路径 | 作用 |
|---|---|
| `SKILL.md` | skill 入口（在仓库根） |
| `references/` | 期刊源、筛选规则、研究画像、输出模板 |
| `scripts/` | 抓取 / 富集 / 判断 / 清理脚本（Python） |
| `state/` | 运行态（阅读状态），**gitignore，不分享** |
| `outputs/` | 生成的 stub / 数据，**gitignore，不分享** |
| `.env` | API key，**gitignore，不入库**；见 `.env.example` |

## 安装

```bash
./install.sh          # 软链到 ~/.claude/skills/frontier-tracker
cp .env.example .env  # 填入 API key
```

## 分享须知

可分享的是 `SKILL.md` + `references/` + `scripts/` + `install.sh`。
`state/`、`outputs/`、`.env` 是本机私有运行态，已排除。
