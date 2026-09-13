"""材料总开关、白名单与落盘位置（P4-F1 / P4-C3 / P4-G3）。

这一层是材料域的**门口**：字节进门之前要过三关（后缀在白名单里、大小在上限内、
内容与后缀相符），进门之后要有一个**确定的位置**待着。三关的顺序不是随意的 ——
先查后缀（最便宜、能立刻给出可操作的提示），再看大小（不读完整个文件就没法确定，
所以边收边数），最后验内容（要落地或读中央目录才知道）。

两处与 P2 音频刻意保持一致的地方，因为它们解决的是同一类问题：

1. **盘上的名字由我们生成，用户给的名字只进库**。音频那边是
   `{course_id}/{beat_id}_{digest}.mp3`，这里是 `{material_id}/source{ext}` ——
   一个字节的用户输入都不进路径，于是「把 `../` 传进文件名」这件事从根上不存在。
   用户看到的名字（`Material.name`）只在界面与下载头里出现，下载时按 RFC 5987 编码。
2. **库里只存相对路径**（P4-C3）。`MATERIAL_DIR` 换成别处，库里一行都不用改；
   `physical_path()` 会把落在材料根目录之外的路径判为无效，而不是照着读。

内容校验（P4-F1）为什么值得写：改后缀的成本极低，而下游要为此付出的代价很高 ——
把 `.doc`（老式 OLE2）改名成 `.docx` 传上来，python-docx 会抛一个「不是一个 zip」
的内部异常，用户看到的是「解析失败」，去查日志才发现是格式不对。这里直接按
**文件头**拒掉，并且在提示里说清楚「它其实是什么」。
"""

from __future__ import annotations

import codecs
import contextlib
import re
import time
import zipfile
from pathlib import Path

from flask import current_app, has_app_context

from app.common.errors import (
    AppError,
    PayloadTooLargeError,
    UnsupportedMediaError,
    ValidationError,
)
from app.common.logging import get_logger
from app.common.response import MESSAGES
from app.models import MATERIAL_EXTS

logger = get_logger("app.materials.policy")

#: 落库的相对路径前缀。与音频的 `assets/audio` 同一条口径：**是个标记，不是路径**。
#: 真正的根目录由 `MATERIAL_DIR` 解出来，所以改了配置也不会与库里的值对不上。
MATERIAL_SUBDIR = "materials"

#: 上传时的临时文件名。它以 `.` 开头，`_clean_tmp()` 只清这种名字的东西 ——
#: 用户传上来一个叫 `tmp` 的文件也不会被误删。
TMP_PREFIX = ".upload-"

#: 材料功能关着（P4-G3）。归在 4xxxx：这是**部署方的一个决定**，
#: 与 40302（语音关着）同一种性质，前端显示提示条而不是错误弹窗。
MATERIAL_DISABLED_CODE = 40303

#: 目录名 / 文件名片段的白名单（与 `voice.assets._UNSAFE` 同一条正则）。
_UNSAFE = re.compile(r"[^0-9A-Za-z_-]+")

#: 展示名里要清掉的东西：路径分隔符（防串目录）、控制字符（防下载头注入）、
#: 以及前后空白。其余字符一律保留 —— 中文文件名是常态，不是异常。
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]")

#: 文件头。四种格式里 docx/pptx 都是 zip（靠中央目录里的条目名分辨），
#: PDF 有自己的头；纯文本没有头，只能靠「能不能当文本解出来」判。
PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
#: 老式 OLE2（`.doc`/`.ppt`/`.xls`）。它是最常见的那种「改了后缀」的伪装。
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
DOCX_ENTRY = "word/document.xml"
PPTX_ENTRY = "ppt/presentation.xml"

#: 校验内容时要读多少字节。PDF 的头在最前面；zip 的门牌是 OLE/zip 那四五个字节。
PROBE_BYTES = 4096

#: 「你多半是想传这个」的提示表。415 只说「不支持」用户会一头雾水 ——
#: 他手上那个文件明明叫「讲义.docx」。说清楚要另存成什么才有下一步。
_HINTS = {
    ".doc": "老式 .doc 请用 Word 另存为 .docx",
    ".ppt": "老式 .ppt 请用 PowerPoint 另存为 .pptx",
    ".xls": "表格暂不支持，请导出为 .md 或 .txt",
    ".xlsx": "表格暂不支持，请导出为 .md 或 .txt",
    ".rtf": "请另存为 .docx 或 .txt",
    ".html": "请另存为 .md 或 .txt",
    ".htm": "请另存为 .md 或 .txt",
    ".epub": "请先转成 .pdf 或 .docx",
    ".wps": "请用 WPS 另存为 .docx 或 .pdf",
}


