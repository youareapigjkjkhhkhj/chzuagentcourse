from agents.llm_client import LLMNotConfiguredError, invoke_llm


def _fallback_analyze(contents, topic="", rag_context=""):
    if not contents:
        return (
            "No readable paper content was retrieved. The report should explain "
            "the search gap and rely on available metadata only."
        )

    snippets = []
    for item in contents[:5]:
        text = " ".join((item.get("text") or "").split())[:900]
        snippets.append(f"- {item.get('title', 'Untitled paper')}: {text}")

    evidence = rag_context[:2500] if rag_context else "\n".join(snippets)
    return (
        f"Topic: {topic}\n\n"
        "Extractive summary from retrieved papers:\n"
        f"{evidence}\n\n"
        "Common analysis angles: problem setting, methods, empirical findings, "
        "limitations, open questions, and practical implications."
    )


def analyze(contents, topic="", rag_context="", llm_config=None):
    prompt = f"""
You are an academic research analyst.

Topic: {topic}

Retrieved evidence:
{rag_context}

Paper contents:
{contents}

Summarize the key ideas, methods, findings, disagreements, limitations, and
research opportunities. Keep the answer grounded in the retrieved evidence.
"""
    try:
        return invoke_llm(prompt, config=llm_config)
    except LLMNotConfiguredError:
        return _fallback_analyze(contents, topic=topic, rag_context=rag_context)
