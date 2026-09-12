#!/usr/bin/env python
"""一条命令跑完前后端两套测试（P0-G1）。

    python scripts/test.py            # 后端 pytest + 前端 vitest
    python scripts/test.py --back     # 只跑后端
    python scripts/test.py --front    # 只跑前端

`make test` 做的就是这件事；没装 GNU Make 就直接跑这个脚本。

两边都跑完才下结论：先跑的那边红了也继续跑另一边 —— 一次看全，
比「改一个跑一次」快得多。真正的断言在 tests/ 与 src/__tests__/ 里，
本脚本只负责启动与汇总，不做任何判定（免得出现「脚本说过了、测试其实没过」）。

刻意不自带共享工具模块：验收与开发脚本要能被单独拷走、用系统 python 直接跑
（AGENTS.md §23 的「不联网、不依赖环境」同样适用于这里）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: Windows 控制台是 GBK，pytest/vitest 的输出里有 ✓ 之类的字符。
#: 默认行为是直接 UnicodeEncodeError 崩掉 —— 跑测试的脚本不该死在打印上。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def venv_python() -> Path:
    """backend/.venv 里的 python（Windows 在 Scripts/，POSIX 在 bin/）。"""
    for candidate in (BACKEND / ".venv/Scripts/python.exe", BACKEND / ".venv/bin/python"):
        if candidate.exists():
            return candidate
    sys.exit(
        "找不到虚拟环境。先建：python -m venv backend/.venv 然后 pip install -r backend/requirements.txt"
    )


def npm() -> str:
    """npm 的可执行名（Windows 上是 npm.cmd）。"""
    for name in ("npm.cmd", "npm"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("PATH 里找不到 npm —— 前端测试需要 Node.js 20+（https://nodejs.org）")


def run(label: str, args: list[str], cwd: Path) -> bool:
    """跑一条命令，输出直接透传到终端（不捕获：失败了要看得到上下文）。"""
    print(f"\n=== {label} ===", flush=True)
    print(f"$ {' '.join(args)}  （cwd={cwd.name}）\n", flush=True)
    result = subprocess.run(
        args,
        cwd=str(cwd),
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8:replace"},
    )
    print(f"\n--- {label}：{'通过' if result.returncode == 0 else '不通过'} ---", flush=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="P0-G1：前后端测试一条命令跑完")
    parser.add_argument("--back", action="store_true", help="只跑后端 pytest")
    parser.add_argument("--front", action="store_true", help="只跑前端 vitest")
    args = parser.parse_args()

    # 两个都没给 = 两个都跑；给了一个就只跑那个
    both = not args.back and not args.front
    outcomes: list[tuple[str, bool]] = []

    if both or args.back:
        if not (BACKEND / "tests").is_dir():
            sys.exit(f"找不到后端测试目录：{BACKEND / 'tests'}")
        outcomes.append(
            ("后端 pytest", run("后端 pytest", [str(venv_python()), "-m", "pytest"], BACKEND))
        )

    if both or args.front:
        if not (FRONTEND / "node_modules").is_dir():
            sys.exit(f"找不到前端依赖：{FRONTEND / 'node_modules'}，先在 frontend 下 npm install")
        outcomes.append(
            ("前端 vitest", run("前端 vitest", [npm(), "run", "test"], FRONTEND))
        )

    print()
    print("=" * 60)
    for label, passed in outcomes:
        print(f"  {'通过' if passed else '不通过'}  {label}")
    failed = [label for label, passed in outcomes if not passed]
    print("=" * 60)
    if failed:
        print(f"失败：{'、'.join(failed)}")
        return 1
    print("全绿（P0-G1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
