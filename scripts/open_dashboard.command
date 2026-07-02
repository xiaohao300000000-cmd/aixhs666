#!/bin/zsh
set -e

PROJECT_DIR="/Users/xiaohao30000/aixhs666"
PORT="${AIXHS_DASHBOARD_PORT:-8017}"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
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

export DATABASE_URL="${DATABASE_URL:-sqlite+pysqlite:////tmp/aixhs-dashboard.db}"
export WORKER_ADAPTER="${WORKER_ADAPTER:-mock}"
export OPS_TOKEN="${OPS_TOKEN:-secret}"

"$PYTHON_BIN" - <<'PY'
import storage.models  # noqa: F401
from sqlalchemy import select, func
from storage.database import Base, engine
from storage.models import Query
from sqlalchemy.orm import sessionmaker

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
with SessionLocal() as session:
    query_count = session.scalar(select(func.count(Query.id))) or 0
    if query_count == 0:
        session.add(
            Query(
                query_text="admissions",
                platform="xhs",
                query_type="seed",
                status="active",
                priority=100,
                source="dashboard_demo",
            )
        )
        session.commit()
PY

if ! lsof -iTCP:"$PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "正在启动 AIXHS 看板服务：http://127.0.0.1:$PORT/ops"
  nohup "$PYTHON_BIN" -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$PORT" > "$LOG_FILE" 2>&1 &
  echo $! > "$LOG_DIR/dashboard.pid"
  sleep 2
else
  echo "AIXHS 看板服务已经在运行：http://127.0.0.1:$PORT/ops"
fi

open "http://127.0.0.1:$PORT/ops"

echo ""
echo "看板已打开。页面右上角 OPS_TOKEN 输入：$OPS_TOKEN"
echo "服务日志：$LOG_FILE"
echo "关闭服务可执行：kill \$(cat $LOG_DIR/dashboard.pid)"
echo ""
