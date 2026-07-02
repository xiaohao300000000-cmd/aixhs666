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
  echo "提示：未找到 MediaCrawler Python，页面仍会打开，但真实采集前需要安装依赖："
  echo "$MEDIACRAWLER_PYTHON"
fi

echo "正在检查数据库并执行迁移..."
if ! "$PYTHON_BIN" -m alembic upgrade head; then
  echo "真实数据库暂不可用，先用本地看板库打开页面。"
  echo "真实采集前请确认 PostgreSQL 已启动并可连接：$DATABASE_URL"
  export DATABASE_URL="sqlite+pysqlite:////tmp/aixhs-dashboard.db"
  "$PYTHON_BIN" - <<'PY'
import storage.models  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from storage.database import Base, engine
from storage.models import Query

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
with SessionLocal() as session:
    if (session.scalar(select(func.count(Query.id))) or 0) == 0:
        session.add(Query(query_text="KET PET 二刷", platform="xhs", query_type="seed", status="active", priority=100, source="dashboard_default"))
        session.commit()
PY
fi

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
if [ "$WORKER_ADAPTER" = "mediacrawler" ] && [ ! -x "$MEDIACRAWLER_PYTHON" ]; then
  echo "真实采集依赖未安装。安装命令："
  echo "python3.12 -m venv third_party/MediaCrawler/.venv"
  echo "third_party/MediaCrawler/.venv/bin/pip install -r third_party/MediaCrawler/requirements.txt"
  echo "python -m scripts.mediacrawler_login"
fi
echo "服务日志：$LOG_FILE"
echo "关闭服务可执行：kill \$(cat $LOG_DIR/dashboard.pid)"
echo ""
