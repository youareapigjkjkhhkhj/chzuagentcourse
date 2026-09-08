"""问答服务：检索编排 + 流式 / 非流式回答。"""
import json
from typing import Dict, Any, Iterator, List, Tuple
from src.config import settings
from src.rag.vectorstore import VectorStoreManager
from src.rag.chain import get_llm, build_prompt, format_docs


def _sse(payload: Dict[str, Any]) -> str:
    """将事件编码为 SSE 行。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class QAService:
    """问答编排器：检索 -> 拼装上下文 -> 大模型生成。"""

    def __init__(self):
        self.mgr = VectorStoreManager()

    def _retrieve(self, question: str, top_k: int) -> List[Tuple]:
        results = self.mgr.similarity_search(question, k=top_k)
        return [(d, score) for d, score in results]

    @staticmethod
    def _sources(results) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for d, score in results:
            src = d.metadata.get("source", "未知")
            if src not in seen:
                seen.add(src)
                out.append({"source": src, "score": round(float(score), 4)})
        return out

    def ask(self, question: str, top_k: int = None) -> Dict[str, Any]:
        """非流式问答：返回 {answer, sources}。"""
        if not self.mgr.exists():
            raise RuntimeError("知识库尚未构建，请先上传笔记并构建索引。")
        top_k = top_k or settings.TOP_K
        results = self._retrieve(question, top_k)
        context = format_docs([d for d, _ in results])
        chain = build_prompt() | get_llm()
        resp = chain.invoke({"context": context, "question": question})
        return {"answer": resp.content, "sources": self._sources(results)}

    def ask_stream(self, question: str, top_k: int = None) -> Iterator[str]:
        """流式问答：逐 token 推送 SSE 事件，结束推送 sources。"""
        if not self.mgr.exists():
            yield _sse({"type": "error", "message": "知识库尚未构建，请先上传笔记并构建索引。"})
            return
        top_k = top_k or settings.TOP_K
        results = self._retrieve(question, top_k)
        context = format_docs([d for d, _ in results])
        llm = get_llm(streaming=True)
        messages = build_prompt().format_prompt(context=context, question=question).to_messages()
        for chunk in llm.stream(messages):
            if chunk.content:
                yield _sse({"type": "token", "content": chunk.content})
        yield _sse({"type": "done", "sources": self._sources(results)})
