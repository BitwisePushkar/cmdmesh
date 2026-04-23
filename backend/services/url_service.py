import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse
from readability import Document
import re as _re
import httpx
import asyncio
import trafilatura
from backend.services.providers.huggingface import stream_hf_response

log = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=5.0, pool=5.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; cmdmesh/1.0; +https://cmdmesh.dev/bot)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}

_BINARY_TYPES = {
    "application/pdf", "application/zip", "application/octet-stream",
    "image/", "video/", "audio/",
}

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

class URLFetchError(Exception):
    pass

class URLBlockedError(URLFetchError):
    pass

async def _is_private_ip(hostname: str) -> bool:
    try:
        loop = asyncio.get_event_loop()
        addr_info = await loop.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if any(ip in net for net in _PRIVATE_NETWORKS):
                return True
        return False
    except (socket.gaierror, ValueError):
        return False

async def _validate_url(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise URLBlockedError(
            f"Only http/https URLs are supported, got: {parsed.scheme}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise URLBlockedError("URL has no hostname.")

    if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        raise URLBlockedError("Requests to localhost are not allowed.")

    if await _is_private_ip(hostname):
        raise URLBlockedError(
            "Requests to private/internal IP addresses are not allowed."
        )

    return url

def _check_content_type(content_type: str | None) -> None:
    if not content_type:
        return
    ct = content_type.lower()
    for binary in _BINARY_TYPES:
        if ct.startswith(binary):
            raise URLFetchError(
                f"Cannot extract text from content type: {content_type.split(';')[0]}"
            )

def _extract_with_trafilatura(html: str, url: str) -> tuple[str | None, str | None]:
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
        favor_precision=False,
        favor_recall=True,
    )

    metadata = trafilatura.extract_metadata(html, default_url=url)
    title = metadata.title if metadata else None

    return text, title

def _extract_with_readability(html: str) -> tuple[str | None, str | None]:
    try:
        doc = Document(html)
        title = doc.title()
        content_html = doc.summary()
        text = _re.sub(r"<[^>]+>", " ", content_html)
        text = _re.sub(r"\s+", " ", text).strip()
        return (text or None), (title or None)
    except Exception as exc:
        log.debug("readability fallback failed: %s", exc)
        return None, None

def _truncate_to_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    last_period = truncated.rfind(". ")
    if last_period > max_chars * 0.8:
        truncated = truncated[:last_period + 1]

    return truncated + f"\n\n[Content truncated at {max_chars} characters]"

def _build_context_block(
    url: str,
    title: str | None,
    text: str,
    question: str | None = None,
) -> str:
    header = f"Content from: {url}"
    if title:
        header += f"\nTitle: {title}"

    block = f"{header}\n{'=' * 50}\n\n{text}\n\n{'=' * 50}"

    if question:
        block += (
            "\n\nAnswer the user's question using the content above. "
            "If the content doesn't contain the answer, say so. "
            "Quote relevant sections when helpful."
        )

    return block

async def fetch_and_extract(
    url: str,
    max_chars: int = 8000,
) -> tuple[str, str | None, list[str]]:
    warnings: list[str] = []
    current_url = await _validate_url(url)
    log.info("Fetching URL: %s (max_chars=%d)", current_url, max_chars)

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=False, # We handle redirects manually for SSRF safety
        ) as client:
            hops = 0
            while hops < 5:
                response = await client.get(current_url)
                
                if response.is_redirect:
                    redirect_url = response.headers.get("location")
                    if not redirect_url:
                        break
                    
                    # Resolve relative URLs
                    from urllib.parse import urljoin
                    current_url = urljoin(current_url, redirect_url)
                    
                    # RE-VALIDATE every hop!
                    current_url = await _validate_url(current_url)
                    hops += 1
                    log.debug("Following redirect to: %s", current_url)
                    continue
                
                break
            
            if hops >= 5:
                raise URLFetchError("Too many redirects (>5). URL may be in a redirect loop.")

    except httpx.TimeoutException as exc:
        raise URLFetchError(
            f"Request timed out. The server at {urlparse(current_url).hostname} is too slow."
        ) from exc
    except httpx.ConnectError as exc:
        raise URLFetchError(
            f"Could not connect to {urlparse(current_url).hostname}. "
            "Check the URL is correct and the site is reachable."
        ) from exc
    except httpx.InvalidURL as exc:
        raise URLFetchError(f"Invalid URL: {exc}") from exc
    except URLBlockedError:
        raise
    except Exception as exc:
        log.error("Unexpected fetch error for %s: %s", current_url, exc)
        raise URLFetchError(f"Unexpected error: {exc}") from exc

    if response.status_code == 404:
        raise URLFetchError(f"Page not found (404): {current_url}")
    if response.status_code == 403:
        raise URLFetchError(
            f"Access denied (403). The site is blocking automated requests."
        )
    if response.status_code == 429:
        raise URLFetchError("Rate limited by the target server (429). Try again later.")
    if response.status_code >= 400:
        raise URLFetchError(
            f"Server returned HTTP {response.status_code} for {current_url}"
        )

    content_type = response.headers.get("content-type", "")
    _check_content_type(content_type)

    try:
        html = response.text
    except Exception as exc:
        raise URLFetchError(f"Could not decode page content: {exc}") from exc

    if not html.strip():
        raise URLFetchError("The page returned an empty body.")
    
    # Run heavy extraction in thread pools to avoid blocking the event loop
    text, title = await asyncio.to_thread(_extract_with_trafilatura, html, current_url)

    if not text or len(text.strip()) < 100:
        warnings.append("Primary extractor returned little content — using fallback.")
        fallback_text, fallback_title = await asyncio.to_thread(_extract_with_readability, html)

        if fallback_text and len(fallback_text.strip()) > len(text or ""):
            text = fallback_text
            if not title:
                title = fallback_title
        elif not text:
            raise URLFetchError(
                "Could not extract readable text from the page. "
                "The page may be JavaScript-rendered or require login."
            )

    text = text.strip()
    original_len = len(text)
    text = _truncate_to_chars(text, max_chars)

    if original_len > max_chars:
        warnings.append(
            f"Content truncated from {original_len:,} to {max_chars:,} characters."
        )

    log.info(
        "Extracted %d chars from %s (title=%r, warnings=%d)",
        len(text), current_url, title, len(warnings)
    )
    return text, title, warnings

async def fetch_with_ai_answer(
    *,
    url: str,
    ai_question: str,
    hf_token: str,
    model_id: str,
    max_chars: int = 8000,
) -> tuple[str, str | None, str, list[str]]:
    text, title, warnings = await fetch_and_extract(url, max_chars=max_chars)
    context_block = _build_context_block(url, title, text, question=ai_question)

    messages = [
        {"role": "system", "content": context_block},
        {"role": "user",   "content": ai_question},
    ]

    chunks: list[str] = []
    async for chunk in stream_hf_response(
        hf_token=hf_token,
        model_id=model_id,
        messages=messages,
    ):
        chunks.append(chunk)

    return text, title, "".join(chunks), warnings

def build_url_context_message(
    url: str,
    title: str | None,
    text: str,
) -> dict:
    return {
        "role": "system",
        "content": _build_context_block(url, title, text),
    }