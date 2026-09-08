from vectorstore.faiss_store import ResearchVectorStore


def chunk_papers(contents, chunk_size=1200, overlap=180):
    chunks = []
    for paper_index, paper in enumerate(contents):
        text = " ".join((paper.get("text") or "").split())
        if not text:
            continue

        metadata_text = " ".join([
            paper.get("title", ""),
            paper.get("title", ""),
            paper.get("abstract", ""),
            paper.get("search_query", ""),
            paper.get("source", ""),
        ])
        start = 0
        chunk_index = 0
        while start < len(text):
            chunk_text = text[start:start + chunk_size]
            chunks.append({
                "id": f"paper-{paper_index}-chunk-{chunk_index}",
                "paper_index": paper_index,
                "chunk_index": chunk_index,
                "title": paper.get("title", "Untitled paper"),
                "authors": paper.get("authors", ""),
                "published": paper.get("published", ""),
                "arxiv_url": paper.get("arxiv_url", ""),
                "pdf_url": paper.get("pdf_url", ""),
                "text": chunk_text,
                "retrieval_text": f"{metadata_text} {chunk_text}",
            })
            chunk_index += 1
            start += max(chunk_size - overlap, 1)
    return chunks


def build_rag_context(topic, contents, top_k=8):
    chunks = chunk_papers(contents)
    store = ResearchVectorStore()
    store.add_documents(chunks)

    query = _build_query(topic, contents)
    matches = store.search(query, top_k=top_k)

    context_blocks = []
    for index, match in enumerate(matches, start=1):
        context_blocks.append(
            "\n".join([
                f"[Evidence {index}] {match.get('title', 'Untitled paper')}",
                (
                    f"Relevance: {match.get('relevance', '可参考')} "
                    f"({match.get('score', 0):.0%})"
                ),
                f"Source: {match.get('arxiv_url', '')}",
                match.get("text", ""),
            ])
        )

    return "\n\n".join(context_blocks), matches


def _build_query(topic, contents):
    terms = [
        topic,
        "key findings methods datasets experiments limitations applications future work",
    ]
    search_query = next(
        (
            paper.get("search_query", "")
            for paper in contents
            if paper.get("search_query")
        ),
        "",
    )
    terms.append(search_query)

    deduped = []
    for term in terms:
        cleaned = " ".join((term or "").split())
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return " ".join(deduped)
