#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_DIR="$ROOT_DIR/.local"
PIDS_DIR="$LOCAL_DIR/pids"
LOGS_DIR="$LOCAL_DIR/logs"
CLICKHOUSE_DIR="$LOCAL_DIR/clickhouse"

BACKEND_PORT="${BACKEND_PORT:-8000}"
MLFLOW_PORT="${MLFLOW_PORT:-5001}"
CLICKHOUSE_HTTP_PORT="${CLICKHOUSE_HTTP_PORT:-8123}"
CLICKHOUSE_TCP_PORT="${CLICKHOUSE_TCP_PORT:-9000}"

mkdir -p \
  "$PIDS_DIR" \
  "$LOGS_DIR" \
  "$CLICKHOUSE_DIR/data" \
  "$CLICKHOUSE_DIR/tmp" \
  "$CLICKHOUSE_DIR/user_files" \
  "$CLICKHOUSE_DIR/format_schemas"

wait_for_http() {
  local url="$1"
  local label="$2"
  for _ in $(seq 1 30); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$label is ready"
      return 0
    fi
    sleep 1
  done
  echo "$label failed to start" >&2
  return 1
}

wait_for_clickhouse() {
  for _ in $(seq 1 30); do
    if clickhouse client --host 127.0.0.1 --port "$CLICKHOUSE_TCP_PORT" --query "SELECT 1" >/dev/null 2>&1; then
      echo "ClickHouse is ready"
      return 0
    fi
    sleep 1
  done
  echo "ClickHouse failed to start" >&2
  return 1
}

start_clickhouse() {
  if clickhouse client --host 127.0.0.1 --port "$CLICKHOUSE_TCP_PORT" --query "SELECT 1" >/dev/null 2>&1; then
    echo "ClickHouse already running"
    return 0
  fi

  clickhouse server --daemon \
    --pidfile="$PIDS_DIR/clickhouse.pid" \
    --log-file="$LOGS_DIR/clickhouse.out.log" \
    --errorlog-file="$LOGS_DIR/clickhouse.err.log" \
    -- \
    --path="$CLICKHOUSE_DIR/data" \
    --tmp_path="$CLICKHOUSE_DIR/tmp" \
    --user_files_path="$CLICKHOUSE_DIR/user_files" \
    --format_schema_path="$CLICKHOUSE_DIR/format_schemas" \
    --http_port="$CLICKHOUSE_HTTP_PORT" \
    --tcp_port="$CLICKHOUSE_TCP_PORT"
  wait_for_clickhouse
}

start_mlflow() {
  if curl -fsS "http://127.0.0.1:$MLFLOW_PORT" >/dev/null 2>&1; then
    echo "MLflow already running"
    return 0
  fi

  python3 "$ROOT_DIR/scripts/launch_detached.py" \
    "$PIDS_DIR/mlflow.pid" \
    "$LOGS_DIR/mlflow.log" \
    bash -lc "cd \"$ROOT_DIR\" && exec uv run mlflow server --host 127.0.0.1 --port \"$MLFLOW_PORT\" --backend-store-uri \"sqlite:///$ROOT_DIR/mlflow.db\" --default-artifact-root \"$ROOT_DIR/mlruns\"" >/dev/null
  wait_for_http "http://127.0.0.1:$MLFLOW_PORT" "MLflow"
}

build_frontend() {
  (cd "$ROOT_DIR/frontend" && npm run build >/dev/null)
  echo "Frontend build is ready"
}

start_backend() {
  if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/platform/control-tower" >/dev/null 2>&1; then
    echo "Backend already running"
    return 0
  fi

  python3 "$ROOT_DIR/scripts/launch_detached.py" \
    "$PIDS_DIR/backend.pid" \
    "$LOGS_DIR/backend.log" \
    bash -lc "cd \"$ROOT_DIR\" && exec env PYTHONPATH=\"$ROOT_DIR/src\" uv run python -m uvicorn main:app --app-dir \"$ROOT_DIR/src\" --host 127.0.0.1 --port \"$BACKEND_PORT\"" >/dev/null
  wait_for_http "http://127.0.0.1:$BACKEND_PORT/api/platform/control-tower" "Backend"
}

start_clickhouse
start_mlflow
build_frontend
start_backend

echo
echo "Demo stack is ready:"
echo "App: http://127.0.0.1:$BACKEND_PORT"
echo "MLflow: http://127.0.0.1:$MLFLOW_PORT"
echo "ClickHouse HTTP: http://127.0.0.1:$CLICKHOUSE_HTTP_PORT"
echo "ClickHouse TCP: 127.0.0.1:$CLICKHOUSE_TCP_PORT"
