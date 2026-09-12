#!/usr/bin/env bash
#
# 一条命令拉起后端 :5000 与前端 :5173（P0-A1）。
#
#   bash scripts/dev.sh              # Git Bash / macOS / Linux
#   BACKEND_PORT=5001 bash scripts/dev.sh
#
# Windows 上用 PowerShell 的等价入口：.\scripts\dev.ps1
# 没装 GNU Make 也能验收 —— accept_p0.py 不依赖本脚本。
#
# 按 Ctrl+C 会同时停掉两个服务（Windows 下走 taskkill /T 杀进程树，
# 否则 flask / node 的孙进程会留着占端口，下次启动报「端口已被占用」）。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BACKEND_PORT="${BACKEND_PORT:-5000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# --- 前置检查：缺什么就直说，别让它快到一半才炸 ---

PYTHON=""
for candidate in "$BACKEND/.venv/Scripts/python.exe" "$BACKEND/.venv/bin/python"; do
  if [ -x "$candidate" ]; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "找不到虚拟环境：$BACKEND/.venv" >&2
  echo "先按 README「5 分钟上手」建好：python -m venv backend/.venv" >&2
  exit 1
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "找不到前端依赖：$FRONTEND/node_modules" >&2
  echo "先在 frontend/ 下执行：npm install" >&2
  exit 1
fi

if [ ! -f "$BACKEND/.env" ]; then
  # 不退出：没有 .env 也能起来（走 Mock Provider），但要不要配 Key 得用户知道
  echo "提示：backend/.env 还不存在，现在跑的是 Mock Provider（无真实模型能力）"
  echo "      照 backend/.env.example 建一个就能连真实模型。"
fi

# --- 启动 ---

PIDS=()
STOPPED=0

stop_all() {
  [ "$STOPPED" = 1 ] && return
  STOPPED=1
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] || continue
    if [ "${OS:-}" = "Windows_NT" ]; then
      # Windows 上要连子孙一起收（vite 还有 esbuild 子进程），所以用 taskkill /T。
      # ⚠ $! 给的是 MSYS/Cygwin 自己的 pid，taskkill 只认 Windows pid ——
      # 直接把前者喂给 taskkill 会打到**同号的无关进程**上。真正的 Windows pid
      # 在 /proc/<pid>/winpid 里。// 是为了躲开 MSYS 的路径转换。
      winpid="$(cat "/proc/$pid/winpid" 2>/dev/null || true)"
      if [ -n "$winpid" ]; then
        taskkill //F //T //PID "$winpid" >/dev/null 2>&1 || true
      fi
      kill "$pid" >/dev/null 2>&1 || true # 读不到 winpid 时至少收掉这一层
    else
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}

trap 'stop_all; exit 130' INT TERM
trap stop_all EXIT

echo "后端 http://localhost:$BACKEND_PORT/api/health"
echo "前端 http://localhost:$FRONTEND_PORT"
echo "按 Ctrl+C 停止两个服务"
echo

(
  cd "$BACKEND"
  exec "$PYTHON" -m flask --app "app:create_app()" run --port "$BACKEND_PORT"
) &
PIDS+=("$!")

(
  cd "$FRONTEND"
  exec npm run dev -- --port "$FRONTEND_PORT" --strictPort
) &
PIDS+=("$!")

# 任何一个退出（手动杀掉、崩了）都收摊，不留半个服务在后台
wait -n "${PIDS[@]}"
stop_all
