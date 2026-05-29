#!/bin/bash
# 第二大脑启动脚本（Mac mini）
# 用法：./second_brain/deploy/run.sh [feishu|web]   默认 feishu
# 它会：①拉取最新知识库档案 ②加载 .env ③启动对应服务

set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # 仓库根目录
cd "$HERE"

# ① 拉取 GitHub Actions 每天提交的新档案（失败不阻断）
git pull --quiet || echo "⚠️ git pull 失败，使用本地现有档案继续。"

# ② 加载密钥
if [ -f second_brain/.env ]; then
  set -a; source second_brain/.env; set +a
else
  echo "❌ 未找到 second_brain/.env，请先 cp second_brain/.env.example second_brain/.env 并填写。"
  exit 1
fi

# ③ 启动
MODE="${1:-feishu}"
if [ "$MODE" = "web" ]; then
  echo "🌐 启动网页版第二大脑…"
  exec python3 second_brain/webapp.py
else
  echo "💬 启动飞书第二大脑（长连接）…"
  exec python3 second_brain/feishu_bot.py
fi
