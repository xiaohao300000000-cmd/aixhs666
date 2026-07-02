#!/bin/zsh
set -e

PROJECT_DIR="/Users/xiaohao30000/aixhs666"
PORT="${AIXHS_DASHBOARD_PORT:-8017}"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
MEDIACRAWLER_PYTHON="$PROJECT_DIR/third_party/MediaCrawler/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/.runtime"
LOG_FILE="$LOG_DIR/dashboard.log"

cd "$PROJECT_DIR"
mkdir -p "$LOG_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "未找到 Python 虚拟环境：$PYTHON_BIN"
  echo "请先在项目目录执行：python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  read "?按回车退出..."
  exit 1
fi

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://education_demand:change_me@localhost:5432/education_demand}"
export WORKER_ADAPTER="${WORKER_ADAPTER:-mediacrawler}"
export OPS_TOKEN="${OPS_TOKEN:-secret}"

if [ "$WORKER_ADAPTER" = "mediacrawler" ] && [ ! -x "$MEDIACRAWLER_PYTHON" ]; then
  echo "当前已切换为真实采集模式，但未找到 MediaCrawler Python："
  echo "$MEDIACRAWLER_PYTHON"
  echo ""
  echo "请先安装真实采集依赖："
  echo "python3.12 -m venv third_party/MediaCrawler/.venv"
  echo "third_party/MediaCrawler/.venv/bin/pip install -r third_party/MediaCrawler/requirements.txt"
  echo "python -m scripts.mediacrawler_login"
  echo ""
  read "?按回车退出..."
  exit 1
fi

echo "正在检查真实数据库并执行迁移..."
"$PYTHON_BIN" -m alembic upgrade head

if [ -f "$LOG_DIR/dashboard.pid" ]; then
  OLD_PID="$(cat "$LOG_DIR/dashboard.pid")"
  if kill -0 "$OLD_PID" >/dev/null 2>&1; then
    echo "正在停止旧的看板服务：$OLD_PID"
    kill "$OLD_PID" >/dev/null 2>&1 || true
    sleep 1
  fi
fi

if ! lsof -iTCP:"$PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "正在启动 AIXHS 真实看板服务：http://127.0.0.1:$PORT/ops"
  nohup "$PYTHON_BIN" -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$PORT" > "$LOG_FILE" 2>&1 &
  echo $! > "$LOG_DIR/dashboard.pid"
  sleep 2
else
  echo "AIXHS 看板服务已经在运行：http://127.0.0.1:$PORT/ops"
fi

open "http://127.0.0.1:$PORT/ops"

echo ""
echo "看板已打开。页面右上角 OPS_TOKEN 输入：$OPS_TOKEN"
echo "当前采集模式：$WORKER_ADAPTER"
echo "当前数据库：$DATABASE_URL"
echo "服务日志：$LOG_FILE"
echo "关闭服务可执行：kill \$(cat $LOG_DIR/dashboard.pid)"
echo ""