class MaterialDisabledError(AppError):
    """材料总开关关着（`MATERIAL_ENABLED=false`，P4-G3）。

    `data` 的形状与 40302 对齐（平铺的 `ok/error`）：这两个错误在前端是同一段
    代码处理的 —— 都是「这个能力没开，走回原来那条路」，形状不同就得写两个分支。
    """

    code = MATERIAL_DISABLED_CODE
    http_status = 403

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or MESSAGES[MATERIAL_DISABLED_CODE])
        self.details = {"ok": False, "error": "material_disabled"}

    def to_envelope(self):
        from app.common.response import fail_with_data

        return fail_with_data(
            self.code,
            dict(self.details),
            self.message,
            self.http_status,
        )


def enabled() -> bool:
    """材料总开关。缺配置时按**开**处理（同 `voice_enabled`）。"""
    return bool(current_app.config.get("MATERIAL_ENABLED", True))


def disabled() -> MaterialDisabledError:
    return MaterialDisabledError()


def max_bytes() -> int:
    """单份材料的字节上限（P4-B1 要 50MB）。"""
    return int(current_app.config.get("MATERIAL_MAX_BYTES") or 50 * 1024 * 1024)


def chunk_chars() -> int:
    return int(current_app.config.get("MATERIAL_CHUNK_CHARS") or 600)


def chunk_overlap() -> int:
    return int(current_app.config.get("MATERIAL_CHUNK_OVERLAP") or 60)


def max_chars() -> int:
    """超过它就在详情里挂一句「材料过大，建议拆分」（F4-13）。"""
    return int(current_app.config.get("MATERIAL_MAX_CHARS") or 200_000)


# --- 名字 ---


def ext_of(name: str) -> str:
    """取小写扩展名（含点）。没有后缀或后缀过长的一律当空串，交给 `ensure_supported` 拒。"""
    suffix = Path(str(name or "").strip()).suffix.lower()
    return suffix if 1 < len(suffix) <= 16 else ""


def display_name(name: str, *, limit: int = 255) -> str:
    """用户给的名字 → 能安全显示、能放进下载头的名字。

    只清控制字符与路径分隔符，不动中文与空格：把「第三章 检索.pdf」改成
    「第三章_检索.pdf」是**改用户的东西**，而它本来也不进路径。
    """
    cleaned = _UNSAFE_NAME.sub("", str(name or "")).strip()
    cleaned = cleaned.lstrip(".") or ""  # 前导点在下载头里会被当成隐藏文件
    return cleaned[:limit]


def safe_token(value: str, *, limit: int = 48) -> str:
    """目录名/文件名的片段（同 `voice.assets.safe_token`）。"""
    return _UNSAFE.sub("_", str(value or "")).strip()[:limit] or "x"


def ensure_supported(ext: str) -> None:
    """后缀必须在白名单里（F4-1），否则 415。"""
    if ext in MATERIAL_EXTS:
        return
    hint = _HINTS.get(ext or "")
    if hint:
        raise UnsupportedMediaError(f"暂不支持 {ext} 格式：{hint}")
    raise UnsupportedMediaError(
        f"暂不支持 {ext or '无后缀'} 格式：只支持 {'、'.join(MATERIAL_EXTS)}"
    )


# --- 落盘 ---


def materials_root() -> Path:
    """材料根目录（物理路径）。

    没有应用上下文时也答得上来（退回默认目录）：分词要读材料根目录下的
    `userdict.txt`，而分词是个纯函数 —— 为它套一个应用上下文，会让
    「用几个词试一下检索」这种调用变成必须先把整个 app 建起来。
    """
    configured = current_app.config.get("MATERIAL_DIR") if has_app_context() else None
    if configured:
        return Path(str(configured))
    from app.config import BACKEND_DIR

    return BACKEND_DIR / "data" / "materials"


def rel_dir(material_id: str) -> str:
    return f"{MATERIAL_SUBDIR}/{safe_token(material_id)}"


