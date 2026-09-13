"""备份与恢复（P5-C3 / §6）。

一台机器上的全部状态就是 `backend/data/` 这一棵树：一个 SQLite 文件加上
四类文件（上传的材料原件、合成出来的音频、导出产物、临时上传）。备份把这棵树
收成一个 `.tar.gz`，恢复把它放回去。

四条决定：

1. **库用 `sqlite3` 的在线备份 API，不是 `cp`**。生成任务正在写库的时候
   `cp` 拿到的可能是写了一半的页 —— 那是「备份看起来成功了、恢复出来打不开」
   的经典故障。`Connection.backup()` 就是 `sqlite3 app.db ".backup"` 的同一条路径
   （§6 写的就是它），但它不要求机器上装了 sqlite3 命令行 —— 开发机是 Windows，
   容器里也没有那个二进制。
2. **数据库存成归档里的 `eduagentx.db`，四类文件按「名字 → 配置项」映射存**。
   存档里的路径**不跟机器走**：换一台机器恢复时，`AUDIO_DIR` 可能指向别处，
   而归档里记的是「audio/…」这样的逻辑名，恢复时再映射回那台机器的配置。
3. **库里存的是相对路径**（P2-C4 / P4-C3 / P5-C1），所以只要文件回到了
   `AUDIO_DIR` / `EXPORT_DIR` 指向的位置，音频就能播、产物就能下载 ——
   这三条口径是同一条。
4. **恢复必须先备份**：把当前那个库改名留档（`.pre-restore-<时间戳>`），
   而不是直接覆盖。恢复是运维在出事时做的动作，而人在那个时候最可能选错文件。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

from flask import current_app

from app.common.logging import get_logger

logger = get_logger("app.backup")

#: 归档里四类文件的目录名 → 配置项。顺序固定，方便人对着 tar -t 看。
DIR_KEYS: dict[str, str] = {
    "uploads": "UPLOAD_DIR",
    "materials": "MATERIAL_DIR",
    "audio": "AUDIO_DIR",
    "exports": "EXPORT_DIR",
}

MANIFEST_NAME = "manifest.json"
DB_NAME = "eduagentx.db"

BACKUP_PREFIX = "eduagentx-"
BACKUP_SUFFIX = ".tar.gz"


def database_path() -> Path:
    """当前配置的 SQLite 文件路径。非 SQLite（PG 之类）返回空路径。

    `sqlite:///relative` 是**相对 backend 目录**的（与 `_ensure_directories`
    同一条解释），绝对路径则是 `sqlite:////abs/path`。
    """
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if not uri.startswith("sqlite:///") or ":memory:" in uri or uri == "sqlite://":
        return Path()
    raw = uri.removeprefix("sqlite:///")
    path = Path(raw)
    if not path.is_absolute():
        from app.config import BACKEND_DIR

        path = BACKEND_DIR / path
    return path


def _dir_paths() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, key in DIR_KEYS.items():
        raw = current_app.config.get(key)
        if raw:
            out[name] = Path(str(raw))
    return out


def _verify_sqlite(payload: bytes) -> None:
    """这份字节是不是一个完整可读的 SQLite 库。不是就抛，绝不落盘。"""
    handle, tmp_name = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    tmp = Path(tmp_name)
    try:
        tmp.write_bytes(payload)
        conn = sqlite3.connect(tmp)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        if not row or str(row[0]).lower() != "ok":
            raise ValueError("备份里的数据库不完整（integrity_check 未通过）")
    finally:
        tmp.unlink(missing_ok=True)


def _walk_files(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def create(out_dir: str | Path, *, keep: int = 0) -> dict[str, Any]:
    """打一份备份，返回 `{path, bytes, dbBytes, files, kept, pruned}`。

    `keep > 0` 时只保留最近的这么多份（含刚打的这份），更早的删掉 ——
    定时备份不设上限的话，总有一天会把盘写满，而写满之后首先坏掉的是主库。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = out / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"

    db_path = database_path()
    dirs = _dir_paths()
    counts: dict[str, int] = dict.fromkeys(dirs, 0)

    with tarfile.open(target, "w:gz") as tar:
        if db_path.is_file():
            # 在线备份（`.backup` 那条路径）：先把快照落到一个临时文件，
            # 再读进归档。**不直接 cp 那个库**：正在写的库拷出来可能是半截的，
            # 而 cp 出来的那一份看起来完全正常。
            handle, tmp_name = tempfile.mkstemp(suffix=".db", dir=str(out))
            os.close(handle)
            tmp = Path(tmp_name)
            try:
                source = sqlite3.connect(db_path)
                try:
                    dest = sqlite3.connect(tmp)
                    try:
                        source.backup(dest)
                    finally:
                        dest.close()
                finally:
                    source.close()
                data = tmp.read_bytes()
            finally:
                # 无论成败都把临时文件收掉：它跟归档同名同姓地躺在备份目录里，
                # 留下的下一份「备份」就会被下一个人当成真的。
                tmp.unlink(missing_ok=True)
            info = tarfile.TarInfo(DB_NAME)
            info.size = len(data)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
        for name, root in dirs.items():
            for path in _walk_files(root):
                counts[name] += 1
                tar.add(path, arcname=f"{name}/{path.relative_to(root).as_posix()}")

        manifest = {
            "version": 1,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dbBytes": database_path().stat().st_size if db_path.is_file() else 0,
            "files": counts,
            # 只记配置项的名字，不记路径：归档要能在另一台机器上恢复，
            # 而那边的路径本来就不一样（见模块 docstring 第 2 条）。
            "sources": sorted(DIR_KEYS),
        }
        payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(payload)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(payload))

    kept = 0
    pruned: list[str] = []
    if keep > 0:
        existing = sorted(out.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))
        for old in existing[:-keep]:
            pruned.append(old.name)
            old.unlink(missing_ok=True)
        kept = min(len(existing), keep)

    report = {
        "path": str(target),
        "bytes": target.stat().st_size,
        "files": sum(counts.values()),
        "counts": counts,
        "kept": kept,
        "pruned": pruned,
    }
    logger.info(
        "备份完成 path=%s bytes=%d files=%d", target.name, report["bytes"], report["files"]
    )
    return report


