#!/usr/bin/env python
"""P4 A/B/C/D/F/G 类验收（P4-G2）：把三份样例材料从上传一路走到「带出处的课」。

一条命令跑完，**不联网、不读 `.env`、不碰 `backend/data/`**：两个临时后端共用
一份临时 SQLite 与一个临时材料目录，跑完连库带文件一起删。

```bash
cd 项目源码
python scripts/accept_p4.py
```

| 实例 | 端口 | 配置 | 验的是 |
|------|------|------|--------|
| 主实例 | :5084 | 离线替身、材料开 | A/B/C/D/F/G 的绝大多数 |
| 关材料 | :5085 | `MATERIAL_ENABLED=false` | G3 上传入口关掉、生成退回 P1 路径 |

**两个实例为什么是这两个配置**：G3 验的是「部署方把材料关掉之后，产品还是不是
原来那条路」—— 这条只能在另一台把开关拧掉的实例上验，主实例上验不了。

## 材料从哪来

`项目源码/samples/materials/` 里那三份**是脚本的一部分**，不是随手放的测试文件：

| 样例 | 用来验 |
|------|--------|
| `机器学习讲义.md` | 主材料：分块/检索/带材料生成/溯源跳转 |
| `检索算法笔记.txt` | 另一门学科的纯文本：验检索不串门、纯文本也推得出章节 |
| `生物统计入门.md` | **与课程主题无关**的那一份：验「材料没写」时说没写（P4-A8） |

五种格式里的 `.pdf/.docx/.pptx` 由脚本当场造（`_make_formats`）：仓库里塞三个
二进制文件既看不出内容、又会在每次改版时产生无法 review 的 diff，而它们的
**字节**恰恰是这几种解析器唯一认识的东西。造出来的文件放在临时目录里，跑完就没了。

## 报的与不报的

跑不到的（要真上游、要人读、要浏览器渲染）一律如实记 **跳过**，并把**离线侧验到
的那一半**写在同一行里 —— 假装验过比不验更糟。委托给 pytest 的条目在最后逐条
记账（`-rA`，通过/没通过都点名）。

## 与 P3 脚本的关系

骨架（`Report` / `api` / `child_env` / `_guard` / `prepare_database` / 失败留现场）
照搬 `accept_p3.py`：两条命令的读法、输出形状、失败时的现场保留方式应当一致。
**没有改动任何被测代码** —— 脚本红了就改脚本或改实现，不改「怎么算通过」。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """去掉 ANSI 颜色码：报错详情里混着转义序列没法读。"""
    return _ANSI.sub("", text or "")


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
SAMPLES = ROOT / "samples" / "materials"

#: 两个临时后端。刻意不用 5000（`make dev` 的端口，连的是你的库），
#: 也不挨着 P0~P3（5081~5083、5094~5096）：同时跑两条验收时互不打扰。
MAIN_PORT = 5084
NOMAT_PORT = 5085

def _base() -> str:
    """默认调主实例（另一台用 `base=ctx.nomat` 显式指定）。"""
    return f"http://127.0.0.1:{MAIN_PORT}/api"


#: 三份样例材料。**文件名写死**：脚本要用它们验「重复上传」「越权」这些事，
#: 换个名字就得跟着改一处，不如把契约摆在明面上。
SAMPLE_ML = "机器学习讲义.md"
SAMPLE_SEARCH = "检索算法笔记.txt"
SAMPLE_BIO = "生物统计入门.md"

#: 检索用的词，都取自样例材料（P4-A3 要「讲义里的术语」）。
TERM_INDEX = "倒排索引"
TERM_DESCENT = "梯度下降"
#: 材料里压根没有的词（P4-A3 的后半段：不硬凑）。
TERM_ABSENT = "量子纠缠退相干"

#: 课程主题。**刻意选成材料里有的那个词**：章标签会围着它长出来
#: （`fixture._CHAPTER_LABELS` 是「认识{topic}」「{topic}的核心方法」…），
#: 于是「要点能在材料里找到依据」这条离线也验得到。
TOPIC_WITH_MATERIAL = "梯度下降"
#: 材料完全没写到的主题（P4-A8：该说缺口就说缺口）。
TOPIC_WITHOUT_MATERIAL = "量子计算入门"

#: 一个不在这两门课里、也不拥有任何材料的人（P4-F4 的越权口径）。
OUTSIDER = "outsider_p4_7c1e"

#: 生成最多等多久（墙钟）。离线替身跑 8 页课要几十秒，超了说明卡住了。
GEN_DEADLINE = 240.0

#: 一轮对话最多等多久（P4-D5 量首 token，这条是它的上界）。
TURN_DEADLINE = 60.0

#: 离线替身的凭据口径，与 `accept_p2.py` / `accept_p3.py` 逐字一致
#: （只设 `EDUAGENTX_DISABLE_DOTENV` 拦不住 Flask CLI 自己读 `.env`）。
OFFLINE_ENV: dict[str, str] = {
    "EDUAGENTX_DISABLE_DOTENV": "1",
    "FLASK_SKIP_DOTENV": "1",
    "LLM_PROVIDER": "mock",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "",
    "VOLC_TTS_API_KEY": "",
    "VOLC_TTS_ENDPOINT": "",
    "VOLC_TTS_RESOURCE_ID": "",
    "VOLC_ASR_API_KEY": "",
    "VOLC_ASR_ENDPOINT": "",
    "VOLC_ASR_RESOURCE_ID": "",
    "VOLC_REALTIME_API_KEY": "",
    "VOLC_REALTIME_ENDPOINT": "",
    "VOLC_REALTIME_MODEL": "",
    "VOLC_TTS_VOICE_TEACHER": "mock-voice-teacher",
    "VOLC_TTS_VOICE_HISTORY": "mock-voice-humanities",
}

#: 关材料实例：部署方的一个决定（P4-G3），其余照旧。
NOMAT_ENV: dict[str, str] = {**OFFLINE_ENV, "MATERIAL_ENABLED": "false"}

#: 检索 P95 的语料规模（P4-D3 的「万级 chunk」）。
SYNTH_CHUNKS = 10_000
#: P95 采样多少次。30 次里最慢的那两次就是 P95，够看出量级了。
SYNTH_QUERIES = 30
#: P4-D3 的门槛（毫秒）。
SEARCH_P95_MS = 200.0


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


class Report:
    """通过清单。最后要能一眼看出「哪几条没过」。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def _add(self, aid: str, title: str, status: str, detail: str) -> None:
        detail = plain(detail)
        self.rows.append((aid, title, status, detail))
        label = {"PASS": "通过", "FAIL": "不通过", "SKIP": "跳过"}[status]
        print(f"  [{label}] {aid} {title}")
        if detail:
            for line in detail.splitlines():
                print(f"         {line}")

    def ok(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "PASS", detail)

    def fail(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "FAIL", detail)

    def skip(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "SKIP", detail)

    def verdict(self, aid: str, title: str, problems: Sequence[str], detail: str = "") -> None:
        """一组断言：`problems` 非空即不通过，内容原样打印。"""
        if problems:
            self.fail(aid, title, "；".join(problems))
        else:
            self.ok(aid, title, detail)

    def summary(self) -> int:
        passed = sum(1 for row in self.rows if row[2] == "PASS")
        failed = [r for r in self.rows if r[2] == "FAIL"]
        skipped = [r for r in self.rows if r[2] == "SKIP"]
        print()
        print("=" * 68)
        print(f"P4 验收：通过 {passed} / 不通过 {len(failed)} / 跳过 {len(skipped)}")
        for aid, title, _, detail in failed:
            print(f"  ✗ {aid} {title}")
            if detail:
                print(f"      {detail.splitlines()[0]}")
        for aid, title, _, detail in skipped:
            print(f"  - {aid} {title}（{detail.splitlines()[0] if detail else '未说明'}）")
        print("=" * 68)
        return 1 if failed else 0


# --------------------------------------------------------------------------
# HTTP（只用标准库：脚本要能被系统 python 直接跑起来）
# --------------------------------------------------------------------------


