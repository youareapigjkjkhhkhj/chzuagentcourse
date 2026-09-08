from datetime import datetime, timedelta, timezone

import arxiv
import requests


class TimeoutSession(requests.Session):
    def __init__(self, timeout=20, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = timeout

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        return super().request(method, url, **kwargs)


def _build_client(max_results, trust_env=True):
    client = arxiv.Client(page_size=max_results, delay_seconds=3, num_retries=2)
    session = TimeoutSession(timeout=20)
    session.trust_env = trust_env
    client._session = session
    return client


def _build_search_query(query, years_back=0):
    cleaned = " ".join((query or "").strip().split())
    if not years_back:
        return cleaned

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * int(years_back))
    start_text = start.strftime("%Y%m%d%H%M")
    end_text = end.strftime("%Y%m%d%H%M")
    return f"({cleaned}) AND submittedDate:[{start_text} TO {end_text}]"


def _run_search(query, max_results, years_back=0, trust_env=True):
    client = _build_client(max_results, trust_env=trust_env)
    search_query = _build_search_query(query, years_back=years_back)
    search = arxiv.Search(
        query=search_query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    results = []
    for result in client.results(search):
        results.append({
            "title": result.title,
            "authors": ", ".join([author.name for author in result.authors]),
            "published": result.published.strftime("%Y-%m-%d"),
            "arxiv_url": result.entry_id,
            "pdf_url": result.pdf_url,
            "abstract": (
                result.summary[:300] + "..."
                if len(result.summary) > 300
                else result.summary
            ),
        })
    return results


def search_arxiv(query, max_results=5, years_back=0):
    errors = []

    for trust_env in (True, False):
        try:
            return _run_search(
                query,
                max_results,
                years_back=years_back,
                trust_env=trust_env,
            )
        except Exception as exc:
            mode = "system proxy/env" if trust_env else "direct/no proxy"
            message = f"arXiv search failed with {mode}: {exc}"
            print(f"[warning] {message}")
            errors.append(message)

    print("[warning] arXiv search is unavailable; continuing with fallback report.")
    return []
