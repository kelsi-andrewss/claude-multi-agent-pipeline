"""Web search tool: Google Search grounding via Gemini."""

from __future__ import annotations

import os
import threading

from format_response import DETAIL_DIR
from gemini_client import _gemini


SEARCH_SYSTEM_INSTRUCTION = (
    "You are a web research assistant. ALWAYS use Google Search to find current, "
    "accurate information before responding. Ground every claim in search results. "
    "Include source URLs as inline citations (e.g. [Source Title](url)). "
    "Produce a factual summary — no conversational filler or hedging. "
    "If search results conflict, note the discrepancy and cite both sources."
)

SEARCH_FILE = os.path.join(DETAIL_DIR, "search.md")

# Tracks whether a batch is active. First call to _start_batch() overwrites
# the file and sets the flag. Subsequent calls within the same batch append.
# reset_search_batch() clears the flag so the next call starts fresh.
_batch_lock = threading.Lock()
_batch_active = False


def reset_search_batch() -> None:
    """Call between logical search batches to start a fresh file on next search."""
    global _batch_active
    with _batch_lock:
        _batch_active = False


def _write_search_result(query: str, response: str) -> str:
    """First call in a batch overwrites; subsequent calls append."""
    global _batch_active
    os.makedirs(DETAIL_DIR, exist_ok=True)
    with _batch_lock:
        if _batch_active:
            mode = "a"
        else:
            mode = "w"
            _batch_active = True
    with open(SEARCH_FILE, mode) as f:
        if mode == "a":
            f.write("\n\n---\n\n")
        f.write(f"## {query}\n\n{response}")
    return SEARCH_FILE


def register(mcp):
    @mcp.tool()
    async def web_search(query: str, new_batch: bool = False) -> str:
        """Search the web for current information using Google Search grounding. Returns a cited summary.

        Args:
            query: Search query string.
            new_batch: Set True on the first call of a new search session to clear previous results.
        """
        if new_batch:
            reset_search_batch()

        response = await _gemini(query, system_instruction=SEARCH_SYSTEM_INSTRUCTION)

        if len(response) > 2000:
            path = _write_search_result(query, response)
            first_line = response.split("\n", 1)[0][:120]
            return f"{first_line}... → {path}"

        return response

    return {"web_search": web_search}
