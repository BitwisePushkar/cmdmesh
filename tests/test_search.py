import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient
from backend.services.search_service import search, _sanitise_query, SearchError, _results_to_context_block, _clean_snippet
from duckduckgo_search.exceptions import RatelimitException
from duckduckgo_search.exceptions import DuckDuckGoSearchException
from backend.schemas.search import SearchResult
from backend.services.url_service import fetch_and_extract, URLFetchError, URLBlockedError, _build_context_block, _validate_url
import httpx

@pytest.fixture
def auth_headers(auth_tokens):
    return {"Authorization": f"Bearer {auth_tokens['access_token']}"}

HF_HEADERS = {
    "X-HF-Token": "hf_test_token",
    "X-HF-Model-Id": "mistralai/Mistral-7B-Instruct-v0.3",
}

FAKE_DDG_RESULTS = [
    {
        "title": "FastAPI documentation",
        "href": "https://fastapi.tiangolo.com",
        "body": "FastAPI is a modern, fast web framework for building APIs with Python.",
    },
    {
        "title": "FastAPI GitHub",
        "href": "https://github.com/tiangolo/fastapi",
        "body": "FastAPI on GitHub — star the repo.",
    },
]

FAKE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
  <article>
    <h1>Hello World</h1>
    <p>This is the main content of the page. It has useful information.</p>
    <p>More content here with details about the topic.</p>
  </article>
  <nav>Navigation that should be stripped</nav>
  <footer>Footer that should be stripped</footer>
