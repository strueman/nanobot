import httpx
import pytest

from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import WebSearchConfig


@pytest.mark.asyncio
async def test_web_search_brave_provider_formats_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert (
            str(request.url) == "https://api.search.brave.com/res/v1/web/search?q=nanobot&count=1"
        )
        assert request.headers["X-Subscription-Token"] == "brave-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "NanoBot",
                            "url": "https://example.com/nanobot",
                            "description": "Ultra-lightweight assistant",
                        }
                    ]
                }
            },
        )

    tool = WebSearchTool(
        config=WebSearchConfig(provider="brave", api_key="brave-key", max_results=5),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(query="nanobot", count=1)
    assert "Results for: nanobot" in result
    assert "1. NanoBot" in result
    assert "https://example.com/nanobot" in result


@pytest.mark.asyncio
async def test_web_search_tavily_provider_formats_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.tavily.com/search"
        payload = request.read().decode("utf-8")
        assert '"api_key":"tavily-key"' in payload
        assert '"query":"openclaw"' in payload
        assert '"max_results":2' in payload
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "OpenClaw",
                        "url": "https://example.com/openclaw",
                        "content": "Plugin-based assistant framework",
                    }
                ]
            },
        )

    tool = WebSearchTool(
        config=WebSearchConfig(provider="tavily", tavily_api_key="tavily-key", max_results=5),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(query="openclaw", count=2)
    assert "Results for: openclaw" in result
    assert "1. OpenClaw" in result
    assert "https://example.com/openclaw" in result


@pytest.mark.asyncio
async def test_web_search_duckduckgo_provider_parses_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "html.duckduckgo.com"
        html = """
        <html><body>
          <a class=\"result__a\" href=\"https://example.com/a\">First Result</a>
          <a class=\"result__snippet\">Snippet A</a>
          <a class=\"result__a\" href=\"https://example.com/b\">Second Result</a>
          <a class=\"result__snippet\">Snippet B</a>
        </body></html>
        """
        return httpx.Response(200, text=html)

    tool = WebSearchTool(
        config=WebSearchConfig(provider="duckduckgo", max_results=5),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(query="assistant", count=2)
    assert "Results for: assistant" in result
    assert "1. First Result" in result
    assert "https://example.com/a" in result
    assert "2. Second Result" in result
    assert "https://example.com/b" in result


@pytest.mark.asyncio
async def test_web_search_legacy_constructor_still_works() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"title": "Legacy", "url": "https://example.com", "description": "ok"}
                    ]
                }
            },
        )

    tool = WebSearchTool(
        api_key="legacy-key", max_results=3, transport=httpx.MockTransport(handler)
    )
    result = await tool.execute(query="legacy", count=1)
    assert "1. Legacy" in result


@pytest.mark.asyncio
async def test_web_search_brave_falls_back_to_duckduckgo_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "html.duckduckgo.com"
        html = """
        <html><body>
          <a class=\"result__a\" href=\"https://example.com/fallback\">Fallback Result</a>
          <a class=\"result__snippet\">Fallback snippet</a>
        </body></html>
        """
        return httpx.Response(200, text=html)

    tool = WebSearchTool(
        config=WebSearchConfig(provider="brave", api_key="", max_results=5),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(query="fallback", count=1)
    assert "Using DuckDuckGo fallback" in result
    assert "1. Fallback Result" in result


@pytest.mark.asyncio
async def test_web_search_tavily_falls_back_to_duckduckgo_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "html.duckduckgo.com"
        html = """
        <html><body>
          <a class=\"result__a\" href=\"https://example.com/tavily-fallback\">Tavily Fallback</a>
          <a class=\"result__snippet\">Fallback snippet</a>
        </body></html>
        """
        return httpx.Response(200, text=html)

    tool = WebSearchTool(
        config=WebSearchConfig(provider="tavily", tavily_api_key="", max_results=5),
        transport=httpx.MockTransport(handler),
    )

    result = await tool.execute(query="fallback", count=1)
    assert "Using DuckDuckGo fallback" in result
    assert "1. Tavily Fallback" in result


@pytest.mark.asyncio
async def test_web_search_brave_missing_key_without_fallback_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    tool = WebSearchTool(
        config=WebSearchConfig(
            provider="brave",
            api_key="",
            fallback_to_duckduckgo_on_missing_key=False,
        )
    )

    result = await tool.execute(query="fallback", count=1)
    assert result == "Error: BRAVE_API_KEY not configured"