def rel_path(material_id: str, ext: str) -> str:
    """落库用的逻辑相对路径（P4-C3）。文件名是我们生成的，不含用户输入的任何一个字节。"""
    return f"{rel_dir(material_id)}/source{ext}"


def physical_path(rel: str) -> Path | None:
    """逻辑相对路径 → 物理路径。落在材料根目录之外的一律判无效（返回 None）。

    有效性在这里判，而不是信任库里那一列 —— 与音频那边同一条理由：约束管得住
    我们自己写的行，管不住有人拿 sqlite3 手改。多一次判断换来「不会被读到任意文件」。
    """
    rel = str(rel or "")
    prefix = MATERIAL_SUBDIR + "/"
    if not rel.startswith(prefix) or ".." in rel:
        return None
    root = materials_root().resolve()
    target = (root / rel[len(prefix) :]).resolve()
    if root != target and root not in target.parents:
        return None
    return target


def file_of(material) -> Path | None:
    """材料那一行对应的原文件；路径不合法或文件不在则 None。

    行在而文件不在是**正常会发生的**（有人清了 `data/`），调用方按「没有文件」
    处理，而不是把它当成数据库坏了。
    """
    path = physical_path(getattr(material, "file_path", ""))
    if path is None or not path.is_file():
        return None
    return path


def purge_files(material) -> int:
    """删掉这份材料在盘上的整个目录，返回删掉的文件数。

    目录名是从 `file_path` 解出来的，不是从 `material.id` 拼的：后者在
    「id 是我们生成的」这条前提被打破时会删错地方，而前者会先过 `physical_path`。
    """
    path = physical_path(getattr(material, "file_path", ""))
    if path is None:
        return 0
    folder = path.parent
    root = materials_root().resolve()
    if folder == root or root not in folder.parents:
        # 只删材料根目录**里面**的一层目录，绝不往根上删
        return 0
    removed = 0
    for item in sorted(folder.glob("**/*"), reverse=True):
        try:
            if item.is_file():
                item.unlink()
                removed += 1
            elif item.is_dir():
                item.rmdir()
        except OSError:  # pragma: no cover - 文件被占用（Windows 上常见）时跳过
            logger.warning("删除材料文件失败 path=%s", item.name)
    with contextlib.suppress(OSError):  # pragma: no cover - 目录还被占用（Windows）
        folder.rmdir()
    return removed


def clean_tmp(*, max_age: float = 3600.0) -> int:
    """清掉上传落下的临时文件（正常路径上它们会被 `os.replace` 搬走）。

    只在材料根目录里扫，且只认 `TMP_PREFIX` 开头的名字 —— 用户传一个叫
    `tmp` 的文件不会因此被删。
    """
    root = materials_root()
    if not root.is_dir():
        return 0
    now = time.time()
    removed = 0
    for item in root.glob(f"{TMP_PREFIX}*"):
        try:
            if item.is_file() and now - item.stat().st_mtime > max_age:
                item.unlink()
                removed += 1
        except OSError:  # pragma: no cover
            continue
    return removed


# --- 内容校验（P4-F1）---


def check_magic(path: Path, ext: str) -> None:
    """文件内容必须与后缀相符，否则 415。

    四种扩展名分三类判法：PDF 认头、docx/pptx 认 zip 里的条目名、纯文本认
    「能不能当文本解出来」。判错的方向是**放行不了的文件被拒**（假阴性），
    不会把不安全的文件放进来（假阳性）—— 这里宁可严一点。
    """
    head = _head_of(path)
    if ext == ".pdf":
        if not head.startswith(PDF_MAGIC):
            raise UnsupportedMediaError(_disguise(head, ".pdf"))
        return
    if ext in (".docx", ".pptx"):
        if head.startswith(OLE_MAGIC):
            # 最典型的一种：老式 Office 文件改个后缀。
            raise UnsupportedMediaError(
                f"这个文件其实是老式 Office 格式，不是 {ext}：请另存为 {ext} 后再上传"
            )
        if not head.startswith(ZIP_MAGIC):
            raise UnsupportedMediaError(_disguise(head, ext))
        entry = DOCX_ENTRY if ext == ".docx" else PPTX_ENTRY
        if not _has_entry(path, entry):
            raise UnsupportedMediaError(
                f"这个压缩包里没有 {entry}，不像是 {ext} 文件"
            )
        return
    # .md / .txt：没有头可认，只要求它是**文本**
    _ensure_text(path, ext)


