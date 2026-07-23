#!/usr/bin/env bash
# frontier-tracker skill 安装脚本 —— 软链到 ~/.claude/skills/
# SKILL.md 在仓库根，故软链目标是仓库根本身。
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SKILLS_DIR="$CLAUDE_DIR/skills"

mkdir -p "$SKILLS_DIR"
ln -sfn "$REPO" "$SKILLS_DIR/frontier-tracker"

echo "✓ frontier-tracker skill installed."
echo "  skill: $SKILLS_DIR/frontier-tracker -> $REPO"
echo
echo "注意："
echo "  - 首次使用前复制 .env.example 为 .env 并填入 API key（.env 已 gitignore，不入库）。"
echo "  - state/ 与 outputs/ 是运行态，已 gitignore，不随仓库分享。"
echo "卸载：删除 $SKILLS_DIR/frontier-tracker 软链即可。"
