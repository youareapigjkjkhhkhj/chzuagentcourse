"""笔记服务：文件管理 + 知识库索引构建。"""
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Any
from src.config import settings
from src.rag.loader import load_document, is_supported
from src.rag.splitter import split_documents
from src.rag.vectorstore import VectorStoreManager


def _safe_name(filename: str) -> str:
    """保留中文，去除路径危险字符，生成安全文件名。"""
    name = Path(filename).name
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    if not name.strip():
        name = f"note_{int(time.time())}"
    return name


def list_notes() -> List[Dict[str, Any]]:
    """列出已上传笔记（按修改时间倒序）。"""
    notes = []
    if settings.NOTES_DIR.exists():
        for p in sorted(settings.NOTES_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file() and is_supported(p.name):
                notes.append({
                    "id": p.name,
                    "name": p.name,
                    "size": p.stat().st_size,
                    "updated_at": int(p.stat().st_mtime),
                })
    return notes


def save_note(file_storage, original_filename: str) -> Dict[str, Any]:
    """保存上传的笔记文件，返回元信息。"""
    name = _safe_name(original_filename)
    dest = settings.NOTES_DIR / name
    if dest.exists():
        stem, ext = os.path.splitext(name)
        name = f"{stem}_{int(time.time())}{ext}"
        dest = settings.NOTES_DIR / name
    file_storage.save(str(dest))
    return {
        "id": name,
        "name": name,
        "size": dest.stat().st_size,
        "updated_at": int(dest.stat().st_mtime),
    }


def get_note_content(note_id: str) -> str:
    """读取笔记原文（用于前端展示）。"""
    p = settings.NOTES_DIR / note_id
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"笔记不存在: {note_id}")
    return p.read_text(encoding="utf-8", errors="ignore")


def delete_note(note_id: str) -> bool:
    """删除笔记；删除后向量索引失效，需重建。"""
    p = settings.NOTES_DIR / note_id
    if p.exists() and p.is_file():
        p.unlink()
        VectorStoreManager().delete()
        return True
    return False


def build_index() -> Dict[str, Any]:
    """全量重建 FAISS 索引：清空旧索引 -> 加载全部笔记 -> 切分 -> 入库。"""
    VectorStoreManager().delete()
    docs = []
    note_count = 0
    for meta in list_notes():
        note_count += 1
        docs.extend(load_document(str(settings.NOTES_DIR / meta["id"])))
    if not docs:
        raise RuntimeError("没有可索引的笔记，请先上传。")
    chunks = split_documents(docs)
    vs = VectorStoreManager().build(chunks)
    return {
        "note_count": note_count,
        "chunk_count": len(chunks),
        "vector_count": vs.index.ntotal,
    }


def index_status() -> Dict[str, Any]:
    """返回索引与笔记数量状态。"""
    mgr = VectorStoreManager()
    notes = list_notes()
    status: Dict[str, Any] = {"indexed": mgr.exists(), "note_count": len(notes)}
    if mgr.exists():
        try:
            status["vector_count"] = mgr.load().index.ntotal
        except Exception:
            status["vector_count"] = None
    return status
