#!/usr/bin/env bash
#
# 一条命令拉起后端 :5000 与前端 :5173（P0-A1）。
#
#   bash scripts/dev.sh              # Git Bash / macOS / Linux
#   bash scripts/dev.sh --force      # 端口被占时，替你收掉占用者再起
#   NO_OPEN=1 bash scripts/dev.sh    # 不自动开浏览器
#   BACKEND_PORT=5001 bash scripts/dev.sh
#   READY_TIMEOUT=120 bash scripts/dev.sh
#
# Windows 上的两个入口：.\scripts\dev.ps1（PowerShell）、双击项目根目录的 start.cmd。
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
READY_TIMEOUT="${READY_TIMEOUT:-60}"
FORCE=0
NO_OPEN="${NO_OPEN:-0}"

case "${1:-}" in
  --force | -f) FORCE=1 ;;
  --help | -h)
    sed -n '3,13p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 0
    ;;
  '') ;;
  *)
    echo "不认识的参数：$1（可用：--force）" >&2
    exit 2
    ;;
esac

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

# --- 端口检查 ---
#
# 上一次没收干净（关终端没走 Ctrl+C、进程崩了）时，端口还占着 —— 这时后端会
# 秒退、前端却照样起来，界面看着正常、接口全挂，最难查。所以起之前先问一句。

port_holders() { # $1=端口 → 每行一个「PID 进程名」，没人监听就什么都不输出
  if [ "${OS:-}" = "Windows_NT" ]; then
    netstat -ano 2>/dev/null |
      grep -E "[:.]$1[[:space:]]" |
      grep -i "listening" |
      awk '{print $NF}' | sort -u |
      while read -r pid; do
        [ -n "$pid" ] || continue
        local name
        # // 是为了躲开 MSYS 的路径转换（同下面 taskkill 那条注释）
        # || true：查不到进程名不该让整个脚本死在这儿（set -e 下管道里的 grep 空手而归就会）
        name="$( { tasklist //FI "PID eq $pid" //FO CSV //NH 2>/dev/null || true; } | head -1 | cut -d, -f1 | tr -d '"')"
        echo "$pid ${name:-未知进程}"
      done
  else
    lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $2, $1}' | sort -u
  fi
}

for spec in "后端:$BACKEND_PORT" "前端:$FRONTEND_PORT"; do
  label="${spec%%:*}"
  port="${spec##*:}"
  # || true：没人监听时这条管道整体是非零（grep 空手 / read 读到 EOF），
  # 而 `set -e` 下「赋值失败」会直接结束脚本 —— 那正是最常见的「端口空着」这一路。
  holders="$(port_holders "$port" || true)"
  [ -n "$holders" ] || continue

  if [ "$FORCE" != "1" ]; then
    echo "端口 $port 已被占用（$label 要用）：" >&2
    echo "$holders" | sed 's/^/    PID /' >&2
    echo "要么先关掉它，要么让本脚本替你收：bash scripts/dev.sh --force" >&2
    exit 1
  fi

  echo "端口 $port 被占用，--force：收掉它"
  # 用 for 而不是 `... | while read`：那样写循环跑在子 shell 里，
  # 而且管道末尾的 read 读到 EOF 会给整条命令一个非零退出码。
  for pid in $(echo "$holders" | awk '{print $1}'); do
    if [ "${OS:-}" = "Windows_NT" ]; then
      taskkill //F //T //PID "$pid" >/dev/null 2>&1 || true
    else
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  sleep 1
done

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

echo "正在启动后端 :$BACKEND_PORT 与前端 :$FRONTEND_PORT ……（Ctrl+C 停止）"

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

# --- 等就绪 ---
#
# 起进程和「能打开」是两件事：flask 要连库、vite 要预打包依赖，各自几秒钟。
# 地址先报出去的话，人一开就是白屏，然后回来问「怎么打不开」。所以等真返回
# 200 再说 —— 顺带把「起来又秒退」也一并认出来（那多半是建库/密钥的问题）。

wait_http() { # $1=名字 $2=URL $3=进程号 $4=最多等几秒
  local label="$1" url="$2" pid="$3" limit="$4" begin now code
  begin="$(date +%s)"
  while :; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "" >&2
      echo "✗ $label 起来又退了 —— 上面那几行就是原因" >&2
      return 1
    fi
    code="$(curl -s -o /dev/null -m 2 -w '%{http_code}' "$url" 2>/dev/null || true)"
    if [ "$code" = "200" ]; then
      now="$(date +%s)"
      echo "✓ $label 就绪（$((now - begin))s）  $url"
      return 0
    fi
    if [ $(( $(date +%s) - begin )) -ge "$limit" ]; then
      echo "" >&2
      echo "✗ $label 等了 ${limit}s 还没就绪：$url" >&2
      return 1
    fi
    sleep 0.5
  done
}

if ! command -v curl >/dev/null 2>&1; then
  # 没有 curl 就不等：报个地址出来，总比卡在这儿强
  echo "提示：没有 curl，跳过就绪等待，直接给你地址"
  echo "后端 http://localhost:$BACKEND_PORT/api/health"
  echo "前端 http://localhost:$FRONTEND_PORT"
  wait -n "${PIDS[@]}"
  stop_all
  exit 0
fi

if ! wait_http "后端" "http://127.0.0.1:$BACKEND_PORT/api/health" "${PIDS[0]}" "$READY_TIMEOUT"; then
  echo "  常见原因：数据库还没建（make migrate && make seed）、.env 里的密钥不对、" >&2
  echo "            端口被别的程序占着（bash scripts/dev.sh --force）。" >&2
  exit 1
fi

# 前端用 localhost 探：让 vite 绑定地址去决定走 ::1 还是 127.0.0.1（见 P0 的说明）
if ! wait_http "前端" "http://localhost:$FRONTEND_PORT" "${PIDS[1]}" "$READY_TIMEOUT"; then
  echo "  常见原因：5173 被上次没关掉的 vite 占着（bash scripts/dev.sh --force）。" >&2
  exit 1
fi

echo
echo "课堂演示  http://localhost:$FRONTEND_PORT"
echo "接口自检  http://localhost:$BACKEND_PORT/api/health"
echo "按 Ctrl+C 停止这两个服务"
echo

if [ "$NO_OPEN" != "1" ]; then
  if [ "${OS:-}" = "Windows_NT" ]; then
    # explorer 只认 URL 本身，不会像 cmd /c start 那样被 MSYS 改路径；它自己
    # 的退出码没意义，所以 || true。
    explorer.exe "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1 || true
  elif [ "$(uname -s)" = "Darwin" ]; then
    open "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1 || true
  else
    xdg-open "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1 || true
  fi
fi

# 任何一个退出（手动杀掉、崩了）都收摊，不留半个服务在后台
wait -n "${PIDS[@]}"
stop_all