def _head_of(path: Path, size: int = PROBE_BYTES) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def _has_entry(path: Path, entry: str) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
    return entry in names


def _disguise(head: bytes, ext: str) -> str:
    """给「内容与后缀不符」配一句能指向下一步的话。"""
    if head.startswith(OLE_MAGIC):
        return f"这个文件其实是老式 Office 格式，不是 {ext}：请另存为 {ext} 后再上传"
    if head.startswith(PDF_MAGIC):
        return "这个文件其实是一份 PDF：请把后缀改成 .pdf 再上传"
    if head[:2] == b"\xff\xd8" or head[:8] == b"\x89PNG\r\n\x1a\n":
        return "这是一张图片，不是文档：扫描件需要 OCR，当前版本暂不支持"
    return f"文件内容与后缀 {ext} 不符，可能改过后缀名"


def _ensure_text(path: Path, ext: str) -> None:
    """纯文本的「魔数」：能解码、且没有 NUL 字节。

    不校验编码是哪种 —— GBK 的讲义与 UTF-8 的讲义都是讲义（解析时会两种都试）。
    但带 NUL 的二进制文件（.exe/.zip 改名成 .txt）一律拒。
    """
    head = _head_of(path)
    if b"\x00" in head:
        raise UnsupportedMediaError(_disguise(head, ext))
    for encoding in ("utf-8", "gbk"):
        if _decodable(head, encoding):
            return
    raise UnsupportedMediaError(f"这个文件既不是 UTF-8 也不是 GBK 文本，不像 {ext} 文件")


def _decodable(sample: bytes, encoding: str) -> bool:
    """样本能不能按 `encoding` 解出来。**末尾允许切在半个字上**。

    `_head_of` 是按字节切的：UTF-8 一个汉字 3 字节、GBK 2 字节，`PROBE_BYTES`
    落在字中间的概率有三分之二。严格解码就会把一份完好无损的 UTF-8 讲义判成
    「既不是 UTF-8 也不是 GBK」——**切在字中间与「这不是文本」是两件事**。

    用增量解码器（`final=False`）判，而不是「依次去掉末尾 0~3 个字节再试」：
    它只把「一个字符还没收全」当成可以等下一块，真错的字节当场就抛。两者的
    差别正好落在我们要的那条线上 ——

    - `b"…\\xe4\\xb8"`（半个「中」）：留着等下一块，放行；
    - `b"\\xff"`：它压根不是任何字符的开头，去掉尾巴那套会把它当成「切在
      半个字上」（丢掉这 1 个字节就剩空串，空串当然解得开），这里照拒。

    真解析那一步本来就是宽松解码（`parsers` 用 `errors="replace"`），
    这里跟着它松，两处的口径才一致。
    """
    decoder = codecs.getincrementaldecoder(encoding)()
    try:
        decoder.decode(sample)
    except UnicodeDecodeError:
        return False
    return True


def check_size(size: int, *, limit: int | None = None) -> None:
    """字节数超过上限 → 413。调用方负责在**边收边数**的过程中调它（P4-B1）。"""
    cap = limit if limit is not None else max_bytes()
    if size > cap:
        raise PayloadTooLargeError(
            f"文件超过 {cap // (1024 * 1024)}MB 上限，请压缩或拆分后再上传"
        )


def require_name(raw: str | None) -> str:
    """上传必须带文件名 —— 没有名字就无从判断格式，也没法在列表里显示。"""
    name = str(raw or "").strip()
    if not name:
        raise ValidationError("上传缺少文件名")
    return name


__all__ = [
    "DOCX_ENTRY",
    "MATERIAL_DISABLED_CODE",
    "MATERIAL_SUBDIR",
    "OLE_MAGIC",
    "PDF_MAGIC",
    "PPTX_ENTRY",
    "TMP_PREFIX",
    "ZIP_MAGIC",
    "MaterialDisabledError",
    "check_magic",
    "check_size",
    "chunk_chars",
    "chunk_overlap",
    "clean_tmp",
    "disabled",
    "display_name",
    "enabled",
    "ensure_supported",
    "ext_of",
    "file_of",
    "materials_root",
    "max_bytes",
    "max_chars",
    "physical_path",
    "purge_files",
    "rel_dir",
    "rel_path",
    "require_name",
    "safe_token",
]
