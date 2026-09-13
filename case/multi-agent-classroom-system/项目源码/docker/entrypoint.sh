#!/bin/sh
# 容器入口（P5-A11 / §6）：
#   1. 修一次挂载目录的属主，然后**降权**到 app 用户
#   2. 跑数据库迁移（每次启动都跑：迁移是幂等的，而漏跑的代价是 500）
#   3. 按需灌种子（SEED_ON_START=1 时才跑）
#   4. 起一个后台清理循环（可选，见下）
#   5. exec 到 gunicorn，把 PID 1 交给它
set -e

DATA_DIR="${DATA_DIR:-/app/backend/data}"

# 卷是宿主机的目录，属主通常是宿主机的用户；容器里的 app 用户对它没有写权限。
# 以 root 进来修一次属主，再用 gosu 降权 —— 进程本身**始终**不是 root（P5-F3）。
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    # 只在必要时修属主：data 里可能有几千个音频文件，每次都 -R 会在冷启动
    # 预算（P5-D4：30 秒）里白白吃掉好几秒。
    if [ "$(stat -c %u "$DATA_DIR" 2>/dev/null || echo 0)" != "10001" ]; then
        chown -R app:app "$DATA_DIR"
    fi
    exec gosu app "$0" "$@"
fi

# 后面每条 flask 命令都假设当前目录是后端根（app 包在那儿）
cd /app/backend
echo "[entrypoint] 以 $(id -un) 身份启动，数据目录 $DATA_DIR"

# 迁移。必须先于任何读库的东西 —— 应用启动时的「收拾上次中断的任务」
# 就会读表（见 app/__init__.py 的 _recover_stuck_jobs）。
echo "[entrypoint] 执行数据库迁移"
flask --app "app:create_app()" db upgrade

if [ "${SEED_ON_START:-0}" = "1" ]; then
    echo "[entrypoint] 灌入种子数据（幂等）"
    flask --app "app:create_app()" seed
fi

# 产物清理（P5-C1）。仓库里没有常驻调度器，容器里也不该因为这个再多一个进程，
# 所以就从这里起一条**后台小循环**：清理本身是本地库查询 + 删文件，很轻。
# EXPORT_CLEANUP_INTERVAL=0 关掉它，改由宿主机 cron 调
# `docker compose exec app flask exports-cleanup`。
CLEANUP_INTERVAL="${EXPORT_CLEANUP_INTERVAL:-3600}"
if [ "$CLEANUP_INTERVAL" != "0" ]; then
    (
        while true; do
            sleep "$CLEANUP_INTERVAL"
            flask --app "app:create_app()" exports-cleanup || true
        done
    ) &
    echo "[entrypoint] 已挂上产物清理循环：每 ${CLEANUP_INTERVAL}s 一次"
fi

exec "$@"
