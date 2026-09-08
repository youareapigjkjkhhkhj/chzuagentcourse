"""本地单元测试：规划代理 / 本地混合 RAG / 兜底分析与写作（不依赖网络与 LLM）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.planner_agent import plan_task
from agents.rag_agent import build_rag_context
from agents.analyst_agent import _fallback_analyze
from agents.writer_agent import _fallback_report
from vectorstore.embeddings import tokenize_for_retrieval

PASS = 0


def check(name, condition, detail=""):
    global PASS
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name} {detail}")
    if condition:
        PASS += 1
    else:
        raise SystemExit(f"单元测试失败: {name}")


# 1) 规划代理
tasks = plan_task("量子计算")
check("planner 生成 5 步任务", len(tasks) == 5, f"n={len(tasks)}")
check("planner 首步包含主题", "量子计算" in tasks[0])

# 2) 分词（英文 token + 中文 bigram）
tokens = tokenize_for_retrieval("Large Language Model 大语言模型")
check("分词包含英文 token", "large" in tokens)
check("分词包含中文 bigram", "大语" in tokens or "语言" in tokens)

# 3) 本地混合 RAG（构造 2 份假论文文本，不调任何 API）
t1 = time.time()
contents = [
    {
        "title": "Graph Neural Networks for Recommendation",
        "authors": "A, B",
        "published": "2024-01-01",
        "arxiv_url": "https://arxiv.org/abs/0000.00001",
        "pdf_url": "",
        "abstract": "We study graph neural networks for recommender systems.",
        "search_query": "graph neural networks recommendation",
        "text": ("Graph neural networks propagate messages over user-item graphs. "
                 "They improve collaborative filtering for recommender systems. "
                 "Experiments show gains in ranking accuracy and cold-start handling."),
    },
    {
        "title": "Medical Image Segmentation with Deep Learning",
        "authors": "C, D",
        "published": "2024-02-01",
        "arxiv_url": "https://arxiv.org/abs/0000.00002",
        "pdf_url": "",
        "abstract": "Deep learning for medical image segmentation.",
        "search_query": "medical image segmentation",
        "text": ("Convolutional networks segment CT and MRI scans for clinical use. "
                 "Dice scores improve with data augmentation and attention modules."),
    },
]
rag_context, evidence = build_rag_context("graph neural networks for recommendation", contents, top_k=3)
check("RAG 构建上下文非空", len(rag_context) > 0, f"len={len(rag_context)}")
check("RAG 返回证据列表", isinstance(evidence, list) and len(evidence) > 0, f"n={len(evidence)}")
check("RAG 证据含 title 与分数", evidence[0].get("title") and evidence[0].get("score") is not None,
      f"top={evidence[0].get('title')} score={evidence[0].get('score'):.2f}")
check("RAG 证据含相关度标签", evidence[0].get("relevance") in {"高度相关", "较相关", "可参考", "弱相关"})
print(f"      RAG 构建耗时 {time.time() - t1:.2f}s")

# 4) 兜底分析（无 LLM 时）
summary = _fallback_analyze(contents, topic="graph neural networks", rag_context=rag_context)
check("兜底分析非空", len(summary) > 50, f"len={len(summary)}")

# 5) 兜底报告
report = _fallback_report(summary, "graph neural networks", references=contents, rag_context=rag_context)
check("兜底报告含标题", report.startswith("# "))
check("兜底报告含 References", "## References" in report)
check("兜底报告含引用条目", "[Graph Neural Networks for Recommendation]" in report)

print(f"\n单元测试全部通过: {PASS} 项")
