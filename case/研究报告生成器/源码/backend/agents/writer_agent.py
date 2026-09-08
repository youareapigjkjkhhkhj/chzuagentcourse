from agents.llm_client import LLMNotConfiguredError, invoke_llm


def _format_references(references):
    if not references:
        return ""

    refs_md = "\n".join([
        (
            f"{index + 1}. [{paper.get('title', 'Untitled paper')}]"
            f"({paper.get('arxiv_url') or paper.get('pdf_url') or '#'}) - "
            f"{paper.get('authors', 'Unknown authors')}, "
            f"{paper.get('published', 'n.d.')}"
            f"{_source_suffix(paper)}"
        )
        for index, paper in enumerate(references)
    ])
    return f"""

## References

{refs_md}

Sources are from the selected paper search provider.
"""


def _source_suffix(paper):
    source = paper.get("source")
    return f", {source}" if source else ""


def _fallback_report(summary, topic, references=None, rag_context=""):
    evidence_section = ""
    if rag_context:
        evidence_section = f"""

## Evidence Excerpts

{rag_context[:3500]}
"""

    return f"""# {topic} Research Report

## Summary

This report was generated from retrieved paper text and local RAG evidence. No usable LLM API key was configured, so the system used an extractive fallback report. Enter an API key in the UI or configure `.env` for a more polished generated report.

## Analysis

{summary}

## Research Notes

- Compare problem definitions, methods, and evaluation settings across papers.
- Treat conclusions from a single paper cautiously unless corroborated by other sources.
- Add more data sources or citation checks for higher reliability.
{evidence_section}
{_format_references(references)}
"""


def write_report(
    summary,
    topic,
    references=None,
    rag_context="",
    language="auto",
    llm_config=None,
):
    language_hint = {
        "zh": "Write the report in Simplified Chinese.",
        "en": "Write the report in English.",
        "auto": "Use the same language as the user's topic when possible.",
    }.get(language, "Use the same language as the user's topic when possible.")

    prompt = f"""
You are a senior research writer.

Topic: {topic}

Analysis summary:
{summary}

RAG evidence:
{rag_context}

Requirements:
- {language_hint}
- Use Markdown.
- Build a polished academic report with clear headings.
- Ground claims in the supplied evidence.
- Include sections for background, key findings, methods or technical routes,
  limitations, future directions, and conclusion.
- Do not fabricate paper titles or citations.
"""
    try:
        report = invoke_llm(prompt, config=llm_config)
    except LLMNotConfiguredError:
        return _fallback_report(summary, topic, references, rag_context)

    report += _format_references(references)
    return report
