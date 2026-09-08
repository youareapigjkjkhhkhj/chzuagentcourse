"""项目一端到端冒烟测试（单进程，无需起独立服务）。

覆盖顺序：
  1. 笔记列表（确认示例笔记存在）
  2. 构建 FAISS 索引（触发 embedding 调用）
  3. 问答检索（触发 LLM 调用，验证溯源）
  4. 流式问答（验证 SSE 流式输出）

运行：
  cd 源码/backend
  PYTHONPATH=. .venv/Scripts/python.exe tests/test_full_flow.py

注意：第 2~4 步会真实调用大模型 API。若遇到 429 频率限制，
请稍后（额度重置后）再运行，或在前端「知识库管理」中点击「构建知识库」。
"""
import json
import sys
import traceback
from src.config import settings
from src.services import note_service
from src.services.qa_service import QAService


def section(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    # 1. 笔记列表
    section("1. 笔记列表")
    notes = note_service.list_notes()
    print(f"   发现笔记 {len(notes)} 篇：{[n['name'] for n in notes]}")
    if not notes:
        print("   [FAIL] 没有笔记，请确认 data/notes/ 下存在示例笔记")
        return 1

    # 2. 构建索引
    section("2. 构建 FAISS 索引")
    try:
        idx = note_service.build_index()
        print(f"   结果：{idx}")
        if idx.get("chunk_count", 0) == 0:
            print("   [FAIL] 索引为空")
            return 1
    except Exception as e:
        print(f"   [ERROR] 构建索引失败：{e}")
        if "429" in str(e) or "频率" in str(e):
            print("   [提示] 命中 API 频率限制，请额度重置后重试（不影响代码正确性）。")
        traceback.print_exc()
        return 2

    # 3. 非流式问答
    section("3. 非流式问答（带溯源）")
    try:
        qa = QAService()
        ans = qa.ask("本助手基于什么技术栈？")
        print(f"   回答：{ans['answer'][:200]}")
        print(f"   来源笔记：{[s['source'] for s in ans['sources']]}")
        if not ans["answer"]:
            print("   [FAIL] 回答为空")
            return 3
    except Exception as e:
        print(f"   [ERROR] 问答失败：{e}")
        if "429" in str(e) or "频率" in str(e):
            print("   [提示] 命中 API 频率限制，请额度重置后重试。")
        traceback.print_exc()
        return 3

    # 4. 流式问答（SSE 字符串逐行解析）
    section("4. 流式问答")
    try:
        qa = QAService()
        chunks, sources = [], None
        for sse in qa.ask_stream("如何构建知识库？"):
            # sse 形如 "data: {json}\n\n"
            if not sse.startswith("data:"):
                continue
            payload = json.loads(sse[len("data:"):].strip())
            if payload.get("type") == "token":
                chunks.append(payload["content"])
            elif payload.get("type") == "done":
                sources = payload.get("sources")
        full = "".join(chunks)
        print(f"   流式拼接长度：{len(full)}")
        print(f"   片段：{full[:120]}")
        print(f"   来源：{sources}")
        if not full:
            print("   [FAIL] 流式回答为空")
            return 4
    except Exception as e:
        print(f"   [ERROR] 流式问答失败：{e}")
        if "429" in str(e) or "频率" in str(e):
            print("   [提示] 命中 API 频率限制，请额度重置后重试。")
        traceback.print_exc()
        return 4

    section("结果")
    print("   [PASS] 端到端流程测试通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