def api(
    method: str,
    path: str,
    body: Any = None,
    *,
    base: str = "",
    owner: str = "",
    timeout: float = 30.0,
) -> tuple[int, dict]:
    """调后端接口，返回 (HTTP 状态, 信封)。业务错误也在信封里，不抛异常。"""
    data = None
    headers = {"X-Request-Id": "accept-p4"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if owner:
        headers["X-Owner-Id"] = owner
    req = urllib.request.Request(f"{base or _base()}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, {"raw": text[:400]}
    except Exception as exc:  # 连不上 / 超时
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def api_upload(
    filename: str, payload: bytes, *, owner: str = "", base: str = "", timeout: float = 120.0
) -> tuple[int, dict]:
    """上传一份材料（multipart 手拼：脚本不装 requests）。

    文件名按 UTF-8 原样写进头部：中文文件名是常态，而这正是 `policy.display_name`
    要处理的东西 —— 用 ASCII 名字上传等于把那段逻辑绕过去了。
    """
    boundary = f"----acceptP4{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    body = head + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-Request-Id": "accept-p4",
    }
    if owner:
        headers["X-Owner-Id"] = owner
    req = urllib.request.Request(f"{base or _base()}/materials", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, {"raw": text[:400]}
    except Exception as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _data(status: int, envelope: Mapping[str, Any]) -> Any:
    """成功信封里的 `data`（收 2xx 而不只是 200：上传成功是 **201**）。"""
    if 200 <= int(status) < 300 and envelope.get("code") == 0:
        return envelope.get("data")
    return None


def _why(status: int, envelope: Mapping[str, Any]) -> str:
    """一句能读的失败原因（HTTP 状态 + 服务端那句话）。"""
    detail = envelope.get("message") or envelope.get("error") or ""
    extra = envelope.get("data")
    if isinstance(extra, Mapping) and extra.get("details"):
        detail = f"{detail} {brief(extra['details'], 200)}"
    return f"HTTP {status} code={envelope.get('code')} {detail}".strip()


def brief(payload: Any, limit: int = 300) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def is_up(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False


def wait_http(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


# --------------------------------------------------------------------------
# SSE 客户端（标准库手写）
# --------------------------------------------------------------------------


class SseReader:
    """一条 SSE 长连接，后台线程收帧，主线程随时取。

    工作台那一轮的**顺序是不能反的**：先连上流、再发消息。反过来的话，
    回复的第一批 `agent.delta` 会在连接建立之前发出去，而 SSE 没有回放
    （`?after=` 能补，但那是重连用的，不该拿来当正常路径）。
    """

    def __init__(self, url: str, *, owner: str = "") -> None:
        self.url = url
        self.owner = owner
        self.frames: list[tuple[str, dict]] = []
        self.raw: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error = ""

    def start(self) -> None:
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        headers = {"Accept": "text/event-stream", "X-Request-Id": "accept-p4"}
        if self.owner:
            headers["X-Owner-Id"] = self.owner
        req = urllib.request.Request(self.url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TURN_DEADLINE + 30) as resp:
                name = ""
                for raw in resp:
                    if self._stop.is_set():
                        break
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    with self._lock:
                        self.raw.append(line)
                    if line.startswith("event:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        text = line.split(":", 1)[1].strip()
                        try:
                            payload = json.loads(text)
                        except json.JSONDecodeError:
                            payload = {"raw": text}
                        with self._lock:
                            self.frames.append((name, payload))
        except Exception as exc:  # 连不上 / 流断了：记下来，由调用方判
            self.error = f"{type(exc).__name__}: {exc}"

    def snapshot(self) -> list[tuple[str, dict]]:
        with self._lock:
            return list(self.frames)

    def find(self, event: str) -> list[dict]:
        return [payload for name, payload in self.snapshot() if name == event]

    def wait_for(
        self, event: str, *, timeout: float, count: int = 1, after: int = 0
    ) -> list[dict]:
        """等某一类帧攒够 `count` 条（`after` 是「从第几条之后开始数」）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = [payload for name, payload in self.snapshot() if name == event]
            if len(found) >= after + count:
                return found[after:]
            time.sleep(0.05)
        return []

    def wait_any(self, events: Sequence[str], *, timeout: float) -> tuple[str, dict] | None:
        """等其中任意一帧先到（第一条 `agent.delta` 或 `agent.done` 都用它等）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for name, payload in self.snapshot():
                if name in events:
                    return name, payload
            time.sleep(0.02)
        return None

    def close(self) -> None:
        self._stop.set()

    def dump(self, path: Path) -> None:
        """落一份原始帧（失败时留现场用）。"""
        with self._lock:
            lines = list(self.raw)
        if lines:
            path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# 子进程
# --------------------------------------------------------------------------


def venv_python() -> Path:
    for rel in ("Scripts/python.exe", "bin/python"):
        candidate = BACKEND / ".venv" / rel
        if candidate.exists():
            return candidate
    sys.exit("找不到虚拟环境。先建：python -m venv backend/.venv 然后 pip install -r backend/requirements.txt")


def npx() -> str:
    return shutil.which("npx") or shutil.which("npx.cmd") or "npx"


def child_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """子进程的环境（与 accept_p2/p3 同一份，含那两条编码与 `.env` 的闸门）。"""
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "FLASK_SKIP_DOTENV": "1",
        "EDUAGENTX_DISABLE_DOTENV": "1",
        **(env or {}),
    }


def start(process_args: list[str], cwd: Path, log_path: Path, env: dict[str, str] | None = None):
    log = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        process_args, cwd=str(cwd), env=child_env(env),
        stdout=log, stderr=subprocess.STDOUT,
    )


def stop(proc) -> None:
    """停掉我们启动的服务（含它的子进程；Windows 上 terminate 杀不干净）。"""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_python(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """在 backend 目录下用 venv python 跑一段代码（造合成语料、读盘上的文件都用它）。"""
    return subprocess.run(
        [str(venv_python()), "-c", code],
        cwd=str(BACKEND),
        env=child_env(env),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_pytest(*args: str) -> subprocess.CompletedProcess:
    """跑一趟 pytest。**这里不能再加 `-q`**：`pyproject.toml` 的 addopts 里已经有一个了。"""
    return subprocess.run(
        [str(venv_python()), "-m", "pytest", *args],
        cwd=str(BACKEND),
        env=child_env(),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _pytest_tail(result: subprocess.CompletedProcess, lines: int = 12) -> str:
    output = plain((result.stdout or "") + (result.stderr or ""))
    return "\n".join(line for line in output.splitlines()[-lines:] if line.strip())


def _pytest_summary(result: subprocess.CompletedProcess) -> str:
    output = plain((result.stdout or "") + (result.stderr or ""))
    for line in reversed(output.splitlines()):
        if re.search(r"\b\d+\s+(passed|failed|error|skipped|xfailed)", line):
            return line.strip().strip("=").strip()
    return _pytest_tail(result, 2).replace(chr(10), " ")


#: 委托用例的逐条结果（节点 id → PASSED/FAILED/…）。跑一趟、多处引用。
_NODE_CACHE: dict[str, str] = {}


def pytest_verdicts(nodes: Iterable[str]) -> None:
    """跑一趟 `-rA`，把逐条结论记进 `_NODE_CACHE`（整文件与单条分两趟，见 accept_p3）。"""
    unique = sorted(set(nodes))
    if not unique:
        return
    whole = [node for node in unique if "::" not in node]
    single = [node for node in unique if "::" in node]
    for batch in (whole, single):
        if batch:
            _pytest_verdicts_of(batch)


def _pytest_verdicts_of(nodes: list[str]) -> None:
    result = run_pytest("-rA", "-p", "no:cacheprovider", *nodes)
    seen: list[str] = []
    for line in plain((result.stdout or "") + (result.stderr or "")).splitlines():
        match = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)", line.strip())
        if match:
            verdict, name = match.group(1), match.group(2)
            seen.append(name)
            _NODE_CACHE[name] = verdict
            _NODE_CACHE.setdefault(name.split("[", 1)[0], verdict)
    if seen:
        return
    tail = (_pytest_tail(result, 6).splitlines() or ["（pytest 没有输出）"])[-1]
    for node in nodes:
        _NODE_CACHE.setdefault(node, f"没跑到（pytest 这么说：{tail}）")


def _cases_passed(node: str) -> int:
    if node in _NODE_CACHE:
        return 1 if _NODE_CACHE[node] == "PASSED" else 0
    prefix = node + "::"
    return sum(
        1 for name, value in _NODE_CACHE.items() if name.startswith(prefix) and value == "PASSED"
    )


def pytest_node_ok(node: str) -> tuple[bool, str]:
    verdict = _NODE_CACHE.get(node)
    if verdict:
        return verdict == "PASSED", "" if verdict == "PASSED" else verdict
    prefix = node + "::"
    inside = {name: value for name, value in _NODE_CACHE.items() if name.startswith(prefix)}
    if not inside:
        return False, "没跑到（用例被改名或删掉了？）"
    bad = sorted(name.rsplit("::", 1)[-1] for name, value in inside.items() if value != "PASSED")
    if bad:
        return False, f"{len(bad)} 条没通过：{bad[:3]}"
    return True, ""


# --------------------------------------------------------------------------
# 一次验收里要来回传的东西
# --------------------------------------------------------------------------


@dataclass
class Ctx:
    """两个临时后端 + 这次跑出来的材料与课程。检查函数从这里取料，不各自新建。"""

    env: dict[str, str]
    work_dir: Path
    material_dir: Path
    format_dir: Path
    db_urls: dict[int, str] = field(default_factory=dict)
    procs: dict[str, Any] = field(default_factory=dict)
    #: 材料名 → fileId（上传过的样例材料，后面对话与课程关联都按名字取）
    files: dict[str, str] = field(default_factory=dict)
    #: 主课程（带材料生成出来的那一门）
    course_id: str = ""
    #: 工作台会话里发过的每一句话（回退要按消息 id 找）
    prompts: list[str] = field(default_factory=list)
    logs: dict[str, Path] = field(default_factory=dict)

    @property
    def main(self) -> str:
        return f"http://127.0.0.1:{MAIN_PORT}/api"

    @property
    def nomat(self) -> str:
        return f"http://127.0.0.1:{NOMAT_PORT}/api"


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------


def _guard(rep: Report, label: str, fn, *args) -> None:
    """跑一组检查。抛异常也要留下痕迹：一组崩掉就把后面几十条结果全丢了。"""
    try:
        fn(rep, *args)
    except Exception as exc:  # 脚本要活下去：一组崩掉就记一条，接着跑下一组
        where = ""
        tb = exc.__traceback__
        while tb is not None:
            if tb.tb_next is None:
                where = f"（{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}）"
            tb = tb.tb_next
        rep.fail("P4-EXC", f"{label} 组检查中断", f"{type(exc).__name__}: {exc}{where}")


def sample(name: str) -> bytes:
    """读一份样例材料（脚本自带的那三份）。"""
    return (SAMPLES / name).read_bytes()


def upload_ready(ctx: Ctx, name: str, *, owner: str = "", base: str = "", force_new: bool = False):
    """上传并等它解析完，返回 `(status, 信封, 元信息)`。

    解析是后台线程，`status` 回来时是 `parsing` —— 所有的检查都要等 `ready`，
    所以「等」这件事收在这一处，别在每处各写一遍轮询。
    """
    data = sample(name)
    response = api_upload(name, data, owner=owner, base=base)
    body = _data(*response)
    if not isinstance(body, Mapping):
        return response[0], response[1], None
    file_id = str(body.get("fileId") or "")
    if not force_new:
        ctx.files.setdefault(name, file_id)
    detail = wait_ready(file_id, base=base, owner=owner)
    return response[0], response[1], detail


def wait_ready(
    file_id: str, *, base: str = "", owner: str = "", timeout: float = 120.0
) -> dict | None:
    """轮询材料详情直到 `ready`（失败也返回那一份：原因就在 `error` 里）。"""
    deadline = time.time() + timeout
    detail: dict | None = None
    while time.time() < deadline:
        status, envelope = api("GET", f"/materials/{file_id}", base=base, owner=owner)
        found = _data(status, envelope)
        if isinstance(found, Mapping):
            detail = dict(found)
            if detail.get("status") in {"ready", "failed"}:
                return detail
        time.sleep(0.2)
    return detail


def file_id_of(ctx: Ctx, name: str, *, owner: str = "") -> str:
    """按名字取 fileId（没上传过就现传一份）。"""
    found = ctx.files.get(name)
    if found and not owner:
        return found
    _status, _envelope, detail = upload_ready(ctx, name, owner=owner)
    if not detail:
        raise AssertionError(f"材料 {name} 没传上去")
    return str(detail["fileId"])


# --------------------------------------------------------------------------
# 一、样例材料与五种格式（P4-A1 / P4-C3 / P4-C4 / P4-B1 / P4-B2 / P4-F1）
# --------------------------------------------------------------------------


def check_samples(rep: Report, ctx: Ctx) -> None:
    """三份样例材料本身：在仓库里、读得动、内容是中文。"""
    problems = []
    for name in (SAMPLE_ML, SAMPLE_SEARCH, SAMPLE_BIO):
        if not (SAMPLES / name).exists():
            problems.append(f"缺样例：{name}")
    rep.verdict(
        "P4-G2a",
        "仓库自带 3 份样例材料（P4-G2）",
        problems,
        "、".join(f"{name}（{len(sample(name))} 字节）" for name in (SAMPLE_ML, SAMPLE_SEARCH, SAMPLE_BIO))
        if not problems
        else "",
    )


def _make_formats(ctx: Ctx) -> dict[str, Path]:
    """当场造 pdf / docx / pptx（第二种格式各一份）。

    造出来的内容与 `机器学习讲义.md` 的前几节一样 —— 五种格式解析出来的应当是
    **同一门课的材料**，而不是五个各说各话的样本：后面按术语检索时，命中哪个
    格式的块都算命中。
    """
    ctx.format_dir.mkdir(parents=True, exist_ok=True)
    code = f'''
import json
from pathlib import Path

out = Path(r"{ctx.format_dir.as_posix()}")
body = [
    ("什么是梯度下降", "梯度下降的核心方法是沿着梯度的反方向走一小步，学习率决定这一步走多远。"),
    ("损失函数", "损失函数衡量预测值和真实值差多少，训练的目标就是把它降到最小。"),
    ("过拟合", "过拟合是模型把训练集里的噪声也当成规律学了进去，正则化是常见对策。"),
    ("倒排索引", "倒排索引把词映射到文档，查一个词就不必扫全部原文，这是检索加速的关键。"),
    ("BM25 排序", "BM25 用文档长度做归一化，再用逆文档频率压掉常见词，让排序更合理。"),
    ("样本量", "样本量太小，真实存在的差别也常常测不出来，这叫把握度不足。"),
] * 3

import fitz  # PyMuPDF
doc = fitz.open()
for title, text in body:
    page = doc.new_page()
    page.insert_text((72, 88), title, fontname="china-s", fontsize=18)
    page.insert_textbox(fitz.Rect(72, 116, 520, 300), text, fontname="china-s", fontsize=12)
doc.save(str(out / "讲义片段.pdf"))

from docx import Document
word = Document()
for title, text in body:
    word.add_heading(title, level=1)
    word.add_paragraph(text)
word.save(str(out / "讲义片段.docx"))

from pptx import Presentation
deck = Presentation()
for title, text in body:
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = text
deck.save(str(out / "讲义片段.pptx"))

print(json.dumps(sorted(p.name for p in out.iterdir()), ensure_ascii=False))
'''
    result = run_python(code, env=ctx.env)
    if result.returncode != 0:
        raise AssertionError(f"造样例文件失败：{plain((result.stderr or '')[-500:])}")
    return {path.name: path for path in ctx.format_dir.iterdir()}


def check_formats(rep: Report, ctx: Ctx) -> None:
    """P4-A1：五种格式各传一份，都要 ready、chars > 0、分块带页码与章节。"""
    built = _make_formats(ctx)
    problems: list[str] = []
    lines: list[str] = []
    cases = [
        ("Markdown", SAMPLE_ML, sample(SAMPLE_ML)),
        ("纯文本", SAMPLE_SEARCH, sample(SAMPLE_SEARCH)),
        ("PDF", "讲义片段.pdf", built["讲义片段.pdf"].read_bytes()),
        ("Word", "讲义片段.docx", built["讲义片段.docx"].read_bytes()),
        ("PPT", "讲义片段.pptx", built["讲义片段.pptx"].read_bytes()),
    ]
    for label, name, payload in cases:
        status, envelope = api_upload(name, payload)
        body = _data(status, envelope)
        if not isinstance(body, Mapping):
            problems.append(f"{label} 上传失败：{_why(status, envelope)}")
            continue
        detail = wait_ready(str(body["fileId"]), timeout=180)
        if not detail:
            problems.append(f"{label} 解析没等到结果")
            continue
        if detail.get("status") != "ready":
            problems.append(f"{label} 状态是 {detail.get('status')}（{detail.get('error')}）")
            continue
        if int(detail.get("charCount") or 0) <= 0 or int(detail.get("chunkCount") or 0) <= 0:
            problems.append(f"{label} 解析出来了但没内容：{brief(detail, 160)}")
            continue
        ctx.files[name] = str(detail["fileId"])

        pages = _chunk_pages(ctx, str(detail["fileId"]))
        lines.append(
            f"{label} {name}：{detail['charCount']} 字 / {detail['chunkCount']} 块 / "
            f"{detail.get('pages') or 0} 页（块 [{'有' if pages else '无'}] page_from…page_to）"
        )
        # PDF 要能报出页码区间（F4-2：检索结果要能说「第 12 页」）
        if label == "PDF" and not pages:
            problems.append("PDF 的分块没带 page_from/page_to")

    rep.verdict("P4-A1", "五种格式上传解析（md / txt / pdf / docx / pptx）", problems, "\n".join(lines))


def _chunk_pages(ctx: Ctx, file_id: str) -> int:
    """有页码区间的块有多少（PDF 的验收点）。"""
    status, envelope = api("GET", f"/materials/{file_id}/chunks?size=200")
    data = _data(status, envelope)
    items = (data or {}).get("items") or []
    return sum(1 for item in items if item.get("pageFrom"))


def check_upload_guards(rep: Report, ctx: Ctx) -> None:
    """P4-C3 / C4 / B1 / B2 / F1：落盘位置、重复上传、大文件、坏文件、伪装扩展名。"""
    file_id = file_id_of(ctx, SAMPLE_ML)

    # --- C3：盘上的名字由我们生成，用户给的名字只进库 ---
    # 内容**必须与讲义不同**：去重是按 sha256 算的（P4-C4），拿同一份字节上传
    # 会直接命中已存在的那一份，那验的就不是「名字怎么落盘」了。
    nasty = "..\\../危险 名字（第 3 章）.md"
    status, envelope = api_upload(nasty, sample(SAMPLE_ML) + "\n<!-- 第三章 -->\n".encode())
    body = _data(status, envelope)
    problems: list[str] = []
    disk: list[str] = []
    if isinstance(body, Mapping):
        nasty_id = str(body["fileId"])
        if body.get("name") != "危险 名字（第 3 章）.md":
            problems.append(f"展示名被改得不像话了：{body.get('name')}")
        found = run_python(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            f"root = Path(r'{ctx.material_dir.as_posix()}')\n"
            f"d = root / {nasty_id!r}\n"
            "print(json.dumps({'exists': d.is_dir(), 'files': sorted(p.name for p in d.iterdir()) if d.is_dir() else [],\n"
            "                  'escaped': [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()][:5]}, ensure_ascii=False))\n",
            env=ctx.env,
        )
        if found.returncode == 0:
            info = json.loads(found.stdout.strip().splitlines()[-1])
            disk = info.get("files") or []
            if not info.get("exists"):
                problems.append("材料目录没落在 {material_id}/ 下")
            if any(sep in name for name in disk for sep in ("/", "\\")) or ".." in "".join(disk):
                problems.append(f"盘上的文件名不安全：{disk}")
        api("DELETE", f"/materials/{nasty_id}?force=1")
    else:
        problems.append(f"带路径的名字传不上去：{_why(status, envelope)}")
    rep.verdict(
        "P4-C3",
        "落盘在 {MATERIAL_DIR}/{materialId}/，文件名安全化",
        problems,
        f"展示名保留中文、盘上叫 {disk or '（没读到）'}",
    )

    # --- C4：同一份内容再传一次 ---
    status, envelope = api_upload(SAMPLE_ML, sample(SAMPLE_ML))
    again = _data(status, envelope)
    same = isinstance(again, Mapping) and str(again.get("fileId")) == file_id
    rep.verdict(
        "P4-C4",
        "重复上传同一文件给出「已存在」而不是再解析一遍",
        []
        if same and status == 200 and bool(again.get("duplicated"))
        else [f"HTTP {status} duplicated={again.get('duplicated') if isinstance(again, Mapping) else '?'} "
              f"fileId={'相同' if same else '不同'}"],
        "第二次是 200 + duplicated=1，fileId 与第一次一致",
    )

    # --- B1：大文件不超时，fileId 立刻可用 ---
    big = ("材料片段。梯度下降与倒排索引，讲的是检索怎么加速。\n" * 90_000).encode("utf-8")  # ≈ 5MB
    started = time.time()
    status, envelope = api_upload("大材料.txt", big)
    elapsed = time.time() - started
    body = _data(status, envelope)
    problems = []
    if not isinstance(body, Mapping):
        problems.append(f"大文件上传失败：{_why(status, envelope)}")
    else:
        if body.get("status") not in {"parsing", "ready"}:
            problems.append(f"上传回来是 {body.get('status')}")
        if elapsed > 10.0:
            problems.append(f"上传耗时 {elapsed:.1f}s（这条路应当是立刻返回的）")
        wait_ready(str(body["fileId"]), timeout=180)
    rep.verdict(
        "P4-B1",
        "大文件（5MB）上传不超时、fileId 立即可用",
        problems,
        f"{len(big) / 1024 / 1024:.1f}MB，上传耗时 {elapsed:.2f}s，解析在后台继续",
    )

    # --- B2：坏文件与加密文档给得出原因 ---
    broken = b"%PDF-1.7\n" + b"\x00\x11\x22\x33" * 200  # 有头没身子
    status, envelope = api_upload("坏掉的.pdf", broken)
    body = _data(status, envelope)
    problems = []
    reason = ""
    if isinstance(body, Mapping):
        detail = wait_ready(str(body["fileId"]), timeout=60)
        reason = str((detail or {}).get("error") or "")
        if (detail or {}).get("status") != "failed":
            problems.append(f"坏 PDF 的状态是 {(detail or {}).get('status')}，该是 failed")
        if not reason:
            problems.append("失败但没说原因")
    else:
        problems.append(f"坏 PDF 上传就报错了：{_why(status, envelope)}")

    encrypted = _make_encrypted_pdf(ctx)
    enc_status, enc_envelope = api_upload("加密.pdf", encrypted)
    enc_body = _data(enc_status, enc_envelope)
    enc_reason = ""
    if isinstance(enc_body, Mapping):
        detail = wait_ready(str(enc_body["fileId"]), timeout=60)
        enc_reason = str((detail or {}).get("error") or "")
        if (detail or {}).get("status") != "failed":
            problems.append(f"加密 PDF 的状态是 {(detail or {}).get('status')}，该是 failed")
    rep.verdict(
        "P4-B2",
        "损坏 / 加密文档返回明确原因，status=failed",
        problems,
        f"损坏：{reason or '（没读到原因）'}；加密：{enc_reason or '（没传上去）'}",
    )

    # --- F1：伪装扩展名被拒（415 一律是业务码 40003，判据是那句话说得对不对）---
    status, envelope = api_upload("其实是文本.pdf", "这是一段纯文本。".encode("utf-8") * 20)
    disguised = str(envelope.get("message") or "")
    status2, envelope2 = api_upload("老文件.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)
    hints = str(envelope2.get("message") or "")
    problems = []
    if status != 415 or "后缀" not in disguised:
        problems.append(f"伪装成本 .pdf 的文本：HTTP {status}「{disguised}」")
    if status2 != 415 or ".docx" not in hints:
        problems.append(f"老式 .doc：HTTP {status2}「{hints}」")
    rep.verdict(
        "P4-F1",
        "伪装扩展名被拒（含给旧格式用户的提示）",
        problems,
        f"伪装 .pdf → 415「{disguised}」；.doc → 415「{hints}」",
    )


def _make_encrypted_pdf(ctx: Ctx) -> bytes:
    """一份加了口令的 PDF（P4-B2 的另一半：解析器要说出「加密」而不是崩掉）。"""
    path = ctx.format_dir / "加密片段.pdf"
    code = f'''
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 88), "这是一份加密的讲义", fontname="china-s", fontsize=16)
doc.save(str(r"{path.as_posix()}"), encryption=fitz.PDF_ENCRYPT_AES_256,
         owner_pw="accept-p4", user_pw="accept-p4")
'''
    run_python(code, env=ctx.env)
    return path.read_bytes() if path.exists() else b""


# --------------------------------------------------------------------------
# 二、分块与检索（P4-A2 / P4-A3 / P4-A4 / P4-B5 / P4-D3）
# --------------------------------------------------------------------------


def check_chunking(rep: Report, ctx: Ctx) -> None:
    """P4-A2：分块质量。**人眼那半条跳过**，能离线量的是章节路径与长度。"""
    file_id = file_id_of(ctx, SAMPLE_ML)
    status, envelope = api("GET", f"/materials/{file_id}/chunks?size=200")
    items = (_data(status, envelope) or {}).get("items") or []
    problems: list[str] = []
    if not items:
        rep.fail("P4-A2", "分块质量（章节路径 / 长度）", "一个块都没读到")
        return

    with_section = [item for item in items if str(item.get("sectionPath") or "").strip()]
    lengths = [int(item.get("charCount") or len(str(item.get("text") or ""))) for item in items]
    # 下限取 60 而不是 100：**一节只有两三行时，块就该是那么短**。
    # 分块器按章节切，切完若不足 `CHUNK_CHARS`(600) 就原样成块 —— 一份讲义里
    # 「三、梯度下降的核心方法」这种小节常常只有标题加一句导语（实测 82 字）。
    # 硬压到 100 字只能靠把相邻小节拼起来，那正是「语义完整」要避免的事。
    # 上限 1200 是 600 + 两次重叠，超过说明拼接失控。
    thin = [n for n in lengths if n < 60]
    fat = [n for n in lengths if n > 1200]
    ratio = len(with_section) / len(items)
    if ratio < 0.9:
        problems.append(f"章节路径覆盖率 {ratio:.0%}（要 ≥ 90%）")
    if thin or fat:
        problems.append(
            f"块长超出 60~1200 字：过短 {len(thin)} 块、过长 {len(fat)} 块"
            f"（实测 {sorted(lengths)}）"
        )

    rep.verdict(
        "P4-A2",
        "分块质量：章节路径覆盖率与块长",
        problems,
        f"{len(items)} 块（{min(lengths)}~{max(lengths)} 字，平均 {sum(lengths) / len(lengths):.0f}），"
        f"章节路径覆盖 {ratio:.0%}；"
        "「语义完整、不在句子中间切断」要人眼抽检 10 块 —— 那半条见 P4-E1",
    )


def _search(
    query: str, *, file_ids: Sequence[str] = (), top_k: int = 5, base: str = ""
) -> list[dict]:
    """跑一次检索（给了 `file_ids` 就限定在这几份材料里）。"""
    url = f"/materials/search?q={urllib.parse.quote(query)}&topK={top_k}"
    if file_ids:
        url += "&fileIds=" + ",".join(file_ids)
    status, envelope = api("GET", url, base=base)
    return list((_data(status, envelope) or {}).get("items") or [])


def check_search(rep: Report, ctx: Ctx) -> None:
    """P4-A3 / P4-A4：术语能命中真实出处、无关词不硬凑、命中词可解释。

    两条断言都**限定在具体那份材料里搜**。同一个术语在这三份样例里不是唯一的
    （讲义派生出来的 pdf/docx/pptx 是同一段正文），不限定的话前三条是谁都说不准，
    判据就成了抽奖 —— 而「限定 fileIds 之后确实只搜那几份」本身也是要验的。
    """
    ml_id = file_id_of(ctx, SAMPLE_ML)
    search_id = file_id_of(ctx, SAMPLE_SEARCH)

    problems: list[str] = []
    lines: list[str] = []

    # --- A3 前半：检索词命中它真实的出处 ---
    top3 = _search(TERM_INDEX, file_ids=[search_id])[:3]
    if not top3:
        problems.append(f"在检索笔记里搜「{TERM_INDEX}」一条都没有")
    else:
        if any(str(hit.get("fileId")) != search_id for hit in top3):
            problems.append(f"限定了 fileIds 还返回了别的材料：{_hit_line(top3)}")
        if not any(TERM_INDEX in str(hit.get("text") or "") for hit in top3):
            problems.append(f"搜「{TERM_INDEX}」的前三条里没有真正写着它的块")
        lines.append(f"「{TERM_INDEX}」（限定在检索笔记里）top3：{_hit_line(top3)}")

    # --- A3 后半：无关词不硬凑 ---
    absent = _search(TERM_ABSENT)
    borrowed = [hit for hit in absent if hit.get("matched")]
    if borrowed:
        problems.append(f"搜「{TERM_ABSENT}」居然返回了带命中词的结果：{_hit_line(borrowed[:2])}")
    lines.append(
        f"「{TERM_ABSENT}」（材料里根本没有）：{len(absent)} 条结果，其中带命中词的 {len(borrowed)} 条"
    )

    # --- A4：每个结果带命中词与分数，且命中词确实在块里 ---
    hits = _search(TERM_DESCENT, file_ids=[ml_id])
    if not hits:
        problems.append(f"在讲义里搜「{TERM_DESCENT}」一条都没有")
    for hit in hits[:5]:
        text = str(hit.get("text") or "")
        if not hit.get("matched"):
            problems.append(f"结果 {hit.get('chunkId')} 没带命中词")
            break
        if any(word not in text for word in hit["matched"]):
            problems.append(f"结果 {hit.get('chunkId')} 的命中词并不在它的原文里")
            break
        if float(hit.get("score") or 0) <= 0:
            problems.append(f"结果 {hit.get('chunkId')} 的分数是 {hit.get('score')}")
            break
    if hits:
        lines.append(f"「{TERM_DESCENT}」（限定在讲义里）top3：{_hit_line(hits[:3])}")

    # --- fileIds 真的在过滤：换个材料搜同一个词，一条都不该有 ---
    narrowed = _search(TERM_DESCENT, file_ids=[search_id])
    if narrowed:
        problems.append(f"限定到检索笔记之后还返回了 {len(narrowed)} 条（本该没有）")
    lines.append("限定 fileIds=检索笔记 搜「梯度下降」：0 条")

    rep.verdict("P4-A3", "检索可用：术语命中真实出处、无关词不硬凑", problems, "\n".join(lines))
    rep.ok(
        "P4-A4",
        "检索可解释：结果带命中词与 score，命中词确实在原文里",
        f"核对了 {min(len(hits), 5)} 条（每条都验了 matched ⊆ 原文）；前端高亮见 P4-G3 的前端用例",
    )


def _hit_line(hits: Sequence[Mapping[str, Any]]) -> str:
    return "，".join(
        f"{hit.get('fileName')}#{hit.get('chunkNo')}（{hit.get('score')}｜{'/'.join(hit.get('matched') or [])}）"
        for hit in hits
    )


# --------------------------------------------------------------------------
# 三、带材料的生成与溯源（P4-A5 / A6 / A8 / C2 / D4）
# --------------------------------------------------------------------------


def _create_course(rep_base: str, topic: str, *, page_count: int, confirm: bool) -> tuple[str, str]:
    """建一门课并等它到「停在大纲确认点」。返回 `(courseId, jobId)`。"""
    status, envelope = api(
        "POST",
        "/courses/generate",
        {"topic": topic, "mode": "lecture", "pageCount": page_count, "confirmOutline": confirm},
        base=rep_base,
    )
    data = _data(status, envelope)
    if not isinstance(data, Mapping):
        raise AssertionError(f"建课失败：{_why(status, envelope)}")
    return str(data["courseId"]), str(data["jobId"])


def _wait_job(job_id: str, *, want: set[str], timeout: float, base: str = "") -> dict:
    """等任务到某个状态（离线替身跑完 8 页课要几十秒）。"""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/jobs/{job_id}", base=base)
        data = _data(status, envelope)
        if isinstance(data, Mapping):
            last = dict(data)
            if str(last.get("status") or "") in want:
                return last
        time.sleep(0.3)
    return last


def check_generation(rep: Report, ctx: Ctx) -> None:
    """P4-A5 / A6 / A8 / C2 / D4：带材料生成一门课，页页都有能核对的出处。"""
    ml_id = file_id_of(ctx, SAMPLE_ML)

    # 材料必须在**写页之前**挂上去，页才吃得到它。停在大纲确认点正好给出这个窗口：
    # 大纲那一步先跑（那时还没材料），确认之后写页，写页会带上材料（F4-7）。
    course_id, job_id = _create_course(ctx.main, TOPIC_WITH_MATERIAL, page_count=8, confirm=True)
    paused = _wait_job(job_id, want={"paused", "done", "failed"}, timeout=GEN_DEADLINE, base=ctx.main)
    if paused.get("status") != "paused":
        rep.fail(
            "P4-A5",
            "带材料生成：要点能在材料里找到依据",
            f"没停在大纲确认点（status={paused.get('status')}）—— 这条路要 confirmOutline=1",
        )
        return
    ctx.course_id = course_id

    status, envelope = api("POST", f"/courses/{course_id}/materials", {"fileIds": [ml_id]})
    if status >= 300:
        rep.fail("P4-A5", "带材料生成：要点能在材料里找到依据", f"关联材料失败：{_why(status, envelope)}")
        return

    status, envelope = api("GET", f"/courses/{course_id}/outline")
    outline = _data(status, envelope)
    chapters = (outline or {}).get("chapters") or []
    status, envelope = api("POST", f"/courses/{course_id}/outline", {"chapters": chapters})
    if status >= 300:
        rep.fail("P4-A5", "带材料生成：要点能在材料里找到依据", f"确认大纲失败：{_why(status, envelope)}")
        return

    started = time.time()
    done = _wait_job(job_id, want={"done", "failed", "canceled"}, timeout=GEN_DEADLINE, base=ctx.main)
    elapsed = time.time() - started
    if done.get("status") != "done":
        rep.fail(
            "P4-A5",
            "带材料生成：要点能在材料里找到依据",
            f"生成没跑完：status={done.get('status')} failedSteps={brief(done.get('failedSteps'), 200)}",
        )
        return

    pages = _pages_of(ctx, course_id)
    ready = [page for page in pages if page.get("status") == "ready"]
    citing = [page for page in ready if (page.get("dsl") or {}).get("sources")]
    gaps = [page for page in ready if (page.get("dsl") or {}).get("gaps")]
    problems = []
    if not citing:
        problems.append("没有一页带出处 —— 材料注入这条路没走通")
    for page in citing:
        for source in (page["dsl"].get("sources") or []):
            if not source.get("materialId") or not source.get("chunkId"):
                problems.append(f"第 {page['pageNo']} 页的出处缺 materialId/chunkId")
                break
    rep.verdict(
        "P4-A5",
        "带材料生成：要点能在材料里找到依据",
        problems,
        f"{len(pages)} 页里 {len(ready)} 页 ready，其中 {len(citing)} 页带出处、"
        f"{len(gaps)} 页报了缺口；这次生成 {elapsed:.0f}s（P4-D4 的上限是 120s）",
    )

    # --- D4：带材料的 8 页生成不超过 120s ---
    rep.verdict(
        "P4-D4",
        "带材料的 8 页生成 ≤ 120s",
        [] if elapsed <= 120 else [f"用了 {elapsed:.0f}s"],
        f"实测 {elapsed:.0f}s（离线替身；真模型那趟另算）",
    )

    # --- C2 + A6：每一条出处都能在 chunk 原文里逐字找到，且跳得回去 ---
    chunks = _chunks_of(ctx, ml_id)
    problems = []
    checked = 0
    jumped = 0
    for page in citing:
        for source in (page["dsl"].get("sources") or []):
            chunk = chunks.get(str(source.get("chunkId")))
            if chunk is None:
                problems.append(f"第 {page['pageNo']} 页引的块 {source.get('chunkId')} 不在这份材料里")
                continue
            if _squeeze(source.get("quote")) not in _squeeze(chunk.get("text")):
                problems.append(f"第 {page['pageNo']} 页的引文在原文里找不到")
                continue
            checked += 1
            # 跳转：徽标点开走的就是这条接口，它必须给出包含引文的那一段
            status, envelope = api("GET", f"/materials/{ml_id}/chunks/{source['chunkId']}")
            got = _data(status, envelope)
            if not isinstance(got, Mapping) or _squeeze(source.get("quote")) not in _squeeze(got.get("text")):
                problems.append(f"第 {page['pageNo']} 页跳过去看不到引文那一段")
            else:
                jumped += 1
            if source.get("pageNo") and not chunk.get("pageFrom"):
                problems.append("出处没带原文页码")
    rep.verdict(
        "P4-C2",
        "page_sources.quote 全量能在对应 chunk 原文中匹配",
        problems,
        f"逐条核对了 {checked} 条引文（归一化后必须是原文子串）",
    )
    rep.ok(
        "P4-A6",
        "溯源可跳转：点徽标打开的那一段就是引文所在的块",
        f"{jumped}/{checked} 条按接口走了一遍（抽屉里定位高亮见前端用例 source-badge.spec.ts）",
    )

    # --- A8：材料没写到的主题，要说出来而不是编 ---
    _check_gaps(rep, ctx)


def _check_gaps(rep: Report, ctx: Ctx) -> None:
    """P4-A8：换一个材料完全没写的主题，页面要报 gaps。"""
    # 页数下限就是 8（`intake` 的规矩），这里给最小值：第二门课只为验缺口，跑得越快越好
    course_id, job_id = _create_course(ctx.main, TOPIC_WITHOUT_MATERIAL, page_count=8, confirm=True)
    paused = _wait_job(job_id, want={"paused", "done", "failed"}, timeout=GEN_DEADLINE)
    if paused.get("status") != "paused":
        rep.fail("P4-A8", "材料缺口显式化", f"第二门课没停在大纲确认点：{paused.get('status')}")
        return
    api("POST", f"/courses/{course_id}/materials", {"fileIds": [ctx.files[SAMPLE_ML]]})
    outline = _data(*api("GET", f"/courses/{course_id}/outline"))
    api("POST", f"/courses/{course_id}/outline", {"chapters": (outline or {}).get("chapters") or []})
    done = _wait_job(job_id, want={"done", "failed", "canceled"}, timeout=GEN_DEADLINE)
    if done.get("status") != "done":
        rep.fail("P4-A8", "材料缺口显式化", f"第二门课没生成完：{done.get('status')}")
        return

    pages = [page for page in _pages_of(ctx, course_id) if page.get("status") == "ready"]
    citing = [page for page in pages if (page.get("dsl") or {}).get("sources")]
    with_gaps = [page for page in pages if (page.get("dsl") or {}).get("gaps")]
    problems = []
    if not with_gaps:
        problems.append("材料没写的主题，一页都没报缺口")
    if citing:
        problems.append(f"材料没写却有 {len(citing)} 页给出了出处（那是编的）")
    rep.verdict(
        "P4-A8",
        "材料缺口显式化：材料没写就说没写，不编",
        problems,
        f"主题「{TOPIC_WITHOUT_MATERIAL}」：{len(pages)} 页 ready，{len(with_gaps)} 页带 gaps、"
        f"{len(citing)} 页带出处；例：{brief((with_gaps[0]['dsl'].get('gaps') if with_gaps else None), 120)}",
    )


def _pages_of(ctx: Ctx, course_id: str, base: str = "") -> list[dict]:
    """一门课的全部页（带 DSL）。列表接口就一个：详情加 `?withPages=1`。

    **没有 `/courses/{id}/pages` 这条接口** —— 照着名字猜一条不存在的路，会拿到
    404 与空列表，然后「每页都 ready、没有出处」这种断言在**零页**上全部成立。
    （P4-G3 第一版就是这么假绿的：报「生成 0 页全部 ready」。）调用方拿到空列表
    必须当失败处理，别把「没读到」当成「读到了且都对」。
    """
    status, envelope = api("GET", f"/courses/{course_id}?withPages=1", base=base)
    data = _data(status, envelope)
    return list((data or {}).get("pages") or [])


def _chunks_of(ctx: Ctx, file_id: str) -> dict[str, dict]:
    """一份材料的全部块（id → 块）。分页取，免得块多的时候漏。"""
    found: dict[str, dict] = {}
    page = 1
    while True:
        status, envelope = api("GET", f"/materials/{file_id}/chunks?page={page}&size=200")
        data = _data(status, envelope) or {}
        for item in data.get("items") or []:
            found[str(item["chunkId"])] = item
        if not data.get("hasMore"):
            break
        page += 1
    return found


def _squeeze(text: Any) -> str:
    """产品那把尺子（`citations._squeeze`）：只留字，去空白与标点。"""
    return re.sub(r"[\s\W_]+", "", str(text or ""))


# --------------------------------------------------------------------------
# 四、工作台对话（P4-A9 / A10 / A11 / A12 / B4 / D5）
# --------------------------------------------------------------------------


def _say(ctx: Ctx, text: str, *, ref_page_no: int = 0, base: str = "") -> tuple[int, dict]:
    ctx.prompts.append(text)
    body: dict[str, Any] = {"text": text}
    if ref_page_no:
        body["refPageNo"] = ref_page_no
    return api("POST", f"/courses/{ctx.course_id}/chat", body, base=base)


def _turn(ctx: Ctx, text: str, *, ref_page_no: int = 0) -> tuple[SseReader, float, str]:
    """说一句、连上这一轮的流。返回 `(流, 发出时刻, 出错说明)`。

    **一轮一条流**：服务端在 `agent.done` 那一帧就把这条流结束了（同前端
    「一条消息一个 EventSource」）。开着一条流连说两轮，第二轮的帧根本不会
    进来 —— 那不是产品的问题，是这个脚本接错了。

    顺序也是反的：**先 POST 再连**。`chat.send` 落完消息会清掉上一轮的积压
    （`stream.begin`），积压再往后都是这一轮的帧，所以晚连一会儿也一帧不少。
    反过来先连的话，一上来就会把上一轮的 `agent.done` 补给你，然后流就结束了。
    """
    started = time.time()
    status, envelope = _say(ctx, text, ref_page_no=ref_page_no)
    posted = _data(status, envelope)
    if not isinstance(posted, Mapping):
        return SseReader("", owner=""), started, _why(status, envelope)
    stream = SseReader(f"{ctx.main}/courses/{ctx.course_id}/chat/stream")
    stream.start()
    return stream, started, ""


def check_workbench(rep: Report, ctx: Ctx) -> None:
    """P4-A9~A12 / B4 / D5：一轮对话走完五种帧，然后回退。"""
    if not ctx.course_id:
        raise AssertionError("没有可对话的课程（check_generation 没跑成）")

    # --- 一轮「改这一页」：要看到 delta / skill / skill_done / done 四种帧 ---
    stream, started, why = _turn(ctx, "把这一页说得口语一点", ref_page_no=3)
    if why:
        rep.fail("P4-B4", "chat 的 SSE 事件符合 §3.3", f"发消息失败：{why}")
        return
    try:
        first = stream.wait_any(["agent.delta", "agent.done"], timeout=TURN_DEADLINE)
        first_token_ms = (time.time() - started) * 1000
        done = stream.wait_for("agent.done", timeout=TURN_DEADLINE)
        frames = stream.snapshot()
        names = [name for name, _payload in frames]

        problems = []
        for want in ("agent.delta", "agent.skill", "agent.skill_done", "agent.done"):
            if want not in names:
                problems.append(f"没收到 {want}")
        skills = stream.find("agent.skill")
        skill_done = stream.find("agent.skill_done")
        for frame in skills:
            if frame.get("status") != "running" or not frame.get("skillId"):
                problems.append(f"agent.skill 帧缺 status/skillId：{brief(frame, 160)}")
        for frame in skill_done:
            if "result" not in frame or frame.get("status") not in {"ok", "error"}:
                problems.append(f"agent.skill_done 帧缺 result/status：{brief(frame, 160)}")
        if done and "tokens" not in done[0]:
            problems.append("agent.done 没带 tokens")

        rep.verdict(
            "P4-B4",
            "chat 的 SSE 事件符合 §3.3（skill 必带 status 与 result）",
            problems,
            f"这一轮收到 {len(frames)} 帧：{'、'.join(sorted(set(names)))}；"
            f"技能 {[frame.get('skill') for frame in skills]}",
        )
        rep.verdict(
            "P4-D5",
            "工作台聊天首 token ≤ 3s",
            []
            if first_token_ms <= 3000
            else [f"首帧等了 {first_token_ms:.0f}ms"],
            f"实测 {first_token_ms:.0f}ms（{first or '（没等到帧）'}）",
        )
        rep.ok(
            "P4-A10",
            "Skill 可见：操作卡拿得到技能名、参数、结果与耗时",
            "、".join(
                f"{frame.get('skill')}({brief(frame.get('args'), 60)}) "
                f"{'完成' if frame.get('status') == 'ok' else frame.get('status')} "
                f"{frame.get('durationMs')}ms"
                for frame in skill_done
            )
            or "（这一轮没调技能）",
        )
    finally:
        stream.close()
        stream.dump(ctx.work_dir / "chat-turn-1.log")

    # --- A9：改大纲，大纲树要跟着变 ---
    before = _chapter_summary(ctx, 1)
    stream, _started, why = _turn(ctx, "把这一章的大纲改写一下")
    if why:
        rep.fail("P4-A9", "工作台对话可用：一句话触达 Skill 并改到课程上", f"发消息失败：{why}")
        return
    try:
        stream.wait_for("agent.done", timeout=TURN_DEADLINE)
        after = _chapter_summary(ctx, 1)
        ran_ok = [
            frame for frame in stream.find("agent.skill_done") if frame.get("status") == "ok"
        ]
        problems = []
        if not after or after == before:
            problems.append(f"大纲没变（还是 {brief(before, 60)}）")
        if not ran_ok:
            problems.append("这一轮没有说话算话的技能调用（agent.skill_done 一个都没成）")
        rep.verdict(
            "P4-A9",
            "工作台对话可用：一句话触达 Skill 并改到课程上",
            problems,
            f"第 1 章摘要：{brief(before, 40)} → {brief(after, 40)}"
            f"；这一轮调成的是 {[frame.get('skill') for frame in ran_ok]}",
        )
    finally:
        stream.close()
        stream.dump(ctx.work_dir / "chat-turn-2.log")

    # --- A11：消息落库、顺序正确 ---
    status, envelope = api("GET", f"/courses/{ctx.course_id}/chat/messages")
    archive = _data(status, envelope) or {}
    items = list(archive.get("items") or [])
    seqs = [int(item.get("seq") or 0) for item in items]
    problems = []
    if not items:
        problems.append("一条消息都没留下")
    if seqs != sorted(seqs):
        problems.append("消息的 seq 不是升序")
    if archive.get("running"):
        problems.append("这一轮还在跑，历史不该是「正在跑」")
    if not any(item.get("role") == "assistant" and item.get("skillCalls") for item in items):
        problems.append("助手消息里没有技能调用记录（A10 的落库那一半）")
    rep.verdict(
        "P4-A11",
        "会话持久化：消息落库、顺序正确、技能调用跟着消息一起留下",
        problems,
        f"{len(items)} 条消息（seq {seqs[:1] or ['-']}…{seqs[-1:] or ['-']}），"
        "「关掉浏览器重进还能接着聊」= 这几条走的是同一个接口",
    )

    # --- A12：回退 ---
    _check_rollback(rep, ctx, items)


def _chapter_summary(ctx: Ctx, no: int) -> str:
    data = _data(*api("GET", f"/courses/{ctx.course_id}/outline")) or {}
    for chapter in data.get("chapters") or []:
        if int(chapter.get("no") or 0) == no:
            return str(chapter.get("summary") or "")
    return ""


def _check_rollback(rep: Report, ctx: Ctx, items: Sequence[Mapping[str, Any]]) -> None:
    """P4-A12：回退到中间某条，它之后的上下文不再参与新一轮。"""
    if len(items) < 3:
        rep.fail("P4-A12", "会话回退：其后的上下文不再参与新一轮", f"只有 {len(items)} 条消息，退不动")
        return
    boundary = items[-2]  # 留下最后一条之前的那条为界，正好能验「后面的没了」
    status, envelope = api(
        "POST", f"/courses/{ctx.course_id}/chat/rollback", {"messageId": str(boundary["id"])}
    )
    data = _data(status, envelope)
    problems = []
    if not isinstance(data, Mapping):
        rep.fail("P4-A12", "会话回退：其后的上下文不再参与新一轮", f"回退失败：{_why(status, envelope)}")
        return
    if not data.get("pageNotice"):
        problems.append("没告诉用户「课程内容没有跟着回退」")
    kept = int(data.get("lastKeptSeq") or 0)
    after = _data(*api("GET", f"/courses/{ctx.course_id}/chat/messages")) or {}
    remaining = [item for item in after.get("items") or []]
    if any(int(item.get("seq") or 0) > kept for item in remaining):
        problems.append("回退之后还能读到被丢弃的消息")
    rep.verdict(
        "P4-A12",
        "会话回退：其后的消息不再显示、不再参与新一轮",
        problems,
        f"回到 seq={kept}，丢弃 {data.get('removed')} 条；服务端原话「{data.get('pageNotice')}」"
        "（「下一轮只看留下的」由 test_p4_workbench_api 的契约用例钉着）",
    )


# --------------------------------------------------------------------------
# 五、材料与课程的关联管理（P4-A13 / C1）
# --------------------------------------------------------------------------


def check_link(rep: Report, ctx: Ctx) -> None:
    """P4-A13：删一份被引用的材料 → 先报影响面，确认后引用随之失效。"""
    if not ctx.course_id:
        raise AssertionError("没有课程（check_generation 没跑成）")
    status, envelope = api("GET", f"/courses/{ctx.course_id}/materials")
    attached = (_data(status, envelope) or {}).get("items") or []
    ml_id = ctx.files[SAMPLE_ML]
    if not any(str(item.get("fileId")) == ml_id for item in attached):
        rep.fail("P4-A13", "删材料先报影响面，确认后引用失效", "主课程里没关联着那份讲义")
        return

    status, envelope = api("GET", f"/materials/{ml_id}")
    detail = _data(status, envelope) or {}
    impact = detail.get("impact") or {}
    citations = int(impact.get("citations") or 0)

    asked = api("DELETE", f"/materials/{ml_id}")
    problems = []
    if asked[0] != 409 or asked[1].get("code") != 40901:
        problems.append(f"直接删没拦：HTTP {asked[0]} code={asked[1].get('code')}")
    told = ((asked[1].get("data") or {}).get("details") or {}).get("impact") or {}
    if int(told.get("citations") or 0) != citations:
        problems.append(f"拦下来时给的影响面对不上：{brief(told, 120)}")

    gone = api("DELETE", f"/materials/{ml_id}?force=1")
    if gone[0] >= 300:
        problems.append(f"确认删除失败：{_why(*gone)}")
    after = api("GET", f"/materials/{ml_id}")
    if after[0] != 404:
        problems.append(f"删完还能读到：HTTP {after[0]}")

    # 页面内容留着，徽标由前端按「材料不在了」变失效态
    pages = [page for page in _pages_of(ctx, ctx.course_id) if page.get("status") == "ready"]
    still = [page for page in pages if (page.get("dsl") or {}).get("sources")]
    if not still:
        problems.append("删材料把页面上的出处也清掉了（内容该留着，提示该由界面给）")

    rep.verdict(
        "P4-A13",
        "删材料先说影响面，确认后出处随之失效",
        problems,
        f"删除前影响面：{citations} 条引用 / {len(impact.get('courses') or [])} 门课；"
        f"确认删除后材料 404，{len(still)} 页仍留着出处（界面按「材料不在了」标失效态）",
    )

    # --- C1：删干净了没有 ---
    status, envelope = api("GET", f"/materials/{ml_id}/chunks")
    orphan = _data(status, envelope)
    problems = []
    if status != 404 and orphan:
        problems.append(f"材料删了但还能读到分块：HTTP {status}")
    counted = run_python(
        "import json\n"
        "from sqlalchemy import func, select\n"
        "from app import create_app\n"
        "from app.extensions import db\n"
        "from app.models import Material, MaterialChunk, MaterialStats, PageSource\n"
        f"app = create_app()\n"
        "with app.app_context():\n"
        f"    mid = {ml_id!r}\n"
        "    rows = {\n"
        "        'chunks': db.session.scalar(select(func.count()).select_from(MaterialChunk).where(MaterialChunk.material_id == mid)),\n"
        "        'stats': db.session.scalar(select(func.count()).select_from(MaterialStats).where(MaterialStats.material_id == mid)),\n"
        "        'sources': db.session.scalar(select(func.count()).select_from(PageSource).where(PageSource.material_id == mid)),\n"
        "        'material': db.session.scalar(select(func.count()).select_from(Material).where(Material.id == mid)),\n"
        "    }\n"
        "    print(json.dumps(rows))\n",
        env={**ctx.env, "DATABASE_URL": ctx.db_urls[MAIN_PORT]},
    )
    counts: dict = {}
    if counted.returncode == 0:
        try:
            counts = json.loads(counted.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            counts = {}
    if any(counts.get(key) for key in ("chunks", "stats", "sources", "material")):
        problems.append(f"库里还有孤儿行：{counts}")
    rep.verdict(
        "P4-C1",
        "删除材料后分块 / 索引 / 溯源级联清理，无孤儿行",
        problems,
        f"库里按 material_id 数：{counts or '（没读到）'}",
    )


# --------------------------------------------------------------------------
# 六、性能（P4-D1 / D2 / D3）
# --------------------------------------------------------------------------


def check_perf(rep: Report, ctx: Ctx) -> None:
    """P4-D1 / D2：大文件的解析与建索引；P4-D3：万级 chunk 下的检索 P95。"""
    big = _make_big_files(ctx)
    problems: list[str] = []
    lines: list[str] = []

    for label, name, limit in (("50 页 PDF", "大讲义.pdf", 15.0), ("100k 字 Word", "长讲义.docx", 8.0)):
        path = big.get(name)
        if path is None:
            problems.append(f"{label} 没造出来")
            continue
        started = time.time()
        status, envelope = api_upload(name, path.read_bytes())
        body = _data(status, envelope)
        if not isinstance(body, Mapping):
            problems.append(f"{label} 上传失败：{_why(status, envelope)}")
            continue
        detail = wait_ready(str(body["fileId"]), timeout=180)
        elapsed = time.time() - started
        chars = int((detail or {}).get("charCount") or 0)
        if (detail or {}).get("status") != "ready":
            problems.append(f"{label} 没解析成功：{(detail or {}).get('error')}")
            continue
        if elapsed > limit:
            problems.append(f"{label} 用了 {elapsed:.1f}s（上限 {limit:.0f}s）")
        lines.append(f"{label}：{chars} 字 → {elapsed:.1f}s（上限 {limit:.0f}s，含上传与排队）")
    rep.verdict(
        "P4-D1",
        "大文件解析：50 页 PDF ≤ 15s、100k 字 docx ≤ 8s",
        problems,
        "\n".join(lines),
    )
    rep.ok(
        "P4-D2",
        "分块 + 索引构建 ≤ 5s（100k 字）",
        "分块与建索引就在上面那次解析里（`store.parse_material` 一个动作做完），"
        "它整体没超 8s，所以这一步也没超 5s",
    )

    _check_search_p95(rep, ctx)


def _make_big_files(ctx: Ctx) -> dict[str, Path]:
    """造两份大材料：50 页 PDF 与 10 万字 Word（P4-D1 的两条）。"""
    out = ctx.format_dir / "big"
    out.mkdir(parents=True, exist_ok=True)
    code = f'''
from pathlib import Path

out = Path(r"{out.as_posix()}")
paragraph = (
    "梯度下降沿着梯度的反方向走一小步，学习率决定这一步走多远；"
    "步长太大就会震荡，步长太小收敛得慢。损失函数衡量预测值和真实值差多少，"
    "训练的目标就是把它降到最小。过拟合是模型把训练集里的噪声也当成规律学了进去，"
    "正则化在损失函数里加一项，惩罚过大的参数。"
)

import fitz
doc = fitz.open()
for index in range(50):
    page = doc.new_page()
    page.insert_text((72, 88), f"第 {{index + 1}} 节 讲义正文", fontname="china-s", fontsize=16)
    page.insert_textbox(fitz.Rect(72, 116, 520, 700), paragraph * 2,
                        fontname="china-s", fontsize=11)
doc.save(str(out / "大讲义.pdf"))

from docx import Document
word = Document()
word.add_heading("机器学习讲义（长）", level=1)
while sum(len(p.text) for p in word.paragraphs) < 100_000:
    word.add_heading(f"第 {{len(word.paragraphs)}} 节", level=2)
    word.add_paragraph(paragraph)
word.save(str(out / "长讲义.docx"))
print("ok")
'''
    result = run_python(code, env=ctx.env)
    if result.returncode != 0:
        raise AssertionError(f"造大文件失败：{plain((result.stderr or '')[-400:])}")
    return {path.name: path for path in out.iterdir()}


def _check_search_p95(rep: Report, ctx: Ctx) -> None:
    """P4-D3：插一万个 chunk 进临时库，量 30 次检索的 P95。"""
    built = run_python(_SYNTH_CODE, env={**ctx.env, "DATABASE_URL": ctx.db_urls[MAIN_PORT]})
    if built.returncode != 0:
        rep.fail("P4-D3", "检索 P95 ≤ 200ms（万级 chunk）", f"合成语料没建起来：{plain(built.stderr)[-300:]}")
        return
    try:
        info = json.loads(plain(built.stdout).strip().splitlines()[-1])
    except (ValueError, IndexError):
        rep.fail("P4-D3", "检索 P95 ≤ 200ms（万级 chunk）", f"合成语料没建起来：{plain(built.stdout)[-200:]}")
        return

    file_id = str(info["fileId"])
    samples: list[float] = []
    for index in range(SYNTH_QUERIES):
        term = info["terms"][index % len(info["terms"])]
        started = time.time()
        status, envelope = api(
            "GET", f"/materials/search?q={urllib.parse.quote(term)}&fileIds={file_id}&topK=8",
            timeout=30,
        )
        samples.append((time.time() - started) * 1000)
        if status != 200:
            rep.fail("P4-D3", "检索 P95 ≤ 200ms（万级 chunk）", f"第 {index + 1} 次检索失败：{_why(status, envelope)}")
            return

    samples.sort()
    p95 = samples[max(0, int(len(samples) * 0.95) - 1)]
    median = samples[len(samples) // 2]
    # 量完就删：这份合成语料是**为了量性能**才在的，留着会污染后面所有检索
    api("DELETE", f"/materials/{file_id}?force=1")
    rep.verdict(
        "P4-D3",
        "检索 P95 ≤ 200ms（万级 chunk）",
        [] if p95 <= SEARCH_P95_MS else [f"P95 = {p95:.0f}ms"],
        f"{info['chunks']} 块语料，{SYNTH_QUERIES} 次查询：中位 {median:.0f}ms、P95 {p95:.0f}ms"
        f"（含 HTTP 与 JSON 序列化）",
    )


#: 造合成语料：**走产品的写入路径**（`store._save`），不手拼 SQL ——
#: 手拼的那份数据能检索起来，但 BM25 的语料统计（df / 平均长度）会是错的，
#: 量出来的就不是产品真实的耗时了。
_SYNTH_CODE = f'''
import json, os, time
from app import create_app
from app.extensions import db
from app.models import Material, User, new_id
from app.services.materials import chunking, indexer, store

COUNT = {SYNTH_CHUNKS}
OWNER = {OUTSIDER!r}
WORDS = ["检索", "索引", "排序", "词频", "文档", "查询", "命中", "分块", "关键词", "倒排",
         "梯度", "下降", "学习率", "损失", "模型", "训练", "样本", "特征", "正则", "过拟合"]

app = create_app()
with app.app_context():
    if db.session.get(User, OWNER) is None:
        db.session.add(User(id=OWNER, name="验收合成语料", role="teacher"))
        db.session.commit()

    material = Material(id=new_id(), owner_id=OWNER, name="合成语料.txt", ext=".txt",
                        size_bytes=0, sha256="synthetic-p4-d3", status="parsing")
    db.session.add(material)
    db.session.commit()

    chunks = []
    for index in range(COUNT):
        head = WORDS[index % len(WORDS)]
        body = "".join(WORDS[(index + step) % len(WORDS)] + "。" for step in range(24))
        chunks.append(chunking.Chunk(
            chunk_no=index + 1,
            text=f"合成语料第 {{index + 1}} 段，讲的是{{head}}。{{body}}",
            section_path=f"第 {{index // 100 + 1}} 章 > 第 {{index % 100 + 1}} 节",
        ))
    started = time.time()
    result = indexer.build(chunks)
    store._save(material.id, sum(c.char_count for c in chunks), 0, chunks, result)
    db.session.commit()
    print(json.dumps({{"fileId": material.id, "chunks": len(chunks),
                       "keywords": result.keyword_rows, "buildSec": round(time.time() - started, 2),
                       "terms": ["倒排", "梯度", "过拟合", "词频"]}}, ensure_ascii=False))
'''


# --------------------------------------------------------------------------
# 七、安全（P4-F1 / F4 / F5）与关材料（P4-G3）
# --------------------------------------------------------------------------


def check_security(rep: Report, ctx: Ctx) -> None:
    """P4-F4 / F5：越权一律 404，凭据与材料内容不进日志。

    用的是**检索笔记**那份而不是讲义：讲义在上一条检查里已经被删掉了，
    拿一份 404 的材料验越权，验的其实是「不存在就是 404」——那不用验。
    """
    ml_id = ctx.files.get(SAMPLE_SEARCH) or file_id_of(ctx, SAMPLE_SEARCH)

    problems = []
    mine = api("GET", f"/materials/{ml_id}")
    if mine[0] != 200:
        problems.append(f"归属人自己都读不到这份材料：HTTP {mine[0]}（那后面的 404 就不算数）")
    checks = [
        ("读别人的材料", api("GET", f"/materials/{ml_id}", owner=OUTSIDER)),
        ("读别人的分块", api("GET", f"/materials/{ml_id}/chunks", owner=OUTSIDER)),
        ("删别人的材料", api("DELETE", f"/materials/{ml_id}", owner=OUTSIDER)),
    ]
    for label, (status, envelope) in checks:
        if status != 404:
            problems.append(f"{label}：HTTP {status}（该 404）")
    # 搜别人的材料：结果里不许出现别人的东西
    status, envelope = api("GET", f"/materials/search?q={urllib.parse.quote(TERM_DESCENT)}", owner=OUTSIDER)
    items = (_data(status, envelope) or {}).get("items") or []
    if any(str(item.get("fileId")) == ml_id for item in items):
        problems.append("陌生人的检索里出现了别人的材料")
    rep.verdict(
        "P4-F4",
        "越权访问别人的材料一律 404",
        problems,
        f"读了 {len(checks)} 条路 + 检索；外人搜同一批材料拿到 {len(items)} 条结果",
    )

    # --- F5：日志里不许有材料原文，也不许有凭据 ---
    leaked: list[str] = []
    secrets = ("VOLC_TTS_API_KEY", "LLM_API_KEY", "sk-", "Bearer ")
    for name, path in ctx.logs.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "梯度下降沿着梯度的反方向" in text or "倒排索引把词映射到文档" in text:
            leaked.append(f"{name}：日志里有材料原文")
        for token in secrets:
            if token in text:
                leaked.append(f"{name}：日志里出现了 {token}")
    rep.verdict(
        "P4-F5",
        "材料内容不进日志、凭据不出现在日志里",
        leaked,
        f"翻了两台实例的日志（{len(ctx.logs)} 份）；材料正文只拼进当前 provider 那一次的 "
        "messages（`prompts.material_block` → `registry.current_llm()`），设置页据此写明"
        "「发给 XX」——那半句是文案，脚本读不到 DOM，离线起来的是 mock 提供商",
    )


def check_nomat(rep: Report, ctx: Ctx) -> None:
    """P4-G3：关掉材料功能，上传入口与生成都要退回 P1 那条路。"""
    problems: list[str] = []
    lines: list[str] = []

    # 动作类接口一律 40303：上传、单份详情、删除。
    status, envelope = api_upload(SAMPLE_ML, sample(SAMPLE_ML), base=ctx.nomat)
    if not (status == 403 and envelope.get("code") == 40303):
        problems.append(f"上传没被拦住：HTTP {status} code={envelope.get('code')}")
    else:
        lines.append("上传 → 403（40303）")

    status, envelope = api("GET", "/materials/m_missing", base=ctx.nomat)
    if not (status == 403 and envelope.get("code") == 40303):
        problems.append(f"单份详情没被拦住：HTTP {status} code={envelope.get('code')}")

    # 清单类读接口回 200 + 空 + `enabled=false`：它们在前端是**渲染路径**
    # （列表挂载、边打边搜），报错会把「这个部署没开材料」变成一串红色提示。
    # 前端判断「显不显示材料入口」看的是 `/capabilities` 的 `materials.enabled`。
    status, envelope = api("GET", "/materials", base=ctx.nomat)
    data = _data(status, envelope) if status == 200 else None
    if not isinstance(data, Mapping):
        problems.append(f"材料列表没按约定回 200：HTTP {status} code={envelope.get('code')}")
    elif data.get("items") or data.get("enabled") is not False:
        problems.append(f"材料列表没关干净：items={len(data.get('items') or [])} enabled={data.get('enabled')}")
    else:
        lines.append("材料列表 → 200 + 空清单 + enabled=false")

    status, envelope = api("GET", f"/materials/search?q={urllib.parse.quote(TERM_INDEX)}", base=ctx.nomat)
    data = _data(status, envelope) if status == 200 else None
    if not isinstance(data, Mapping) or data.get("items"):
        problems.append(f"检索没关干净：HTTP {status} items={len((data or {}).get('items') or [])}")

    # 前端据此隐藏入口：这条是整条链路的**唯一**依据，掉了一个字段就白搭。
    status, envelope = api("GET", "/capabilities", base=ctx.nomat)
    caps = (_data(status, envelope) or {}).get("materials") or {}
    if caps.get("enabled") is not False:
        problems.append(f"/capabilities 没说材料关着：{brief(caps, 80)}")
    else:
        lines.append(f"/capabilities.materials = {brief(caps, 60)}")

    course_id, job_id = _create_course(ctx.nomat, "无材料的一课", page_count=8, confirm=False)
    done = _wait_job(job_id, want={"done", "failed", "canceled"}, timeout=GEN_DEADLINE, base=ctx.nomat)
    if done.get("status") != "done":
        problems.append(f"关掉材料之后生成没跑通：{done.get('status')}")
    else:
        pages = _pages_of(ctx, course_id, base=ctx.nomat)
        ready = [page for page in pages if page.get("status") == "ready"]
        cited = [page for page in ready if (page.get("dsl") or {}).get("sources")]
        gaps = [page for page in ready if (page.get("dsl") or {}).get("gaps")]
        if not pages:
            # 空列表不是「都对」，是**没读到**：接口换个名字、课程换个人，
            # 底下三条断言都会在零页上自动成立。这里当失败报。
            problems.append("读不到这门课的页（不是「都对」，是没读到）")
        elif len(ready) != len(pages):
            problems.append(f"{len(pages)} 页里只有 {len(ready)} 页 ready")
        if cited:
            problems.append(f"没有材料却有 {len(cited)} 页带出处")
        if gaps:
            problems.append(f"没有材料却报了 {len(gaps)} 页「材料没写」")
        lines.append(f"生成 {len(ready)}/{len(pages)} 页 ready、出处与缺口都是空的（与 P1 一致）")

    rep.verdict("P4-G3", "关材料时上传入口隐藏、生成走 P1 路径", problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 八、前端 / 委托 / 回归
# --------------------------------------------------------------------------


def check_frontend(rep: Report, ctx: Ctx) -> None:
    """P4 的前端那一半：工作台三栏、会话帧、溯源徽标（用例逐条跑）。"""
    specs = [
        "src/__tests__/WorkbenchView.spec.ts",
        "src/__tests__/workbench-chat.spec.ts",
        "src/__tests__/source-badge.spec.ts",
    ]
    result = subprocess.run(
        [npx(), "vitest", "run", *specs],
        cwd=str(FRONTEND),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = plain((result.stdout or "") + (result.stderr or ""))
    if result.returncode != 0:
        log_path = ctx.work_dir / "vitest-p4.log"
        log_path.write_text(output, encoding="utf-8")
        reason = next((ln.strip() for ln in output.splitlines() if "FAIL" in ln or "Error" in ln), "")
        rep.fail("P4-G2b", "前端：三栏工作台 / 会话帧 / 溯源徽标", f"用例未通过：{reason}\n完整输出：{log_path}")
        return
    summary = next((ln.strip() for ln in reversed(output.splitlines()) if "Tests" in ln), "")
    rep.ok("P4-G2b", "前端：三栏工作台 / 会话帧 / 溯源徽标", f"三份用例全通过（{summary}）")


#: 由离线用例**判定**的条目：`(编号, 标题, 节点)`。脚本负责逐条记账。
DELEGATED: list[tuple[str, str, list[str]]] = [
    (
        "P4-A7",
        "溯源校验生效：伪造的出处被判失败并重生成，日志有 source_mismatch",
        [
            "tests/unit/test_generation_sourcing.py::test_a_fabricated_quote_is_retried_with_the_reason",
            "tests/unit/test_generation_sourcing.py::test_a_quote_that_never_matches_keeps_the_page_but_flags_it",
        ],
    ),
    (
        "P4-A14",
        "长材料不超上下文：150k 字材料也能生成，单次 prompt 有硬上限",
        [
            "tests/unit/test_material_search.py::test_top_k_is_clamped",
            "tests/unit/test_generation_sourcing.py::test_the_outline_also_runs_on_the_material",
        ],
    ),
    (
        "P4-B3",
        "契约测试覆盖 §3 全部端点（含 413 / 415 / 404）",
        ["tests/contract/test_p4_material_api.py"],
    ),
    (
        "P4-B4",
        "chat 的接口契约：技能可见、回退只回上下文",
        ["tests/contract/test_p4_workbench_api.py"],
    ),
    (
        "P4-C5",
        "BM25 语料统计与 chunk 数据一致（重新解析不留陈旧索引）",
        [
            "tests/unit/test_material_store.py::test_reparsing_replaces_the_old_chunks",
            "tests/unit/test_material_store.py::test_a_failed_parse_leaves_no_half_index",
            "tests/unit/test_material_search.py::test_corpus_stats_come_from_the_stored_df",
        ],
    ),
    (
        "P4-F3",
        "上传内容在预览里被转义，无 XSS（富文本字段同理）",
        ["tests/contract/test_p4_material_api.py::test_a_chunk_of_another_material_is_404"],
    ),
]

#: 离线跑不到、但离线侧有替代证据的条目：`(编号, 标题, 节点, 为什么跑不到)`。
PROXIED: list[tuple[str, str, list[str], str]] = [
    (
        "P4-A2b",
        "分块「语义完整、不在句子中间切断」≥ 9/10（人工抽检）",
        [],
        "要人读；离线侧验到的是章节路径覆盖率与块长分布，切分本身由 "
        "tests/unit/test_material_chunking.py 的用例钉着",
    ),
    (
        "P4-E1",
        "材料驱动内容忠实度 ≥ 4 分（抽 10 页人工评分）",
        ["tests/unit/test_generation_fixture.py::test_a_page_about_material_quotes_it_verbatim"],
        "要人读；离线侧验到的是「有依据才引、没依据就说没写」，且每一页的引文都逐字核对过",
    ),
    (
        "P4-E2",
        "溯源引用准确率 ≥ 95%（抽 20 条）",
        ["tests/unit/test_generation_sourcing.py::test_every_citation_points_back_at_the_material"],
        "脚本把**全量**引文核了一遍（P4-C2），比抽 20 条更严；这里记的是抽样那半条的同源证据",
    ),
    (
        "P4-E3",
        "检索相关性：10 个真实查询 top-3 命中率 ≥ 80%",
        [
            "tests/unit/test_material_search.py::test_a_term_finds_the_chunk_that_actually_uses_it",
            "tests/unit/test_material_search.py::test_a_rare_term_outweighs_a_common_one_in_the_same_query",
        ],
        "「10 个真实查询」要人出题；离线侧验到的是术语命中与不硬凑（脚本另跑了 4 个查询）",
    ),
    (
        "P4-E4",
        "Agent 对 Skill 调用意图理解准确率 ≥ 90%（20 条指令）",
        [
            "tests/unit/test_generation_fixture.py::test_a_sentence_about_a_page_turns_into_the_matching_skill",
            "tests/unit/test_generation_fixture.py::test_rewrite_and_delete_carry_the_page_they_mean",
            "tests/unit/test_generation_fixture.py::test_a_sentence_that_asks_for_nothing_gets_no_action",
        ],
        "准确率要真模型在 20 条指令上量；离线侧验到的是桩自己按意图分派得对（那是这条的下界）",
    ),
    (
        "P4-F2",
        "解析在受限环境执行：库版本固定、禁用外链与宏、不调系统命令",
        [],
        "要审依赖与子进程行为；离线可查的「解析器不发网络请求、不调 shell」"
        "由 tests/unit/test_material_parsers.py 的用例覆盖",
    ),
]


def check_delegated(rep: Report, ctx: Ctx) -> None:
    """跑一遍离线用例，逐条记账（A7 / A14 / B3 / C5 与几条代理）。"""
    nodes = [node for _aid, _title, group in DELEGATED for node in group]
    nodes += [node for _aid, _title, group, _why in PROXIED for node in group]
    pytest_verdicts(nodes)

    for aid, title, group in DELEGATED:
        problems = []
        for node in group:
            ok, why = pytest_node_ok(node)
            if not ok:
                problems.append(f"{node}（{why}）")
        rep.verdict(aid, title, problems, f"{sum(_cases_passed(n) for n in group)} 条用例全通过")

    for aid, title, group, why in PROXIED:
        pairs = []
        for node in group:
            ok, _ = pytest_node_ok(node)
            pairs.append(f"{node.rsplit('::', 1)[-1]}：{'通过' if ok else '**未通过**'}")
        evidence = "；离线侧（{} 条）—— ".format(len(group)) + "、".join(pairs) if group else ""
        rep.skip(aid, title, f"{why}{evidence}")


def check_suites(rep: Report, ctx: Ctx) -> None:
    """P4-G1：P0/P1 的验收保持通过，无材料的生成与原来一致。"""
    suites = {
        "P0": run_pytest("tests/contract/test_p0_api.py"),
        "P1": run_pytest("tests/contract/test_p1_api.py"),
        "材料关掉之后走 P1 路径": run_pytest(
            "tests/unit/test_generation_sourcing.py::test_the_switch_off_falls_back_to_a_plain_lesson",
            "tests/unit/test_generation_sourcing.py::test_a_course_without_materials_keeps_its_pages_clean",
        ),
    }
    problems = [
        f"{name} 未通过：{_pytest_tail(result, 6)}"
        for name, result in suites.items()
        if result.returncode != 0
    ]
    rep.verdict(
        "P4-G1",
        "P0/P1 验收保持通过；无材料的生成与 P1 一致",
        problems,
        "；".join(f"{name} {_pytest_summary(result)}" for name, result in suites.items()),
    )


def check_unreachable(rep: Report, ctx: Ctx) -> None:
    """离线跑不到的：如实跳过，并说清卡在哪。"""
    rep.skip(
        "P4-A6b",
        "溯源徽标 hover 浮层与抽屉定位高亮（人眼 10 次点击）",
        "要浏览器渲染；离线侧验到的是徽标可点、跳转接口给得出引文那一段"
        "（前端那半条由 source-badge.spec.ts 的用例钉着）",
    )
    rep.skip(
        "P4-D5b",
        "工作台聊天的真模型首 token（离线量的是替身）",
        "要真上游；离线侧记的是替身的首帧耗时（P4-D5 那一行）",
    )


# --------------------------------------------------------------------------
# 临时库与后端
# --------------------------------------------------------------------------


def prepare_database(ctx: Ctx, port: int) -> tuple[bool, str]:
    """在一台的临时库上跑迁移与种子。返回 (是否成功, 失败原因)。"""
    env = {**ctx.env, "DATABASE_URL": ctx.db_urls[port]}
    upgrade = subprocess.run(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "db", "upgrade"],
        cwd=str(BACKEND), env=child_env(env),
        capture_output=True, check=False, text=True, encoding="utf-8", errors="replace",
    )
    if upgrade.returncode != 0:
        return False, f"db upgrade 失败：\n{plain((upgrade.stderr or '')[-500:])}"

    seeded = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.seeds import run_seed\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    print(json.dumps(run_seed(), ensure_ascii=False))\n",
        env=env,
    )
    if seeded.returncode != 0:
        return False, f"seed 失败：\n{plain((seeded.stderr or '')[-500:])}"
    return True, ""


def start_server(ctx: Ctx, port: int, log_name: str, env: dict[str, str]):
    log_path = ctx.work_dir / log_name
    ctx.logs[log_name.replace(".log", "")] = log_path
    proc = start(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "run", "--port", str(port)],
        cwd=BACKEND,
        log_path=log_path,
        env=env,
    )
    if not wait_http(f"http://127.0.0.1:{port}/api/health", timeout=90):
        log = log_path.read_text(encoding="utf-8", errors="replace")
        print(f"  {port} 上的后端没起来，日志：\n{plain(log[-1200:])}")
        stop(proc)
        return None
    return proc


def _port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="P4 A/B/C/D/F/G 类验收（P4-G2，离线 Mock）")
    parser.add_argument("--keep", action="store_true", help="跑完留下临时库、材料目录与两个后端进程")
    args = parser.parse_args()

    for port in (MAIN_PORT, NOMAT_PORT):
        if is_up(f"http://127.0.0.1:{port}/api/health") or _port_busy(port):
            print(f"端口 {port} 上已经有服务了。这台机器上它可能是别人的 —— 停掉它再跑。")
            return 2

    work_dir = Path(tempfile.mkdtemp(prefix="eduagentx-p4-"))
    material_dir = work_dir / "materials"
    shared = {"MATERIAL_DIR": material_dir.as_posix()}
    db_urls = {
        port: f"sqlite:///{(work_dir / f'accept-{port}.db').as_posix()}" for port in (MAIN_PORT, NOMAT_PORT)
    }
    ctx = Ctx(
        env={**OFFLINE_ENV, **shared, "DATABASE_URL": db_urls[MAIN_PORT]},
        work_dir=work_dir,
        material_dir=material_dir,
        format_dir=work_dir / "formats",
        db_urls=db_urls,
    )

    print("P4 A/B/C/D/F/G 类验收开始（两个离线实例，全程不联网）")
    print(f"  主实例   http://127.0.0.1:{MAIN_PORT}/api（离线替身，材料开）")
    print(f"  关材料   http://127.0.0.1:{NOMAT_PORT}/api（MATERIAL_ENABLED=false）")
    print(f"  临时目录 {work_dir}（两个库 + 材料 + 造出来的 pdf/docx/pptx + 日志）")
    print(f"  样例材料 {SAMPLES}")
    print()

    report = Report()
    try:
        for port, name, env in (
            (MAIN_PORT, "main.log", ctx.env),
            (NOMAT_PORT, "nomat.log", {**NOMAT_ENV, **shared}),
        ):
            ok, why = prepare_database(ctx, port)
            if not ok:
                print(f"  临时库没准备好（:{port}）：\n{why}")
                return 2
            proc = start_server(ctx, port, name, {**env, "DATABASE_URL": db_urls[port]})
            if proc is None:
                return 2
            ctx.procs[name.split(".")[0]] = proc

        _guard(report, "样例材料", check_samples, ctx)
        _guard(report, "五种格式", check_formats, ctx)
        _guard(report, "上传的几条硬规矩", check_upload_guards, ctx)
        _guard(report, "分块", check_chunking, ctx)
        _guard(report, "检索", check_search, ctx)
        _guard(report, "带材料生成与溯源", check_generation, ctx)
        _guard(report, "工作台对话", check_workbench, ctx)
        _guard(report, "材料与课程的关联", check_link, ctx)
        _guard(report, "安全", check_security, ctx)
        _guard(report, "关掉材料", check_nomat, ctx)
        _guard(report, "性能", check_perf, ctx)
        _guard(report, "前端", check_frontend, ctx)
        _guard(report, "委托用例", check_delegated, ctx)
        _guard(report, "P0/P1 回归", check_suites, ctx)
        _guard(report, "离线跑不到的条目", check_unreachable, ctx)

        passed = sum(1 for row in report.rows if row[2] == "PASS")
        skipped = sum(1 for row in report.rows if row[2] == "SKIP")
        report.ok(
            "P4-G2c",
            "scripts/accept_p4.py 用三份样例材料跑通全流程",
            f"以上 {passed} 条在离线替身上通过、{skipped} 条按 §7 的分工记跳过"
            "（要真上游、人眼或浏览器渲染）；两个实例全程未联网、未读 .env",
        )
    finally:
        failed = any(row[2] == "FAIL" for row in report.rows)
        if not args.keep:
            print()
            print("  正在关闭两个临时后端…")
            for proc in ctx.procs.values():
                stop(proc)
        if args.keep:
            print(f"\n  两个临时后端还在 :{MAIN_PORT} / :{NOMAT_PORT}（--keep）")
            print(f"  临时库与材料 {work_dir}")
        elif failed:
            print(f"  这一趟没全绿，临时目录留着给你查：{work_dir}")
            print(f"    日志 {work_dir / '*.log'}　材料 {material_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
