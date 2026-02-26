"""web 组工具 — web_fetch HTTP 获取"""

import re

import httpx

_DEFAULT_MAX_LENGTH = 8000
_REQUEST_TIMEOUT = 15
_USER_AGENT = "Mozilla/5.0 (compatible; AgentBot/1.0)"


def _html_to_text(html: str) -> str:
    """将 HTML 转换为可读纯文本（纯正则方案，不引入额外依赖）"""
    text = html

    for tag in ("script", "style", "nav", "footer", "header"):
        text = re.sub(
            rf"<{tag}[^>]*>.*?</{tag}>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    for i in range(1, 7):
        text = re.sub(
            rf"<h{i}[^>]*>(.*?)</h{i}>",
            lambda m, level=i: "\n" + "#" * level + " " + m.group(1).strip() + "\n",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|tr|td|th)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")

    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    return text.strip()


def register(registry, ctx=None):
    """注册 web 组工具"""

    @registry.tool(
        description=(
            "Fetch a URL and return its content as text. "
            "HTML pages are automatically converted to readable text. "
            "Use this to access web pages, APIs, documentation, etc."
        ),
        parameters={
            "url": {
                "type": "STRING",
                "description": "The URL to fetch",
            },
            "extract_text": {
                "type": "STRING",
                "description": "Set to 'false' to return raw content without HTML stripping (default: 'true')",
                "required": False,
            },
            "max_length": {
                "type": "NUMBER",
                "description": "Max chars to return (default: 8000)",
                "required": False,
            },
        },
        group="web",
    )
    def web_fetch(url: str, extract_text: str = "true", max_length: int = _DEFAULT_MAX_LENGTH) -> str:
        """获取 URL 内容"""
        try:
            max_length = min(int(max_length), 50000)

            if not url.startswith(("http://", "https://")):
                return "Error: URL must start with http:// or https://"

            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": _USER_AGENT},
            )

            if response.status_code != 200:
                return f"HTTP {response.status_code}: {response.reason_phrase}\n{response.text[:500]}"

            content_type = response.headers.get("content-type", "")
            body = response.text

            should_extract = extract_text.lower() != "false"
            if should_extract and "text/html" in content_type:
                body = _html_to_text(body)

            if len(body) > max_length:
                half = max_length // 2
                body = (
                    body[:half]
                    + f"\n\n... [内容被截断，共 {len(body)} 字符，显示前 {half} + 后 {half}] ...\n\n"
                    + body[-half:]
                )

            return body

        except httpx.TimeoutException:
            return f"Error: request timed out ({_REQUEST_TIMEOUT}s): {url}"
        except httpx.ConnectError as e:
            return f"Error: connection failed: {e}"
        except Exception as e:
            return f"Error: web_fetch failed: {type(e).__name__}: {e}"

    @registry.tool(
        description=(
            "Search the web for current information using a search engine. "
            "Returns titles, URLs, and snippets for each result. "
            "Use this when you need up-to-date facts, news, weather, prices, or any real-time information."
        ),
        parameters={
            "query": {
                "type": "STRING",
                "description": "Search query (e.g., 'kobe weather tomorrow', '2026年AI趋势')",
            },
            "max_results": {
                "type": "NUMBER",
                "description": "Number of results (default: 5, max: 10)",
                "required": False,
            },
            "region": {
                "type": "STRING",
                "description": "Region code (e.g., 'jp-jp', 'cn-zh', 'wt-wt' for global). Default: 'wt-wt'",
                "required": False,
            },
        },
        group="web",
    )
    def web_search(query: str, max_results: int = 5, region: str = "wt-wt") -> str:
        from ddgs import DDGS

        if not query.strip():
            return "Error: search query cannot be empty"
        max_results = max(1, min(int(max_results), 10))
        try:
            results = DDGS().text(query, max_results=max_results, region=region)
            if not results:
                return f"No results found for: {query}"
            lines = []
            for i, r in enumerate(results, 1):
                lines.append(f"### {i}. {r.get('title', 'Untitled')}")
                lines.append(f"**URL**: {r.get('href', '')}")
                lines.append(r.get('body', ''))
                lines.append("")
            return "\n".join(lines).strip()
        except Exception as e:
            return f"Error: web search failed: {type(e).__name__}: {e}"
