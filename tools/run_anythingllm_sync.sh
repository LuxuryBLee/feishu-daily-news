#!/bin/bash
# 每天自动：拉取 GitHub 最新档案 → 同步进 AnythingLLM
# 在 Mac 上配合 cron/launchd 使用（见 docs/SECOND_BRAIN_ANYTHINGLLM.md）

set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

# 加载密钥（建议把下面三个变量写进 tools/.anythingllm.env）
if [ -f tools/.anythingllm.env ]; then
  set -a; source tools/.anythingllm.env; set +a
fi

echo "[$(date '+%Y-%m-%d %H:%M')] 拉取最新档案…"
git pull --quiet || echo "⚠️ git pull 失败，使用本地现有档案。"

echo "[$(date '+%Y-%m-%d %H:%M')] 同步到 AnythingLLM…"
python3 tools/sync_to_anythingllm.py
