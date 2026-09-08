from datetime import datetime, timedelta, timezone
import html
import re

import requests

from tools.arxiv_search import search_arxiv


PAPER_SOURCE_LABELS = {
    "arxiv": "arXiv",
    "semantic_scholar": "Semantic Scholar",
    "europe_pmc": "Europe PMC",
    "crossref": "Crossref",
    "all_open": "综合开放源",
}

DIRECT_PAPER_SOURCES = ("arxiv", "semantic_scholar", "europe_pmc", "crossref")

USER_AGENT = "multi-agent-research-assistant/2.0"


def search_papers(query, source="arxiv", max_results=5, years_back=0):
    source = source if source in PAPER_SOURCE_LABELS else "arxiv"

    if source == "all_open":
        papers = []
        for source_name in DIRECT_PAPER_SOURCES:
            papers.extend(
                search_papers(
                    query,
                    source=source_name,
                    max_results=max_results,
                    years_back=years_back,
                )
            )
        return _dedupe_papers(papers)[:max_results]

    handlers = {
        "arxiv": _search_arxiv,
        "semantic_scholar": _search_semantic_scholar,
        "europe_pmc": _search_europe_pmc,
        "crossref": _search_crossref,
    }
    return handlers[source](query, max_results=max_results, years_back=years_back)


def paper_source_label(source):
    return PAPER_SOURCE_LABELS.get(source, PAPER_SOURCE_LABELS["arxiv"])


def _search_arxiv(query, max_results=5, years_back=0):
    papers = search_arxiv(query, max_results=max_results, years_back=years_back)
    return [_with_source(paper, "arxiv") for paper in papers]


def _search_semantic_scholar(query, max_results=5, years_back=0):
    params = {
        "query": query,
        "limit": max_results,
        "fields": (
            "title,authors,year,abstract,url,openAccessPdf,"
            "publicationDate,externalIds"
        ),
    }
    if years_back:
        start, end = _date_window(years_back)
        params["year"] = f"{start.year}-{end.year}"

    data = _get_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params=params,
    )
    results = []
    for item in data.get("data", []):
        title = item.get("title") or "Untitled paper"
        authors = ", ".join(author.get("name", "") for author in item.get("authors", []))
        external_ids = item.get("externalIds") or {}
        doi = external_ids.get("DOI")
        url = item.get("url") or (f"https://doi.org/{doi}" if doi else "")
        pdf = item.get("openAccessPdf") or {}
        paper = {
            "title": title,
            "authors": authors or "Unknown authors",
            "published": str(item.get("publicationDate") or item.get("year") or "n.d."),
            "arxiv_url": url,
            "source_url": url,
            "pdf_url": pdf.get("url") or "",
            "abstract": _clean_abstract(item.get("abstract")),
            "doi": doi or "",
        }
        results.append(_with_source(paper, "semantic_scholar"))
    return results


def _search_europe_pmc(query, max_results=5, years_back=0):
    search_query = query
    if years_back:
        start, end = _date_window(years_back)
        search_query = (
            f"({query}) AND FIRST_PDATE:[{start.isoformat()} TO {end.isoformat()}]"
        )

    params = {
        "query": search_query,
        "format": "json",
        "pageSize": max_results,
        "resultType": "core",
    }
    data = _get_json(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params=params,
    )
    items = data.get("resultList", {}).get("result", [])
    results = []
    for item in items:
        url = _europe_pmc_url(item)
        paper = {
            "title": item.get("title") or "Untitled paper",
            "authors": item.get("authorString") or "Unknown authors",
            "published": (
                item.get("firstPublicationDate")
                or item.get("firstIndexDate")
                or item.get("pubYear")
                or "n.d."
            ),
            "arxiv_url": url,
            "source_url": url,
            "pdf_url": _europe_pmc_pdf_url(item),
            "abstract": _clean_abstract(item.get("abstractText")),
            "doi": item.get("doi") or "",
        }
        results.append(_with_source(paper, "europe_pmc"))
    return results


