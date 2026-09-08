#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS_DIR="$ROOT_DIR/.local/pids"

stop_pid_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local pid
    pid="$(cat "$file")"
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$file"
  fi
}

stop_pid_file "$PIDS_DIR/backend.pid"
stop_pid_file "$PIDS_DIR/mlflow.pid"
stop_pid_file "$PIDS_DIR/clickhouse.pid"

pkill -f "uvicorn main:app" >/dev/null 2>&1 || true
pkill -f "mlflow server --host 127.0.0.1" >/dev/null 2>&1 || true
pkill -f "clickhouse server" >/dev/null 2>&1 || true
pkill -f "clickhouse.*8123" >/dev/null 2>&1 || true
