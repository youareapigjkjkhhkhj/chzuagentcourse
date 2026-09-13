"""材料库：上传、解析编排、读取、删除（F4-1~F4-6 / P4-C1~C5）。

这是材料域唯一**写库**的地方，也是唯一知道「一次上传要经过哪几步」的地方。
四步的顺序不是随便排的：

    落行(uploading) → 收字节 → 校验/去重 → 改成 parsing → 丢给后台线程解析

「先落行再收字节」看着别扭（这条记录在字节到齐前没有文件），但它换来两件事：
**id 稳定**（客户端拿到的 fileId 与后台任务、错误信息里的 id 是同一个），
以及**失败可查**（413/415 拒绝时删掉这条行，其余任何中断都留下一条记录，
而不是一个没人知道的临时文件）。`_sweep_stale()` 负责收尾那些连响应都没发出去
就断掉的（进程被杀、网线被拔）。

解析本身不持写锁：PyMuPDF 解一份 50 页 PDF 要几秒、jieba 索引 10 万字要几秒，
而 SQLite 只有一个写者（AGENTS §4.2）—— 把这几秒放进去，别的请求就全在排队。
所以流程是「取行（读）→ 解析（无锁）→ 写回（短事务）」。

「派生数据先删后写」是幂等的关键（P4-C5）：重新解析一份材料时，旧的块、旧倒排、
旧统计一律先清掉 —— 否则改了切块参数再解析一次，库里会同时留着两代块，
检索结果看起来「既像新的又像旧的」，而且没有任何报错。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import func, insert, select

from app.common.dbw import db_write
from app.common.errors import NotFoundError, ValidationError
from app.common.identity import owned_by
from app.common.logging import get_logger
from app.common.timeutil import utcnow_iso
from app.extensions import db
from app.models import (
    ChunkKeyword,
    CourseSource,
    Material,
    MaterialChunk,
    MaterialStats,
    PageSource,
    new_id,
)
from app.services.materials import chunking, indexer, parsers, policy, search

logger = get_logger("app.materials.store")

#: `uploading` 停留多久算「断了」。900 秒远大于一次正常上传（50MB 在慢网上也就
#: 几分钟），但短于「用户第二天回来发现它还挂在那儿」。
STALE_UPLOAD_SECONDS = 900

#: 收字节的块大小。1MB 是「内存里最多同时有一块」与「系统调用别太多」之间的折中。
_CHUNK = 1024 * 1024


# --- 读 ---


def list_materials(
    *, owner_id: str = "", status: str = "", limit: int = 100, offset: int = 0
) -> list[Material]:
    """当前用户的材料，新的在前。"""
    stmt = select(Material).order_by(Material.created_at.desc(), Material.id.desc())
    if owner_id:
        stmt = stmt.where(Material.owner_id == owner_id)
    if status:
        stmt = stmt.where(Material.status == status)
    stmt = stmt.limit(max(1, min(int(limit or 100), 500))).offset(max(0, int(offset or 0)))
    return list(db.session.scalars(stmt).all())


def get_material(material_id: str, *, owner_id: str = "") -> Material:
    """取一份材料；不存在或不属于当前用户 → 404（P4-F4，两种情况同一个码）。"""
    material = db.session.get(Material, str(material_id or ""))
    if material is None or not owned_by(material, owner_id):
        raise NotFoundError("材料不存在")
    return material


def detail(material_id: str, *, owner_id: str = "") -> dict:
    """详情：元信息 + 目录树（F4-6 的抽屉用）。"""
    material = get_material(material_id, owner_id=owner_id)
    data = material.to_dict()
    data["tree"] = tree_of(material.id)
    # 「材料过大，建议拆分」（F4-13）：提示挂在详情上，前端不用自己记这个阈值
    data["oversized"] = bool(material.char_count and material.char_count > policy.max_chars())
    return data


def tree_of(material_id: str) -> list[dict]:
    """分块目录树。节点是 `section_path`（`第 3 章 > 3.2 检索`）按 `>` 拆出来的。"""
    rows = db.session.execute(
        select(MaterialChunk.section_path, MaterialChunk.page_from)
        .where(MaterialChunk.material_id == material_id)
        .order_by(MaterialChunk.chunk_no)
    ).all()
    flat: dict[str, dict] = {}
    roots: list[dict] = []
    for section, page in rows:
        path = str(section or "").strip()
        if not path:
            continue
        node: dict | None = None
        prefix = ""
        for title in [part.strip() for part in path.split(">") if part.strip()]:
            prefix = f"{prefix} > {title}" if prefix else title
            current = flat.get(prefix)
            if current is None:
                current = {"title": title, "path": prefix, "chunkCount": 0, "page": None,
                           "children": []}
                flat[prefix] = current
                (node["children"] if node else roots).append(current)
            current["chunkCount"] += 1
            if current["page"] is None and page is not None:
                current["page"] = int(page)
            node = current
    return roots


def list_chunks(
    material_id: str,
    *,
    owner_id: str = "",
    page: int = 1,
    size: int = 50,
    section: str = "",
) -> dict:
    """分块分页（F4-6）。`section` 传章节路径时，连同它的子节点一起返回。"""
    material = get_material(material_id, owner_id=owner_id)
    stmt = select(MaterialChunk).where(MaterialChunk.material_id == material.id)
    if section:
        prefix = str(section).strip()
        stmt = stmt.where(
            (MaterialChunk.section_path == prefix)
            | (MaterialChunk.section_path.like(f"{prefix} > %"))
        )
    total = db.session.scalar(
        select(func.count()).select_from(stmt.subquery())
    )
    size = max(1, min(int(size or 50), 200))
    page = max(1, int(page or 1))
    rows = db.session.scalars(
        stmt.order_by(MaterialChunk.chunk_no).offset((page - 1) * size).limit(size)
    ).all()
    return {
        "total": int(total or 0),
        "page": page,
        "size": size,
        "items": [chunk.to_dict() for chunk in rows],
    }


def get_chunk(material_id: str, chunk_id: str, *, owner_id: str = "") -> MaterialChunk:
    """单个分块（溯源徽标点击后跳到的那一段）。"""
    material = get_material(material_id, owner_id=owner_id)
    chunk = db.session.get(MaterialChunk, str(chunk_id or ""))
    if chunk is None or chunk.material_id != material.id:
        raise NotFoundError("分块不存在")
    return chunk


# --- 上传 ---


def create_from_upload(file, *, owner_id: str = "") -> tuple[Material, bool]:
    """收下一份上传，返回 `(材料, 是否已存在)`。

    `已存在` 为真时（P4-C4）**不会**重新解析：同样的字节再拆一遍，得到的块与
    索引完全一样，用户的等待却要重来一次。唯一的例外是上一次解析失败了 ——
    那时候用户再传一次就是想重试，重复内容不该把他挡在门外。
    """
    if not policy.enabled():
        raise policy.disabled()
    name = policy.display_name(policy.require_name(getattr(file, "filename", "")))
    ext = policy.ext_of(name)
    policy.ensure_supported(ext)

    _prepare_root()
    _sweep_stale(owner_id)
    policy.clean_tmp()

    material = Material(
        owner_id=owner_id or None,
        name=name or f"material{ext}",
        ext=ext,
        status="uploading",
    )
    db_write(lambda: db.session.add(material))
    try:
        path, size, digest = _spool(file)
    except Exception:
        _discard(material.id)
        raise

    try:
        policy.check_size(size)
        policy.check_magic(path, ext)
        if size <= 0:
            raise ValidationError("文件是空的")
    except Exception:
        path.unlink(missing_ok=True)
        _discard(material.id)
        raise

    existing = _find_duplicate(owner_id, digest)
    if existing is not None and existing.status != "failed":
        path.unlink(missing_ok=True)
        _discard(material.id)
        return existing, True

    # 上一次解析失败的那一条**复用**（同一份内容不能有第二行：唯一约束不允许），
    # 刚落的占位行删掉。用户再传一次就是想重试，不该被自己上一次的失败挡住。
    row = existing if existing is not None else material
    if existing is not None:
        _discard(material.id)

    target = policy.physical_path(policy.rel_path(row.id, ext))
    if target is None:  # pragma: no cover - 自己生成的路径一定合法
        path.unlink(missing_ok=True)
        _discard(material.id)
        raise ValidationError("材料路径不合法")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, target)

    def finalize() -> None:
        row.name = name or row.name
        row.ext = ext
        row.size_bytes = size
        row.sha256 = digest
        row.file_path = policy.rel_path(row.id, ext)
        row.status = "parsing"
        row.error = ""

    db_write(finalize)
    submit_parse(row.id)
    return row, False


def _spool(file) -> tuple[Path, int, str]:
    """把上传流写到临时文件，边写边数字节与 sha256。

    不用 `file.read()` 一把梭：50MB 上限是「允许」不是「期望」，
    真要有人传 2GB，一把梭会先把内存吃光再报 413。
    """
    handle, raw_path = tempfile.mkstemp(prefix=policy.TMP_PREFIX, dir=str(policy.materials_root()))
    path = Path(raw_path)
    digest = hashlib.sha256()
    size = 0
    stream = getattr(file, "stream", file)
    with os.fdopen(handle, "wb") as out:
        while True:
            block = stream.read(_CHUNK)
            if not block:
                break
            size += len(block)
            if size > policy.max_bytes():
                # 早停：已经超了就不必把剩下的字节读完（也不该读）
                # 先关再删：Windows 上删一个还开着的文件会失败
                out.close()
                path.unlink(missing_ok=True)
                logger.warning("材料上传超限 size=%s cap=%s", size, policy.max_bytes())
                policy.check_size(size)  # 抛出 413，文案只有那一处
            digest.update(block)
            out.write(block)
    return path, size, digest.hexdigest()


def _find_duplicate(owner_id: str, digest: str) -> Material | None:
    if not digest:
        return None
    stmt = select(Material).where(Material.sha256 == digest)
    # owner 为空（还没跑种子）时按「都算同一个人的」比 —— 此时库里也只有他的东西
    stmt = stmt.where(Material.owner_id == (owner_id or None))
    return db.session.scalars(stmt.order_by(Material.created_at)).first()


def _discard(material_id: str) -> None:
    """把「先落行」留下的那一条删掉（校验没过时才会走到这儿）。"""
    row = db.session.get(Material, material_id)
    if row is not None:
        db_write(lambda: db.session.delete(row))


def _prepare_root() -> None:
    root = policy.materials_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.exception("材料目录不可用 path=%s", root.name)
        raise ValidationError("材料目录不可用，请检查服务器配置") from exc


def _sweep_stale(owner_id: str) -> None:
    """把「上传中途断了」的记录标成失败。

    判据要**同时**满足「停了很久」与「盘上没有文件」：只看时间会把一个正在
    慢速上传的记录误杀（它在收字节期间不会更新 `updated_at`）。
    """
    deadline = (datetime.now(timezone.utc) - timedelta(seconds=STALE_UPLOAD_SECONDS)).isoformat()
    stmt = select(Material).where(Material.status == "uploading")
    if owner_id:
        stmt = stmt.where(Material.owner_id == owner_id)
    stale = [
        row
        for row in db.session.scalars(stmt).all()
        if (row.updated_at or "") < deadline and policy.file_of(row) is None
    ]
    if not stale:
        return

    def mark() -> None:
        for row in stale:
            row.status = "failed"
            row.error = "上传中断，请重新上传"

    db_write(mark)
    logger.info("清理中断的上传 count=%s", len(stale))


# --- 解析 ---


def submit_parse(material_id: str) -> bool:
    """丢给后台线程池。key 加 `material:` 前缀以避免与生成任务的 jobId 撞车。"""
    from app.common.tasks import get_runner

    return get_runner().submit(f"material:{material_id}", lambda: parse_material(material_id))


def parse_material(material_id: str) -> bool:
    """解析 → 分块 → 建索引 → 落库（P4-B1 的后台那一段）。

    返回是否成功。**不往上抛异常**：调用它的是线程池，抛出去也没人接；
    失败的原因写在 `material.error` 里给用户看，堆栈进服务端日志。
    """
    material = db.session.get(Material, material_id)
    if material is None:
        return False
    path = policy.file_of(material)
    if path is None:
        _fail(material_id, "原文件不在服务器上，请重新上传")
        return False
    ext = material.ext
    db_write(lambda: _set_status(material_id, "parsing"))

    try:
        doc = parsers.parse(path, ext)
        chunks = chunking.split(
            doc.blocks, target=policy.chunk_chars(), overlap=policy.chunk_overlap()
        )
        result = indexer.build(chunks)
    except parsers.ParseError as exc:
        _fail(material_id, str(exc))
        return False
    except Exception as exc:  # 任何解析库的崩溃都不该带走进程
        logger.exception("材料解析失败 id=%s type=%s", material_id, type(exc).__name__)
        _fail(material_id, "解析失败：文件可能损坏或含有不支持的内容")
        return False

    if not chunks:
        _fail(material_id, "这份文件里没有可用的文字内容")
        return False
    if doc.notes:
        logger.info("材料解析提示 id=%s notes=%s", material_id, "；".join(doc.notes))

    db_write(lambda: _save(material_id, doc.chars, doc.pages, chunks, result))
    return True


def _set_status(material_id: str, status: str) -> None:
    row = db.session.get(Material, material_id)
    if row is not None:
        row.status = status


def _fail(material_id: str, reason: str) -> None:
    """失败时**清掉派生数据**：留着半份索引比没有索引更糟（它看起来是好的）。"""

    def run() -> None:
        row = db.session.get(Material, material_id)
        if row is None:
            return
        _clear_derived(material_id)
        row.status = "failed"
        row.error = reason[:512]
        row.chunk_count = 0

    db_write(run)
    logger.warning("材料失败 id=%s reason=%s", material_id, reason)


def _clear_derived(material_id: str) -> None:
    """删掉这份材料派生出来的一切（块、倒排、统计）。外键 CASCADE 管倒排。"""
    db.session.execute(
        MaterialChunk.__table__.delete().where(MaterialChunk.material_id == material_id)
    )
    db.session.execute(
        MaterialStats.__table__.delete().where(MaterialStats.material_id == material_id)
    )


def _save(
    material_id: str, chars: int, pages: int, chunks: Sequence[chunking.Chunk], result
) -> None:
    """把一次解析的产物写进库（先删后写，P4-C5）。"""
    _clear_derived(material_id)
    stamp = utcnow_iso()
    chunk_rows = [
        {
            "id": new_id(),
            "material_id": material_id,
            "chunk_no": chunk.chunk_no,
            "page_from": chunk.page_from,
            "page_to": chunk.page_to,
            "section_path": chunk.section_path[:255],
            "text": chunk.text,
            "char_count": chunk.char_count,
            "tokens": chunk.tokens,
            "created_at": stamp,
            "updated_at": stamp,
        }
        for chunk in chunks
    ]
    if chunk_rows:
        db.session.execute(insert(MaterialChunk), chunk_rows)
    keyword_rows: list[dict] = []
    for chunk_row, keywords in zip(chunk_rows, result.keywords, strict=False):
        keyword_rows.extend(
            {"chunk_id": chunk_row["id"], "keyword": word, "tf": tf} for word, tf in keywords
        )
    if keyword_rows:
        # 一条一条 add 的话，10 万字的材料会有几万次 ORM 往返（P4-D2 要求 ≤ 5s）
        db.session.execute(insert(ChunkKeyword), keyword_rows)
    db.session.add(
        MaterialStats(
            material_id=material_id,
            doc_count=result.doc_count,
            avg_doc_len=result.avg_doc_len,
            keyword_df_json=_dump_df(result.df),
        )
    )
    material_row = db.session.get(Material, material_id)
    if material_row is not None:
        material_row.char_count = chars
        material_row.pages = pages
        material_row.chunk_count = len(chunks)
        material_row.status = "ready"
        material_row.error = ""


def _dump_df(df: dict[str, int]) -> str:
    """`df` 存成一行紧凑 JSON。`sort_keys` 是为了让两份相同语料的库内容逐字节相同
    —— 排查「索引到底有没有变」时，这比肉眼扫一遍几万行的字典有用得多。"""
    return json.dumps(df, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


# --- 删除 ---


def impact(material_id: str, *, owner_id: str = "") -> dict:
    """删之前先算影响面（P4-A13：「3 页引用将失效」）。

    数的是 `page_sources` 里的行：那是「课里的哪一页引用了它」这笔账，
    页面 DSL 里那份 `sources` 是给前端显示用的（见 `models/material.py` 的头注释）。
    """
    material = get_material(material_id, owner_id=owner_id)
    rows = db.session.execute(
        select(PageSource.page_id, PageSource.page_no, MaterialChunk.chunk_no)
        .join(MaterialChunk, MaterialChunk.id == PageSource.chunk_id, isouter=True)
        .where(PageSource.material_id == material.id)
    ).all()
    page_ids = {row[0] for row in rows}
    courses = db.session.execute(
        select(CourseSource.course_id).where(CourseSource.material_id == material.id)
    ).all()
    return {
        "fileId": material.id,
        "name": material.name,
        "pages": len(page_ids),
        "citations": len(rows),
        "courses": [row[0] for row in courses],
    }


def delete_material(material_id: str, *, owner_id: str = "") -> dict:
    """删材料：库里的行（级联带走分块/索引/溯源）+ 盘上的目录（P4-C1 / P4-C3）。"""
    material = get_material(material_id, owner_id=owner_id)
    payload = material.to_dict()
    material_id = material.id
    db_write(lambda: db.session.delete(material))
    removed = policy.purge_files(material)
    logger.info("材料已删除 id=%s files=%s", material_id, removed)
    return {"fileId": material_id, "name": payload["name"], "removedFiles": removed}


# --- 检索 ---


def search_materials(
    query: str,
    *,
    owner_id: str = "",
    file_ids: Sequence[str] | None = None,
    top_k: int = 8,
) -> list[search.Hit]:
    """在工作台里检索（F4-5）。`file_ids` 为空 = 检索当前用户的全部材料。"""
    ids = _searchable_ids(owner_id, file_ids)
    if not ids:
        return []
    return search.search(query, material_ids=ids, top_k=top_k)


def _searchable_ids(owner_id: str, file_ids: Sequence[str] | None) -> list[str]:
    """把「用户想搜哪几份」收敛成「他确实能搜哪几份」（P4-F4）。"""
    stmt = select(Material.id).where(Material.status == "ready")
    if owner_id:
        stmt = stmt.where(Material.owner_id == owner_id)
    wanted = [str(item) for item in (file_ids or []) if item]
    if wanted:
        stmt = stmt.where(Material.id.in_(wanted))
    return [row[0] for row in db.session.execute(stmt).all()]


def material_ids_of_course(course_id: str) -> list[str]:
    """一门课关联的材料 id（生成时按它检索，F4-7）。"""
    rows = db.session.execute(
        select(CourseSource.material_id).where(CourseSource.course_id == course_id)
    ).all()
    return [row[0] for row in rows]


def materials_of_course(course_id: str, *, owner_id: str = "") -> list[Material]:
    """一门课关联的材料（工作台抽屉里标「已加入」用，P4-7）。

    按 `added_at` 排：抽屉里的顺序与用户「先后加了哪几份」一致，而不是按 id
    随机 —— 一份材料的 id 是随机的，按它排等于每次刷新换个顺序。
    """
    stmt = (
        select(Material)
        .join(CourseSource, CourseSource.material_id == Material.id)
        .where(CourseSource.course_id == str(course_id or ""))
        .order_by(CourseSource.added_at, Material.id)
    )
    if owner_id:
        stmt = stmt.where(Material.owner_id == owner_id)
    return list(db.session.scalars(stmt).all())


# --- 与课程的关联（P4-A13 / F4-14 的存储侧，接口在 P4-3）---


def attach_to_course(course_id: str, material_ids: Sequence[str], *, owner_id: str = "") -> dict:
    """把材料关联到课程。已经关联过的不重复写（自然主键会挡，这里先查再插）。"""
    from app.models import Course

    course = db.session.get(Course, str(course_id or ""))
    if course is None or not owned_by(course, owner_id):
        raise NotFoundError("课程不存在")
    added: list[str] = []
    skipped: list[str] = []
    links: list[CourseSource] = []
    for material_id in [str(item) for item in material_ids if item]:
        material = get_material(material_id, owner_id=owner_id)
        if material.status != "ready":
            raise ValidationError("材料还没解析完，暂时不能加入课程")
        if db.session.get(CourseSource, (course.id, material.id)) is not None:
            skipped.append(material.id)
            continue
        added.append(material.id)
        links.append(
            CourseSource(course_id=course.id, material_id=material.id, added_at=utcnow_iso())
        )
    if links:
        db_write(lambda: db.session.add_all(links))
    return {"added": added, "skipped": skipped, "courseId": course.id}


def detach_from_course(course_id: str, material_id: str, *, owner_id: str = "") -> dict:
    """从课程移除材料（F4-14）。引用行跟着外键走，这里只报影响面给接口回话。"""
    from app.models import Course

    course = db.session.get(Course, str(course_id or ""))
    if course is None or not owned_by(course, owner_id):
        raise NotFoundError("课程不存在")
    material = get_material(material_id, owner_id=owner_id)
    link = db.session.get(CourseSource, (course.id, material.id))
    if link is None:
        raise NotFoundError("这门课没有关联这份材料")
    affected = db.session.execute(
        select(func.count()).select_from(PageSource).where(PageSource.material_id == material.id)
    ).scalar()
    db_write(lambda: db.session.delete(link))
    return {
        "courseId": course.id,
        "fileId": material.id,
        "affectedCitations": int(affected or 0),
    }


def purge_course(course_id: str) -> int:
    """删课时的收尾：解开关联即可，材料本身留着（它属于用户，不属于这门课）。"""
    rows = list(
        db.session.execute(
            select(CourseSource).where(CourseSource.course_id == course_id)
        ).scalars()
    )
    if not rows:
        return 0

    def drop() -> None:
        for row in rows:
            db.session.delete(row)

    db_write(drop)
    return len(rows)


def stats() -> dict[str, Any]:
    """给脚本与调试页看的一眼数字（`accept_p4.py` 会打印它）。"""
    total = db.session.scalar(select(func.count()).select_from(Material)) or 0
    chunks = db.session.scalar(select(func.count()).select_from(MaterialChunk)) or 0
    keywords = db.session.scalar(select(func.count()).select_from(ChunkKeyword)) or 0
    pages = db.session.scalar(select(func.count()).select_from(PageSource)) or 0
    return {
        "materials": int(total),
        "chunks": int(chunks),
        "keywords": int(keywords),
        "pageSources": int(pages),
    }


__all__ = [
    "STALE_UPLOAD_SECONDS",
    "attach_to_course",
    "create_from_upload",
    "delete_material",
    "detach_from_course",
    "detail",
    "get_chunk",
    "get_material",
    "impact",
    "list_chunks",
    "list_materials",
    "material_ids_of_course",
    "materials_of_course",
    "parse_material",
    "purge_course",
    "search_materials",
    "stats",
    "submit_parse",
    "tree_of",
]
