def plan_task(query):
    topic = query.strip() or "latest research"
    return [
        f"Clarify the research scope for: {topic}",
        f"Search recent and relevant academic papers about: {topic}",
        "Read papers and extract claims, methods, findings, and limitations",
        "Build a retrieval context from the most relevant paper chunks",
        "Write a structured report with evidence and references",
    ]