def inspect(archive: str | Path) -> dict[str, Any]:
    """看一眼归档里有什么（不落盘）。恢复之前先让人确认一下。"""
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        manifest: dict[str, Any] = {}
        if MANIFEST_NAME in names:
            handle = tar.extractfile(MANIFEST_NAME)
            if handle is not None:
                manifest = json.loads(handle.read().decode("utf-8"))
    files = [n for n in names if n not in {MANIFEST_NAME, DB_NAME}]
    return {
        "path": str(archive),
        "hasDb": DB_NAME in names,
        "files": len(files),
        "manifest": manifest,
    }


def restore(archive: str | Path, *, confirm: bool = False) -> dict[str, Any]:
    """从归档恢复。`confirm=False` 时**什么都不做**，只回一份「会动哪些东西」。

    调用方（CLI）在没给 `--yes` 时先打印这份预告再退出 —— 恢复会覆盖线上数据，
    让人先看清楚要往哪儿写，比事后道歉便宜。
    """
    src = Path(archive)
    if not src.is_file():
        raise FileNotFoundError(f"找不到备份文件：{src}")

    db_path = database_path()
    dirs = _dir_paths()
    plan = {
        "archive": str(src),
        "database": str(db_path) if db_path else "",
        "dirs": {name: str(path) for name, path in dirs.items()},
    }
    if not confirm:
        return {**plan, "applied": False, "safetyCopy": "", "restored": 0}

    safety = ""
    if db_path and db_path.is_file():
        # 先留一份「恢复前」的库：恢复错了还能退回来。复制一份而不是改名，
        # 是因为**改名在 Windows 上会失败**：应用起来的时候连过库，
        # 那个句柄还开着，`rename` 会直接报「另一个程序正在使用此文件」，
        # 而「覆盖写」是允许的。恢复这个动作不该只在 Linux 上能做完。
        safety_path = db_path.with_suffix(f".pre-restore-{int(time.time())}.db")
        shutil.copy2(db_path, safety_path)
        safety = str(safety_path)
        # WAL 与 shm 属于**上一个库**：留着的话 SQLite 会把它们当成这个库
        # 还没落盘的内容回放进去，恢复出来的就成了两个库的混合物。
        # 拿不掉只记一条日志 —— 库本身已经换好了，为此把恢复判失败不划算。
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            try:
                sidecar.unlink(missing_ok=True)
            except OSError:
                logger.warning("没能删掉 %s（有别的进程正开着它）", sidecar.name)

    restored = 0
    with tarfile.open(src, "r:gz") as tar:
        if db_path and DB_NAME in tar.getnames():
            db_path.parent.mkdir(parents=True, exist_ok=True)
            handle = tar.extractfile(DB_NAME)
            if handle is not None:
                payload = handle.read()
                # 落盘之前先验一遍：`integrity_check` 说 OK 才写过去。
                # 备份的全部意义是「以后还读得回来」，而这是唯一能当场回答
                # 「这份备份读得回来吗」的一步 —— 出事那天才发现读不回来就晚了。
                _verify_sqlite(payload)
                db_path.write_bytes(payload)
                restored += 1

        for name, root in dirs.items():
            for info in tar.getmembers():
                if not info.isfile() or not info.name.startswith(f"{name}/"):
                    continue
                relative = info.name[len(name) + 1 :]
                # 归档里的相对路径理论上是我们自己写的，但它仍然是外部输入：
                # 带 `..` 的成员会把文件写到 data 目录外面去（zip-slip）。
                if not relative or ".." in Path(relative).parts:
                    continue
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                handle = tar.extractfile(info)
                if handle is None:
                    continue
                target.write_bytes(handle.read())
                restored += 1

    logger.warning("恢复完成 archive=%s 文件 %d 个", src.name, restored)
    return {**plan, "applied": True, "safetyCopy": safety, "restored": restored}


