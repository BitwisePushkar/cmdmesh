import logging
import re
import asyncio
from dataclasses import dataclass
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException
from backend.schemas.search import SearchResult
from backend.services.providers.huggingface import stream_hf_response

log = logging.getLogger(__name__)

_SNIPPET_MAX = 300
_RETRY_SLEEP = 2.0
_QUERY_STRIP_PATTERN = re.compile(r"[^\w\s\-\.\,\?\!\'\"\:\(\)\/\@\#\$\%\&\*\+]", re.UNICODE)

class SearchError(Exception):
    pass

def _sanitise_query(query: str) -> str:
    q = _QUERY_STRIP_PATTERN.sub(" ", query)
    q = re.sub(r"\s+", " ", q).strip()
    return q[:300]

def _clean_snippet(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if len(text) > _SNIPPET_MAX:
        text = text[:_SNIPPET_MAX].rsplit(" ", 1)[0] + "…"
    return text

def _results_to_context_block(
    query: str, results: list[SearchResult]
) -> str:
    if not results:
        return f"[Search for '{query}' returned no results.]"

    lines = [
        f"Web search results for: {query}",
        "=" * 50,
    ]
    for r in results:
        lines.append(f"\n[{r.position}] {r.title}")
        lines.append(f"    URL: {r.url}")
        if r.snippet:
            lines.append(f"    {r.snippet}")
    lines.append("\n" + "=" * 50)
    lines.append(
        "Answer the user's question using the search results above. "
        "Cite the source number [N] when referencing specific information. "
        "If the results don't answer the question, say so."
    )
    return "\n".join(lines)

def _do_search_sync(query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(
            query,
            max_results=max_results,
            safesearch="moderate",
        ))

async def search(
    query: str,
    max_results: int = 5,
) -> list[SearchResult]:
    clean_query = _sanitise_query(query)
    if not clean_query:
        raise SearchError("Query is empty after sanitisation.")

    log.info("Searching DDG: %r (max=%d)", clean_query, max_results)

    try:
        raw = await asyncio.to_thread(_do_search_sync, clean_query, max_results)
    except RatelimitException:
        log.warning("DDG rate limit hit — retrying after %.1fs", _RETRY_SLEEP)
        await asyncio.sleep(_RETRY_SLEEP)
        try:
            raw = await asyncio.to_thread(_do_search_sync, clean_query, max_results)
        except (RatelimitException, DDGSException) as exc:
            raise SearchError(
                "Search is temporarily rate-limited. Please wait a moment and try again."
            ) from exc
    except DDGSException as exc:
        raise SearchError(f"Search failed: {exc}") from exc
    except Exception as exc:
        log.error("Unexpected search error: %s", exc)
        raise SearchError(f"Unexpected search error: {exc}") from exc

    results: list[SearchResult] = []
    for i, item in enumerate(raw or [], start=1):
        title = (item.get("title") or "").strip() or "Untitled"
        url = (item.get("href") or item.get("url") or "").strip()
        snippet = _clean_snippet(item.get("body") or item.get("snippet") or "")

        if not url:
            continue 

        results.append(SearchResult(
            title=title,
            url=url,
            snippet=snippet,
            position=i,
        ))

    if not results:
        log.warning("DuckDuckGo returned NO results for query: %r (sanitised: %r)", query, clean_query)
    else:
        log.info("DDG returned %d results for %r", len(results), clean_query)
        
    return results

async def search_with_ai_answer(
    *,
    query: str,
    ai_question: str,
    hf_token: str,
    model_id: str,
    max_results: int = 5,
) -> tuple[list[SearchResult], str]:

    results = await search(query, max_results=max_results)
    context_block = _results_to_context_block(query, results)

    messages = [
        {"role": "system",  "content": context_block},
        {"role": "user",    "content": ai_question},
    ]

    chunks: list[str] = []
    async for chunk in stream_hf_response(
        hf_token=hf_token,
        model_id=model_id,
        messages=messages,
    ):
        chunks.append(chunk)

    return results, "".join(chunks)

def build_search_context_message(
    query: str, results: list[SearchResult]
) -> dict:
    return {
        "role": "system",
        "content": _results_to_context_block(query, results),
    }