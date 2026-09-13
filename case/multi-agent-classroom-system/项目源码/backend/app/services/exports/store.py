"""导出产物落盘（P5-C1）。

与 `materials/policy.py`、`voice/assets.py` 同一套口径，三件事照抄，因为它们
解决的是同一类问题：

1. **盘上的名字由我们生成，一门课一个目录**：`{EXPORT_DIR}/{course_id}/{export_id}.{ext}`。
   课程 id 与导出 id 都是我们自己发的（uuid4().hex，不可猜），用户的一个字节
   都不进路径 —— 于是「把 `../` 传进文件名」从根上不存在。
2. **库里只存相对路径**（P5-C1 的 `data/exports/…`）。`EXPORT_DIR` 换到别处，
   库里一行都不用改；`physical_path()` 会把落在导出根目录之外的路径判为无效，
   而不是照着读。
3. **落盘是「先写临时文件再 rename」**。直接往目标路径写的话，一份正在被下载的
   产物会在半途变成半个文件；而 `os.replace` 在同一文件系统上是原子的。

`prune()` 是「删过期」，不是「删全部」：它按 `expires_at` 走，只碰自己发的那些行。
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import time
from collections.abc import Collection
from pathlib import Path

from flask import current_app, has_app_context

from app.common.logging import get_logger
from app.models.export import EXPORT_FORMATS, EXPORT_SUBDIR

logger = get_logger("app.exports.store")

#: 与模型同源。模型的 CHECK 拦的是「库里那一列」，这里拦的是「盘上那一步」，
#: 两处都写是因为它们各自会被单独调用（迁移、清理脚本）。
SUBDIR = EXPORT_SUBDIR

#: 目录名片段的白名单（与 `materials.policy.safe_token` 同一条正则）。
_UNSAFE = re.compile(r"[^0-9A-Za-z_-]+")

#: 临时文件前缀。以 `.` 开头，`clean_tmp()` 只清这种名字的东西。
TMP_PREFIX = ".export-"


def root() -> Path:
    """导出根目录（物理路径）。

    没有应用上下文时也答得上来（退回默认目录）：验收脚本与清理任务有时在
    请求之外调它，为拿一个目录去建整个 app 上下文不划算。
    """
    configured = current_app.config.get("EXPORT_DIR") if has_app_context() else None
    if configured:
        return Path(str(configured))
    from app.config import BACKEND_DIR

    return BACKEND_DIR / "data" / "exports"


def ttl_hours() -> float:
    """产物在盘上留多久（P5-A6 的 24h）。"""
    return float(current_app.config.get("EXPORT_TTL_HOURS") or 24.0)


def max_bytes() -> int:
    """单份产物的字节上限（超过就不落盘，见 config 里的说明）。"""
    return int(current_app.config.get("EXPORT_MAX_BYTES") or 64 * 1024 * 1024)


def safe_token(value: str, *, limit: int = 48) -> str:
    return _UNSAFE.sub("_", str(value or "")).strip()[:limit] or "x"


def rel_dir(course_id: str) -> str:
    return f"{SUBDIR}/{safe_token(course_id)}"


def rel_path(course_id: str, export_id: str, fmt: str) -> str:
    """落库用的逻辑相对路径（P5-C1）。后缀是**我们自己从枚举里取的**，不是用户传的。"""
    ext = fmt if fmt in EXPORT_FORMATS else "bin"
    return f"{rel_dir(course_id)}/{safe_token(export_id)}.{ext}"


def physical_path(rel: str) -> Path | None:
    """逻辑相对路径 → 物理路径。落在导出根目录之外的一律判无效（返回 None）。

    与材料那边同一条理由：约束管得住我们自己写的行，管不住有人拿 sqlite3 手改。
    """
    rel = str(rel or "")
    prefix = SUBDIR + "/"
    if not rel.startswith(prefix) or ".." in rel:
        return None
    base = root().resolve()
    target = (base / rel[len(prefix) :]).resolve()
    if base != target and base not in target.parents:
        return None
    return target


def file_of(export) -> Path | None:
    """导出那一行对应的产物文件；路径不合法或文件不在则 None。

    行在而文件不在是**正常会发生的**（清理任务删了文件、或有人清了 `data/`），
    调用方按「产物没了」处理，而不是当成数据库坏了。
    """
    path = physical_path(getattr(export, "file_path", ""))
    if path is None or not path.is_file():
        return None
    return path


def write(course_id: str, export_id: str, fmt: str, data: bytes) -> tuple[str, int]:
    """落盘，返回 `(相对路径, 字节数)`。**不写库** —— 那是调用方在一个短事务里做的。

    先写同目录下的临时文件再 `os.replace`：同目录保证 rename 不跨文件系统
    （跨设备的 rename 会退化成拷贝+删除，就不再是原子的了）。
    """
    rel = rel_path(course_id, export_id, fmt)
    target = physical_path(rel)
    if target is None:  # pragma: no cover - 自己生成的路径一定合法
        raise ValueError("导出路径不合法")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, raw = tempfile.mkstemp(prefix=TMP_PREFIX, dir=str(target.parent))
    tmp = Path(raw)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(tmp, target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return rel, len(data)


def purge(export) -> int:
    """删掉一份产物在盘上的文件，返回删掉的文件数。

    路径是从 `file_path` 解出来的，不是从 `export.id` 拼的：后者在「id 是我们
    生成的」这条前提被打破时会删错地方，而前者会先过 `physical_path`。
    """
    path = physical_path(getattr(export, "file_path", ""))
    if path is None:
        return 0
    try:
        path.unlink()
        return 1
    except FileNotFoundError:
        return 0
    except OSError:  # pragma: no cover - 文件被占用（Windows 上常见）
        logger.warning("删除导出产物失败 name=%s", path.name)
        return 0


def purge_course(course_id: str) -> int:
    """删课时的收尾：把 `{EXPORT_DIR}/{course_id}/` 整个目录端掉。

    库里的行由外键 CASCADE 带走（`exports.course_id` 是 CASCADE），这里只管盘上。
    """
    folder = physical_path(rel_dir(course_id))
    base = root().resolve()
    if folder is None or folder == base or base not in folder.parents:
        # 只删导出根目录**里面**的一层目录，绝不往根上删
        return 0
    if not folder.is_dir():
        return 0
    removed = 0
    for item in sorted(folder.glob("**/*"), reverse=True):
        try:
            if item.is_file():
                item.unlink()
                removed += 1
        except OSError:  # pragma: no cover
            logger.warning("删除导出文件失败 name=%s", item.name)
    with contextlib.suppress(OSError):  # pragma: no cover - 目录还被占用（Windows）
        folder.rmdir()
    return removed


def rel_key(path: Path) -> str:
    """盘上的一个文件 → 它在库里会是的那条相对路径。`sweep_orphans` 的比对依据。"""
    base = root().resolve()
    try:
        inner = path.resolve().relative_to(base)
    except ValueError:  # pragma: no cover - 走不到根的只有根自己
        return ""
    return f"{SUBDIR}/{inner.as_posix()}"


def sweep_orphans(known: Collection[str], *, max_age: float = 600.0) -> int:
    """删掉盘上**没有行认领**的产物。

    这不是「清理过期」的重复，而是它补不上的那个洞：`write()` 先把字节落到盘上，
    调用方随后才在一个事务里写 `file_path`。两步之间进程被杀（容器重启、
    部署、OOM）就会留下一份谁都指不到的产物 —— 而 `cleanup()` 是**顺着行找文件**的，
    这种文件它永远看不见，只会一直占着磁盘（`used_bytes()` 涨、导出历史里又查无此物）。

    `max_age` 是**宽限期**：刚落盘、行还没写进去的那些文件正在这个窗口里，
    删掉它们等于把一次正在进行的导出毁掉。导出本身是秒级的，10 分钟足够宽。

    `known` 是当前所有活着的 `export.file_path` —— 由调用方一次查出来传进来，
    不在这里查库：`store` 这一层不认识 `Export` 模型。
    """
    base = root()
    if not base.is_dir():
        return 0
    alive = {str(item) for item in known}
    now = time.time()
    removed = 0
    for item in base.glob("**/*"):
        try:
            if not item.is_file() or item.name.startswith(TMP_PREFIX):
                continue
            if rel_key(item) in alive:
                continue
            if now - item.stat().st_mtime < max_age:
                continue
            item.unlink()
            removed += 1
        except OSError:  # pragma: no cover - 文件被占用（Windows）
            continue
    if removed:
        logger.warning("清掉了 %d 个无主导出产物", removed)
    return removed


def clean_tmp(*, max_age: float = 3600.0) -> int:
    """清掉落盘失败留下的临时文件（正常路径上它们会被 `os.replace` 搬走）。"""
    base = root()
    if not base.is_dir():
        return 0
    now = time.time()
    removed = 0
    for item in base.glob("**/" + TMP_PREFIX + "*"):
        try:
            if item.is_file() and now - item.stat().st_mtime > max_age:
                item.unlink()
                removed += 1
        except OSError:  # pragma: no cover
            continue
    return removed


def used_bytes() -> int:
    """导出根目录现在占了多少字节（运维手册与「产物占多大」那个数字用它）。"""
    base = root()
    if not base.is_dir():
        return 0
    total = 0
    for item in base.glob("**/*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:  # pragma: no cover
            continue
    return total


__all__ = [
    "SUBDIR",
    "TMP_PREFIX",
    "clean_tmp",
    "file_of",
    "max_bytes",
    "physical_path",
    "purge",
    "purge_course",
    "rel_dir",
    "rel_key",
    "rel_path",
    "root",
    "safe_token",
    "sweep_orphans",
    "ttl_hours",
    "used_bytes",
    "write",
]