def register_cli(app) -> None:
    """注册 `flask backup` / `flask restore`（P5-C3）。"""
    # click 必须在装饰器求值之前就位：`@click.argument` 是 import 期执行的，
    # 写在函数体里的 import 那时候还没跑到
    import click

    @app.cli.command("backup")
    def backup_command() -> None:  # pragma: no cover - 通过 CLI 触发
        """打一份备份（库 + 材料 + 音频 + 导出产物）。"""
        out = current_app.config.get("BACKUP_DIR") or "backups"
        keep = int(current_app.config.get("BACKUP_KEEP") or 0)
        report = create(out, keep=keep)
        click.echo(f"备份完成：{report['path']}")
        click.echo(
            f"  数据库 1 个，文件 {report['files']} 个，共 {report['bytes'] / 1048576:.1f} MB"
        )
        if report["pruned"]:
            click.echo(f"  按保留 {keep} 份的约定删掉了：{'、'.join(report['pruned'])}")

    @app.cli.command("restore")
    @click.argument("archive")
    @click.option("--yes", is_flag=True, help="确认覆盖当前数据（不给就只打印预告）")
    def restore_command(archive: str, yes: bool) -> None:  # pragma: no cover - 通过 CLI 触发
        """从备份恢复。**会覆盖当前数据库**，所以默认只打印预告。"""
        plan = restore(archive, confirm=yes)
        if not plan["applied"]:
            click.echo(f"将要恢复：{plan['archive']}")
            click.echo(f"  数据库 → {plan['database'] or '（不是 SQLite，跳过）'}")
            for name, path in plan["dirs"].items():
                click.echo(f"  {name} → {path}")
            click.echo("确认无误后加 --yes 再来一次（会先给现在的库留一份副本）")
            return
        click.echo(f"恢复完成：{plan['restored']} 个文件")
        if plan["safetyCopy"]:
            click.echo(f"  恢复前的数据库留了一份：{plan['safetyCopy']}")
        click.echo("  重启服务后生效（进程里的连接还指着旧文件）")


__all__ = ["DIR_KEYS", "create", "database_path", "inspect", "register_cli", "restore"]
