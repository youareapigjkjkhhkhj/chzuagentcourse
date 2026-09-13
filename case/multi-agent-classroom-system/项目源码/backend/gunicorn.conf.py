"""gunicorn 配置（P5 §6）。用法：`gunicorn -c gunicorn.conf.py "app:create_app()"`。

**为什么是 gevent 而不是 sync**：这台服务上有两种长连接 —— SSE
（`/api/courses/generate/{id}/stream`，一次生成一两分钟）与 WebSocket
（`/ws/voice/realtime`、`/ws/classroom/…`）。sync worker 一次只能拿一个请求，
一条 SSE 就会把一个 worker 占死；而 `simple-websocket` 只认几种 WSGI 服务器
暴露出来的 socket，gevent 是其中之一（另一种是 werkzeug 的开发服务器）。

**为什么 workers 固定 1**：
- SQLite 是单写者。多进程写同一个库要靠重试去绕，而这个仓库从 P1 起就把
  「串行化写」放在进程内的锁里（common/dbw.py）—— 一个进程内它成立，
  两个进程就不成立了。
- 课堂运行时的在线名单与事件游标在**进程内存**里（services/classroom/runtime.py）。
  两个 worker 各持一半连接，就会看到两个不同的课堂。
- P5 §8 的对策里写着「单实例部署，不用多副本」。gevent 的并发在 greenlet 上，
  一个 worker 足够扛住一间教室。

**超时**：SSE 与 WS 都是「长时间没有数据也不该被杀」的连接。心跳（15s）与
ping（20s）让数据一直在动，所以把 timeout 放到 300s 就行 —— 它管的是
「worker 卡住了吗」，不是「这个请求跑多久了」。
"""

import multiprocessing  # noqa: F401  # 留着：改并发时第一个要看的是机器核数

bind = "0.0.0.0:5000"
worker_class = "gevent"
workers = 1
worker_connections = 1000
# 见模块 docstring：SSE / WS 的时长靠心跳保证，不靠放大这个值兜底
timeout = 300
graceful_timeout = 30
keepalive = 5

# 日志出 stdout/stderr，由容器运行时收。**不在这里另开文件**：
# 应用自己的 LOG_FILE 那条路留给物理机部署（app/common/logging.py），
# 两处都开会让日志有两个去处，而运维只会看其中一个。
accesslog = "-"
errorlog = "-"
loglevel = "info"

# 访问日志里会带上请求行（含查询串）。票据走的是**加密后的 URL 参数**
# （P5 §4.1 的一次性下载 token、课堂的接入票据），而日志侧的脱敏滤器
# （app/common/logging.py）只作用于应用日志，管不到 gunicorn 自己写的这一行。
# 所以这里显式换掉默认格式：去掉请求行里的查询串，只留路径。
# 排查问题要的是「谁在什么时候打了哪个接口」，不是他带的那张票。
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s" %(s)s %(b)s %(D)sus'


def on_starting(server):  # pragma: no cover - 只在容器里跑到
    server.log.info("EduAgentX gunicorn 启动：%s workers=%s", worker_class, workers)