def _search_crossref(query, max_results=5, years_back=0):
    params = {
        "query.bibliographic": query,
        "rows": max_results,
        "sort": "relevance",
        "order": "desc",
    }
    if years_back:
        start, end = _date_window(years_back)
        params["filter"] = (
            f"from-pub-date:{start.isoformat()},until-pub-date:{end.isoformat()}"
        )

    data = _get_json("https://api.crossref.org/works", params=params)
    items = data.get("message", {}).get("items", [])
    results = []
    for item in items:
        doi = item.get("DOI") or ""
        url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
        paper = {
            "title": _first(item.get("title")) or "Untitled paper",
            "authors": _crossref_authors(item.get("author") or []),
            "published": _crossref_date(item),
            "arxiv_url": url,
            "source_url": url,
            "pdf_url": _crossref_pdf_url(item),
            "abstract": _clean_abstract(item.get("abstract")),
            "doi": doi,
        }
        results.append(_with_source(paper, "crossref"))
    return results


def _get_json(url, params=None):
    errors = []
    headers = {"User-Agent": USER_AGENT}

    for trust_env in (True, False):
        session = requests.Session()
        session.trust_env = trust_env
        try:
            response = session.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            mode = "system proxy/env" if trust_env else "direct/no proxy"
            errors.append(f"{url} failed with {mode}: {exc}")

    print("[warning] Paper source request failed: " + "; ".join(errors))
    return {}


def _with_source(paper, source):
    item = dict(paper)
    item["paper_source"] = source
    item["source"] = paper_source_label(source)
    item.setdefault("source_url", item.get("arxiv_url") or item.get("pdf_url") or "")
    item.setdefault("pdf_url", "")
    item.setdefault("abstract", "")
    return item


def _dedupe_papers(papers):
    seen = set()
    deduped = []
    for paper in papers:
        key = _paper_key(paper)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(paper)
    return deduped


def _paper_key(paper):
    for field in ("doi", "arxiv_url", "source_url", "title"):
        value = (paper.get(field) or "").strip().lower()
        if value:
            return value
    return ""


def _date_window(years_back):
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365 * int(years_back))
    return start, end


def _clean_abstract(text):
    cleaned = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return ""
    return cleaned[:300] + "..." if len(cleaned) > 300 else cleaned


def _first(value):
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _europe_pmc_url(item):
    if item.get("doi"):
        return f"https://doi.org/{item['doi']}"
    if item.get("pmcid"):
        return f"https://europepmc.org/article/PMC/{item['pmcid'].replace('PMC', '')}"
    source = item.get("source")
    record_id = item.get("id")
    if source and record_id:
        return f"https://europepmc.org/article/{source}/{record_id}"
    return ""


def _europe_pmc_pdf_url(item):
    urls = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
    if isinstance(urls, dict):
        urls = [urls]

    for entry in urls:
        url = entry.get("url") or ""
        style = (entry.get("documentStyle") or "").lower()
        if style == "pdf" or url.lower().endswith(".pdf"):
            return url
    return ""


def _crossref_authors(authors):
    names = []
    for author in authors[:8]:
        given = author.get("given") or ""
        family = author.get("family") or ""
        name = " ".join(part for part in (given, family) if part)
        if name:
            names.append(name)
    return ", ".join(names) if names else "Unknown authors"


def _crossref_date(item):
    for field in ("published-print", "published-online", "published", "issued"):
        parts = (item.get(field) or {}).get("date-parts") or []
        if not parts:
            continue
        values = [str(part).zfill(2) for part in parts[0] if part]
        if values:
            return "-".join(values)
    return "n.d."


def _crossref_pdf_url(item):
    for link in item.get("link") or []:
        url = link.get("URL") or ""
        content_type = (link.get("content-type") or "").lower()
        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return url
    return ""
