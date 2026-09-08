import re

from agents.llm_client import invoke_llm
from tools.paper_sources import search_papers


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_COMMON_TRANSLATIONS = {
    "边缘计算": "edge computing",
    "集成电路": "integrated circuit semiconductor chip design",
    "量子计算": "quantum computing",
    "人工智能": "artificial intelligence",
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "大语言模型": "large language model",
    "自然语言处理": "natural language processing",
    "计算机视觉": "computer vision",
    "物联网": "internet of things",
    "区块链": "blockchain",
    "联邦学习": "federated learning",
    "强化学习": "reinforcement learning",
    "知识图谱": "knowledge graph",
    "自动驾驶": "autonomous driving",
    "智能制造": "smart manufacturing",
    "数字孪生": "digital twin",
    "网络安全": "cybersecurity",
    "推荐系统": "recommender systems",
    "图神经网络": "graph neural networks",
    "半导体": "semiconductor",
    "芯片": "chip semiconductor integrated circuit",
}


def search_agent(
    tasks,
    topic=None,
    max_results=5,
    years_back=0,
    paper_source="arxiv",
    llm_config=None,
):
    query = _base_query(tasks, topic=topic)
    queries = _query_variants(query, llm_config=llm_config)

    for candidate in queries:
        papers = search_papers(
            candidate,
            source=paper_source,
            max_results=max_results,
            years_back=years_back,
        )
        if papers:
            for paper in papers:
                paper["search_query"] = candidate
            return papers

    return []


def _base_query(tasks, topic=None):
    if topic:
        return topic.strip()
    if isinstance(tasks, list):
        return " ".join(tasks) if tasks else "latest research"
    return str(tasks)


def _query_variants(query, llm_config=None):
    variants = []

    if _has_cjk(query):
        translated = _translate_query(query, llm_config=llm_config)
        if translated:
            variants.append(translated)

        fallback = _dictionary_translate(query)
        if fallback:
            variants.append(fallback)

    variants.append(query)
    variants.append(_ascii_only(query))

    deduped = []
    for item in variants:
        cleaned = " ".join((item or "").strip().split())
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _has_cjk(text):
    return bool(_CJK_RE.search(text or ""))


def _translate_query(query, llm_config=None):
    if not llm_config:
        return ""

    prompt = f"""
Translate this academic research topic into a concise English academic paper search query.
Return only the query text, without quotes or explanation.

Topic: {query}
"""
    try:
        translated = invoke_llm(prompt, config=llm_config)
    except Exception as exc:
        print(f"[警告] LLM query translation failed: {exc}")
        return ""

    translated = translated.strip().strip('"').strip("'")
    return translated[:160]


def _dictionary_translate(query):
    matches = [
        english
        for chinese, english in _COMMON_TRANSLATIONS.items()
        if chinese in query
    ]
    if matches:
        return " ".join(matches)
    return ""


def _ascii_only(query):
    return " ".join(re.findall(r"[A-Za-z][A-Za-z0-9_+\-]{1,}", query or ""))
