#!/usr/bin/env bash
# FLUX Studio 服务器部署脚本
# 用法(在服务器上、仓库根目录):
#   ./scripts/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

# 1. 必须有 .env
if [[ ! -f .env ]]; then
  echo "✗ 缺少 .env —— 请先 cp .env.example .env 并按服务器改好(MODEL_API_URL 等)"
  exit 1
fi

# 2. 必须配置 MODEL_API_URL(指向自管的 GPU 模型服务,见 .env.example 说明)
source .env
if [[ -z "${MODEL_API_URL:-}" ]]; then
  echo "✗ .env 缺少 MODEL_API_URL —— 它指向你单独部署的 GPU 模型服务(model-api/app.py,例如 http://192.168.1.50:8000)"
  exit 1
fi

echo "→ 拉取镜像 + 构建..."
docker compose build

echo "→ 启动全部服务(含 worker)..."
docker compose up -d

FRONTEND_PORT="${FRONTEND_PORT:-8080}"
BACKEND_PORT_RAW="${BACKEND_PORT:-127.0.0.1:8081}"
# 去掉可能的 127.0.0.1: 前缀,只保留端口号用于显示
BACKEND_PORT_SHOW="${BACKEND_PORT_RAW##*:}"

echo
echo "✓ 完成。状态:"
docker compose ps
echo
echo "前端: http://<服务器IP>:${FRONTEND_PORT}"
echo "API : http://<服务器IP>:${BACKEND_PORT_SHOW}/docs   (若绑了 127.0.0.1 则仅本机可访问,用 SSH 隧道)"
echo "GPU 模型服务: ${MODEL_API_URL}   (由你另行部署,不在此 compose 中)"