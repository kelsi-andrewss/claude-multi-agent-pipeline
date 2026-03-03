# Story 346 — Consolidate Jaccard clustering into shared helpers

## Goal
The Jaccard similarity functions `_tokenize`, `_jaccard`, and `_group_items` already live in `tools_pm_helpers.py`. However, `tools_pm_write.py` and `tools_pm_organize.py` both import and use them directly — this is fine. The real issue is that `_find_best_story_match` in `tools_pm_write.py` and the triage/regroup logic in `tools_pm_organize.py` duplicate similar patterns of "tokenize, score, filter by threshold". Extract the shared scoring pattern into a helper.

## Changes

### 1. `tools_pm_helpers.py` — Add `_score_stories_by_similarity`
Add a new helper function:
```
def _score_stories_by_similarity(
    query: str,
    stories: list[sqlite3.Row],
    threshold: float = 0.3,
    title_col: str = "title",
) -> list[tuple[float, str, str]]:
```
- Tokenizes `query` using `_tokenize`
- Iterates over story rows, tokenizes each title, computes `_jaccard` score
- Returns sorted list of `(score, story_id, story_title)` tuples where score > threshold
- Sorted descending by score

### 2. `tools_pm_write.py` — Replace `_find_best_story_match`
- Import `_score_stories_by_similarity` from helpers
- Rewrite `_find_best_story_match` to use the new helper instead of inline Jaccard logic
- The function still returns `(best_match_id | None, candidates_list)` — same interface

### 3. `tools_pm_organize.py` — Replace inline Jaccard in triage
- Import `_score_stories_by_similarity` from helpers
- In the triage mode's "suggested_moves" section (lines ~197-218), replace the inline loop that tokenizes story titles and compares against epic titles using `_jaccard`
- Use `_score_stories_by_similarity` or at minimum call the shared `_tokenize` + `_jaccard` pattern through the helper
- The regroup mode's similar logic (lines ~354-362) should also use the shared helper

## Validation
- Server starts without errors: `python3 mcp-servers/gemini/server.py`
- `pm_add_task` still auto-matches stories
- `pm_housekeep(mode='triage')` still produces suggested_moves
- `pm_housekeep(mode='regroup')` still produces proposals
