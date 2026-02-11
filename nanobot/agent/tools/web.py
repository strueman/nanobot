"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


class WebSearchTool(Tool):
    """Search the web using configured provider."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 5,
        config: "WebSearchConfig | None" = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        from nanobot.config.schema import WebSearchConfig

        self.config = config or WebSearchConfig(api_key=api_key or "", max_results=max_results)
        if api_key is not None:
            self.config.api_key = api_key
        if max_results != 5:
            self.config.max_results = max_results
        self._transport = transport
        self._provider_searchers: dict[str, Callable[[str, int], Awaitable[str]]] = {
            "duckduckgo": self._search_duckduckgo,
            "tavily": self._execute_tavily_provider,
            "searxng": self._search_searxng,
            "brave": self._execute_brave_provider,
        }

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        provider = (self.config.provider or "brave").strip().lower()
        n = min(max(count or self.config.max_results, 1), 10)

        search = self._provider_searchers.get(provider, self._provider_searchers["brave"])
        return await search(query, n)

    async def _execute_brave_provider(self, query: str, n: int) -> str:
        brave_key = self._brave_api_key()
        if not brave_key and self.config.fallback_to_duckduckgo_on_missing_key:
            return await self._fallback_to_duckduckgo('BRAVE_API_KEY', query, n)
        return await self._search_brave(query=query, n=n)

    async def _execute_tavily_provider(self, query: str, n: int) -> str:
        tavily_key = self._tavily_api_key()
        if not tavily_key and self.config.fallback_to_duckduckgo_on_missing_key:
            return await self._fallback_to_duckduckgo('TAVILY_API_KEY', query, n)
        return await self._search_tavily(query=query, n=n)

    async def _fallback_to_duckduckgo(self, missing_key: str, query: str, n: int) -> str:
        ddg = await self._search_duckduckgo(query=query, n=n)
        if ddg.startswith('Error:'):
            return ddg
        return f'Using DuckDuckGo fallback ({missing_key} missing).\n\n{ddg}'

    def _brave_api_key(self) -> str:
        return self.config.api_key or os.environ.get("BRAVE_API_KEY", "")

    def _tavily_api_key(self) -> str:
        return self.config.tavily_api_key or os.environ.get("TAVILY_API_KEY", "")

    def _searxng_base_url(self) -> str:
        return self.config.searxng_base_url or os.environ.get("SEARXNG_BASE_URL", "")

    async def _search_brave(self, query: str, n: int) -> str:
        api_key = self._brave_api_key()
        if not api_key:
            return "Error: BRAVE_API_KEY not configured"

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                    timeout=10.0,
                )
                r.raise_for_status()

            results = r.json().get("web", {}).get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    async def _search_tavily(self, query: str, n: int) -> str:
        api_key = self._tavily_api_key()
        if not api_key:
            return "Error: TAVILY_API_KEY not configured"

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": query, "max_results": n},
                    timeout=15.0,
                )
                r.raise_for_status()

            results = r.json().get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                title = _normalize(_strip_tags(item.get("title", "")))
                url = item.get("url", "")
                snippet = _normalize(_strip_tags(item.get("content", "")))
                lines.append(f"{i}. {title}\n   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    async def _search_duckduckgo(self, query: str, n: int) -> str:
        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                )
                r.raise_for_status()

            anchors = re.findall(
                r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                r.text,
                flags=re.I | re.S,
            )
            snippet_matches = re.findall(
                r'<(?:a|div)[^>]*class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
                r.text,
                flags=re.I | re.S,
            )

            if not anchors:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, (url, title_html) in enumerate(anchors[:n], 1):
                title = _normalize(_strip_tags(title_html))
                lines.append(f"{i}. {title}\n   {url}")
                if i - 1 < len(snippet_matches):
                    snippet = _normalize(_strip_tags(snippet_matches[i - 1]))
                    if snippet:
                        lines.append(f"   {snippet}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    async def _search_searxng(self, query: str, n: int) -> str:
        base_url = self._searxng_base_url().strip()
        if not base_url:
            return "Error: SEARXNG_BASE_URL not configured"

        endpoint = f"{base_url.rstrip('/')}/search"

        try:
            async with httpx.AsyncClient(transport=self._transport) as client:
                r = await client.get(
                    endpoint,
                    params={"q": query, "format": "json"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                )
                r.raise_for_status()

            results = r.json().get("results", [])
            if not results:
                return f"No results for: {query}"

            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results[:n], 1):
                title = _normalize(_strip_tags(item.get("title", "")))
                url = item.get("url", "")
                snippet = _normalize(_strip_tags(item.get("content", "")))
                lines.append(f"{i}. {title}\n   {url}")
                if snippet:
                    lines.append(f"   {snippet}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""
    
    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }
    
    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars
    
    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        from readability import Document

        max_chars = maxChars or self.max_chars

        # Validate URL before fetching
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url})

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
            
            ctype = r.headers.get("content-type", "")
            
            # JSON
            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2), "json"
            # HTML
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"
            
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            
            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text})
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})
    
    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))
