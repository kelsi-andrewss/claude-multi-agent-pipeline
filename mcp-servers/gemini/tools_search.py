"""Web search tool: Google Search grounding via Gemini."""

from __future__ import annotations

from format_response import _write_detail
from gemini_client import _gemini


SEARCH_SYSTEM_INSTRUCTION = (
    "You are a web research assistant. ALWAYS use Google Search to find current, "
    "accurate information before responding. Ground every claim in search results. "
    "Include source URLs as inline citations (e.g. [Source Title](url)). "
    "Produce a factual summary — no conversational filler or hedging. "
    "If search results conflict, note the discrepancy and cite both sources."
)


def register(mcp):
    @mcp.tool()
    async def web_search(query: str) -> str:
        """Search the web for current information using Google Search grounding. Returns a cited summary."""
        response = await _gemini(query, system_instruction=SEARCH_SYSTEM_INSTRUCTION)

        if len(response) > 2000:
            path = _write_detail("search.md", response)
            first_line = response.split("\n", 1)[0][:120]
            return f"{first_line}... → {path}"

        return response

    return {"web_search": web_search}