</body>
</html>
"""

def _mock_ddg(results=None):
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text = MagicMock(return_value=results or FAKE_DDG_RESULTS)
    return mock_ddgs

def _mock_hf_stream(*chunks: str):
    async def _gen(**kwargs):
        for chunk in chunks:
            yield chunk
    return _gen

@pytest.mark.asyncio
async def test_search_service_returns_results():
    with patch("backend.services.search_service._do_search_sync", return_value=FAKE_DDG_RESULTS):
        results = await search("FastAPI", max_results=5)
    assert len(results) == 2
    assert results[0].title == "FastAPI documentation"
    assert results[0].url == "https://fastapi.tiangolo.com"
    assert results[0].position == 1
    assert "FastAPI" in results[0].snippet

@pytest.mark.asyncio
async def test_search_service_empty_results():
    with patch("backend.services.search_service._do_search_sync", return_value=[]):
        results = await search("xkcd_nonexistent_query_abc123", max_results=5)
    assert results == []

@pytest.mark.asyncio
async def test_search_service_sanitises_query():
    sanitised = _sanitise_query("hello <script>alert(1)</script> world")
    assert "<script>" not in sanitised
    assert "hello" in sanitised
    empty = _sanitise_query("<<>>&&||")
    assert empty.strip() == "" or len(empty.strip()) < 3

@pytest.mark.asyncio
async def test_search_service_blank_query_raises():
    with pytest.raises(SearchError, match="empty"):
        await search("   ")

@pytest.mark.asyncio
async def test_search_service_rate_limit_retries():
    mock_ddgs = _mock_ddg()
    mock_ddgs.text = MagicMock(side_effect=RatelimitException("rate limited"))
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)

    with patch("backend.services.search_service._do_search_sync", side_effect=RatelimitException("rate limited")), \
         patch("backend.services.search_service.asyncio.sleep"):
        with pytest.raises(SearchError, match="rate-limited"):
            await search("test query")

@pytest.mark.asyncio
async def test_search_service_ddg_exception_raises_search_error():
    mock_ddgs = _mock_ddg()
    mock_ddgs.text = MagicMock(side_effect=DuckDuckGoSearchException("network error"))
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)

    with patch("backend.services.search_service._do_search_sync", side_effect=DuckDuckGoSearchException("network error")):
        with pytest.raises(SearchError):
            await search("test")

@pytest.mark.asyncio
async def test_search_service_skips_results_without_url():
    results_with_missing_url = [
        {"title": "Good result", "href": "https://example.com", "body": "content"},
        {"title": "Bad result", "href": "", "body": "no url"},
        {"title": "Also bad", "href": None, "body": "also no url"},
    ]
    with patch("backend.services.search_service._do_search_sync", return_value=results_with_missing_url):
        results = await search("test")

    assert len(results) == 1
    assert results[0].title == "Good result"

def test_results_to_context_block_format():
    results = [
        SearchResult(title="Page A", url="https://a.com", snippet="About A", position=1),
        SearchResult(title="Page B", url="https://b.com", snippet="About B", position=2),
    ]
    block = _results_to_context_block("test query", results)

    assert "test query" in block
    assert "Page A" in block
    assert "https://a.com" in block
    assert "[1]" in block
    assert "[2]" in block
    assert "Cite the source" in block

def test_results_to_context_block_empty():
    block = _results_to_context_block("nothing", [])
    assert "no results" in block.lower()

def test_snippet_truncated_at_limit():
    long_text = "word " * 200
    result = _clean_snippet(long_text)
    assert len(result) <= 305 
    assert result.endswith("…")

@pytest.mark.asyncio
async def test_url_service_fetches_and_extracts():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html; charset=utf-8"}
    mock_response.text = FAKE_HTML

    with patch("backend.services.url_service.httpx.AsyncClient") as mock_client_class, \
         patch("backend.services.url_service.trafilatura.extract",
               return_value="Hello World\n\nThis is the main content of the page."), \
         patch("backend.services.url_service.trafilatura.extract_metadata") as mock_meta:

        mock_meta.return_value = MagicMock(title="Test Page")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        text, title, warnings = await fetch_and_extract("https://example.com")

    assert "Hello World" in text
    assert title == "Test Page"
    assert isinstance(warnings, list)

@pytest.mark.asyncio
async def test_url_service_404_raises():
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = "Not found"

    with patch("backend.services.url_service.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        with pytest.raises(URLFetchError, match="404"):
            await fetch_and_extract("https://example.com/not-found")

@pytest.mark.asyncio
async def test_url_service_403_raises():
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.headers = {"content-type": "text/html"}

    with patch("backend.services.url_service.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        with pytest.raises(URLFetchError, match="403"):
            await fetch_and_extract("https://example.com/private")

@pytest.mark.asyncio
async def test_url_service_blocks_private_ip():
    with patch("backend.services.url_service._is_private_ip", return_value=True):
        with pytest.raises(URLBlockedError, match="private"):
            await fetch_and_extract("http://192.168.1.1/admin")

@pytest.mark.asyncio
async def test_url_service_blocks_localhost():
    with pytest.raises(URLBlockedError):
        await fetch_and_extract("http://localhost:8000/internal")

@pytest.mark.asyncio
async def test_url_service_blocks_non_http_scheme():
    with pytest.raises(URLBlockedError, match="http/https"):
        await fetch_and_extract("ftp://example.com/file")

@pytest.mark.asyncio
async def test_url_service_blocks_binary_content_type():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/pdf"}

    with patch("backend.services.url_service.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        with pytest.raises(URLFetchError, match="application/pdf"):
            await fetch_and_extract("https://example.com/doc.pdf")

@pytest.mark.asyncio
async def test_url_service_timeout_raises():
    with patch("backend.services.url_service.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client_class.return_value = mock_client

        with pytest.raises(URLFetchError, match="timed out"):
            await fetch_and_extract("https://slow.example.com")

@pytest.mark.asyncio
async def test_url_service_truncates_large_content():
    long_text = "word " * 10000 

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = "<html><body>" + long_text + "</body></html>"

    with patch("backend.services.url_service.httpx.AsyncClient") as mock_client_class, \
         patch("backend.services.url_service.trafilatura.extract", return_value=long_text), \
         patch("backend.services.url_service.trafilatura.extract_metadata",
               return_value=MagicMock(title="Long page")):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        text, title, warnings = await fetch_and_extract(
            "https://example.com", max_chars=1000
        )

    assert len(text) <= 1050  
    assert "truncated" in text.lower()
    assert any("truncated" in w.lower() for w in warnings)

@pytest.mark.asyncio
async def test_url_service_falls_back_to_readability():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_response.text = FAKE_HTML

    with patch("backend.services.url_service.httpx.AsyncClient") as mock_client_class, \
         patch("backend.services.url_service.trafilatura.extract", return_value=None), \
         patch("backend.services.url_service.trafilatura.extract_metadata",
               return_value=MagicMock(title=None)), \
         patch("backend.services.url_service._extract_with_readability",
               return_value=("Fallback content from readability", "Fallback Title")):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        text, title, warnings = await fetch_and_extract("https://example.com")

    assert "Fallback content" in text
    assert title == "Fallback Title"
    assert any("fallback" in w.lower() for w in warnings)

@pytest.mark.asyncio
async def test_validate_url_adds_https():
    with patch("backend.services.url_service._is_private_ip", return_value=False):
        url = await _validate_url("https://example.com/page")
        assert url == "https://example.com/page"

@pytest.mark.asyncio
async def test_validate_url_rejects_ftp():
    with pytest.raises(URLBlockedError, match="http/https"):
        await _validate_url("ftp://example.com")

def test_build_context_block_format():
    block = _build_context_block(
        "https://example.com",
        "Test Article",
        "This is the page content.",
        question="What is this about?",
    )
    assert "https://example.com" in block
    assert "Test Article" in block
    assert "This is the page content." in block
    assert "Answer the user" in block

@pytest.mark.asyncio
async def test_search_query_requires_auth(client: AsyncClient):
    r = await client.post("/search/query", json={"query": "test"})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_url_endpoint_requires_auth(client: AsyncClient):
    r = await client.post("/search/url", json={"url": "https://example.com"})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_inject_search_requires_auth(client: AsyncClient):
    r = await client.post("/search/inject-search",
                          json={"query": "test", "session_id": str(uuid.uuid4())})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_inject_url_requires_auth(client: AsyncClient):
    r = await client.post("/search/inject-url",
                          json={"url": "https://example.com",
                                "session_id": str(uuid.uuid4())})
    assert r.status_code == 401

@pytest.mark.asyncio
async def test_search_query_plain_no_hf_token_needed(
    client: AsyncClient, auth_headers
):
    with patch("backend.services.search_service.DDGS", return_value=_mock_ddg()):
        r = await client.post(
            "/search/query",
            json={"query": "FastAPI tutorial", "max_results": 3},
            headers=auth_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "FastAPI tutorial"
    assert len(body["results"]) == 2
    assert body["ai_answer"] is None

@pytest.mark.asyncio
async def test_search_query_returns_correct_fields(
    client: AsyncClient, auth_headers
):
    with patch("backend.services.search_service.DDGS", return_value=_mock_ddg()):
        r = await client.post(
            "/search/query",
            json={"query": "Python"},
            headers=auth_headers,
        )
    body = r.json()
    result = body["results"][0]
    assert "title" in result
    assert "url" in result
    assert "snippet" in result
    assert "position" in result
    assert result["position"] == 1

@pytest.mark.asyncio
async def test_search_query_blank_query_rejected(
    client: AsyncClient, auth_headers
):
    r = await client.post(
        "/search/query",
        json={"query": "   "},
        headers=auth_headers,
    )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_search_query_with_ai_requires_hf_token(
    client: AsyncClient, auth_headers
):
    r = await client.post(
        "/search/query",
        json={"query": "Python", "ai_question": "What is Python?"},
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert "X-HF-Token" in r.json()["detail"]

@pytest.mark.asyncio
async def test_search_query_with_ai_requires_model_id(
    client: AsyncClient, auth_headers
):
    r = await client.post(
        "/search/query",
        json={"query": "Python", "ai_question": "What is Python?"},
        headers={**auth_headers, "X-HF-Token": "hf_test"},
    )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_search_query_with_ai_streams_answer(
    client: AsyncClient, auth_headers
):
    with patch("backend.services.search_service.DDGS", return_value=_mock_ddg()), \
         patch("backend.services.providers.huggingface.stream_hf_response",
               side_effect=_mock_hf_stream("Python is a language.")):
        r = await client.post(
            "/search/query",
            json={"query": "Python", "ai_question": "What is Python?"},
            headers={**auth_headers, **HF_HEADERS},
        )
    assert r.status_code == 200
    assert r.json()["ai_answer"] == "Python is a language."

@pytest.mark.asyncio
async def test_search_stream_endpoint_yields_results_then_chunks(
    client: AsyncClient, auth_headers
):
    with patch("backend.services.search_service.DDGS", return_value=_mock_ddg()), \
         patch("backend.services.providers.huggingface.stream_hf_response",
               side_effect=_mock_hf_stream("Answer here")):
        r = await client.post(
            "/search/query/stream",
            json={"query": "test", "ai_question": "What?"},
            headers={**auth_headers, **HF_HEADERS},
        )

    assert r.status_code == 200
    lines = [json.loads(l) for l in r.text.strip().split("\n") if l]

    assert lines[0]["type"] == "results"
    assert len(lines[0]["data"]) > 0

    chunks = [l for l in lines if l["type"] == "chunk"]
    assert len(chunks) > 0
    assert "".join(c["chunk"] for c in chunks) == "Answer here"
    assert lines[-1]["type"] == "done"

@pytest.mark.asyncio
async def test_search_ddg_error_returns_503(
    client: AsyncClient, auth_headers
):
    with patch("backend.routes.search.search",
               side_effect=SearchError("DDG is down")):
        r = await client.post(
            "/search/query",
            json={"query": "test"},
            headers=auth_headers,
        )
    assert r.status_code == 503
    assert "DDG is down" in r.json()["detail"]

@pytest.mark.asyncio
async def test_url_endpoint_plain_extraction(client: AsyncClient, auth_headers):
    with patch("backend.routes.search.fetch_and_extract",
               return_value=("Extracted text here", "Page Title", [])):
        r = await client.post(
            "/search/url",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["extracted_text"] == "Extracted text here"
    assert body["title"] == "Page Title"
    assert body["char_count"] == len("Extracted text here")
    assert body["ai_answer"] is None

@pytest.mark.asyncio
async def test_url_endpoint_with_ai_requires_hf_token(
    client: AsyncClient, auth_headers
):
    r = await client.post(
        "/search/url",
        json={"url": "https://example.com", "ai_question": "summarise"},
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert "X-HF-Token" in r.json()["detail"]

@pytest.mark.asyncio
async def test_url_endpoint_with_ai_answer(client: AsyncClient, auth_headers):
    with patch("backend.routes.search.fetch_with_ai_answer",
               return_value=("Page text", "Title", "AI summary here", [])):
        r = await client.post(
            "/search/url",
            json={"url": "https://example.com", "ai_question": "summarise"},
            headers={**auth_headers, **HF_HEADERS},
        )
    assert r.status_code == 200
    assert r.json()["ai_answer"] == "AI summary here"

@pytest.mark.asyncio
async def test_url_endpoint_blocked_url_returns_400(
    client: AsyncClient, auth_headers
):
    with patch("backend.routes.search.fetch_and_extract",
               side_effect=URLBlockedError("private IP blocked")):
        r = await client.post(
            "/search/url",
            json={"url": "http://192.168.1.1"},
            headers=auth_headers,
        )
    assert r.status_code == 400
    assert "private" in r.json()["detail"].lower()

@pytest.mark.asyncio
async def test_url_endpoint_fetch_error_returns_422(
    client: AsyncClient, auth_headers
):
    with patch("backend.routes.search.fetch_and_extract",
               side_effect=URLFetchError("404 not found")):
        r = await client.post(
            "/search/url",
            json={"url": "https://example.com/gone"},
            headers=auth_headers,
        )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_url_stream_endpoint_yields_meta_then_chunks(
    client: AsyncClient, auth_headers
):
    with patch("backend.routes.search.fetch_and_extract",
               return_value=("Article content", "Article Title", [])), \
         patch("backend.services.providers.huggingface.stream_hf_response",
               side_effect=_mock_hf_stream("Summary chunk")):
        r = await client.post(
            "/search/url/stream",
            json={"url": "https://example.com", "ai_question": "summarise"},
            headers={**auth_headers, **HF_HEADERS},
        )

    assert r.status_code == 200
    lines = [json.loads(l) for l in r.text.strip().split("\n") if l]

    assert lines[0]["type"] == "meta"
    assert lines[0]["title"] == "Article Title"
    assert lines[0]["char_count"] == len("Article content")

    chunks = [l for l in lines if l["type"] == "chunk"]
    assert "".join(c["chunk"] for c in chunks) == "Summary chunk"

    assert lines[-1]["type"] == "done"

@pytest.mark.asyncio
async def test_inject_search_into_session(
    client: AsyncClient, auth_headers, auth_tokens
):
    r = await client.post("/chat/sessions", json={
        "model_id": "mistralai/Mistral-7B-Instruct-v0.3",
        "title": "Test for injection",
    }, headers=auth_headers)
    assert r.status_code == 201
    session_id = r.json()["id"]

    with patch("backend.services.search_service.DDGS", return_value=_mock_ddg()):
        r = await client.post(
            "/search/inject-search",
            json={"query": "FastAPI", "session_id": session_id},
            headers=auth_headers,
        )

    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id
    assert body["context_chars"] > 0
    assert "FastAPI" in body["message"]

@pytest.mark.asyncio
async def test_inject_search_session_not_found(
    client: AsyncClient, auth_headers
):
    with patch("backend.services.search_service.DDGS", return_value=_mock_ddg()):
        r = await client.post(
            "/search/inject-search",
            json={"query": "test", "session_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_inject_search_requires_session_id(
    client: AsyncClient, auth_headers
):
    r = await client.post(
        "/search/inject-search",
        json={"query": "test"},
        headers=auth_headers,
    )
    assert r.status_code == 422

@pytest.mark.asyncio
async def test_inject_url_into_session(
    client: AsyncClient, auth_headers
):
    r = await client.post("/chat/sessions", json={
        "model_id": "mistralai/Mistral-7B-Instruct-v0.3",
    }, headers=auth_headers)
    session_id = r.json()["id"]

    with patch("backend.routes.search.fetch_and_extract",
               return_value=("Page content injected", "Injected Page", [])):
        r = await client.post(
            "/search/inject-url",
            json={"url": "https://example.com", "session_id": session_id},
            headers=auth_headers,
        )

    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == session_id
    assert body["context_chars"] > 0

@pytest.mark.asyncio
async def test_inject_url_session_not_found(client: AsyncClient, auth_headers):
    with patch("backend.routes.search.fetch_and_extract",
               return_value=("content", "title", [])):
        r = await client.post(
            "/search/inject-url",
            json={"url": "https://example.com", "session_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_inject_url_invalid_session_id_format(client: AsyncClient, auth_headers):
    with patch("backend.routes.search.fetch_and_extract",
               return_value=("content", "title", [])):
        r = await client.post(
            "/search/inject-url",
            json={"url": "https://example.com", "session_id": "not-a-uuid"},
            headers=auth_headers,
        )
    assert r.status_code == 422