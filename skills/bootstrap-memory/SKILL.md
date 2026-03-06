---
name: bootstrap-memory
description: Seed OpenMemory with existing knowledge from key-prompts and decisions. Safe to re-run — uses per-entry dedup.
args: []
---

# Bootstrap OpenMemory

Incremental seeding of OpenMemory with project knowledge. Safe to re-run — checks each entry for duplicates before storing.

## Steps

1. **Health check.** Call `openmemory_list(user_id="global", limit=1)`. If unreachable, abort: "OpenMemory not reachable. Ensure Ollama is running (`ollama serve`) and the OpenMemory MCP server is registered."

2. **Seed key prompt patterns.** Read each file in `~/.claude/.claude/tracking/key-prompts/`. For each `##` entry:
   - Extract the title, category, context, prompt, and why-it-worked fields
   - Compute `simhash = md5(compressed_entry)[:16]`
   - Call `openmemory_query(query=<full compressed entry text>, k=3, user_id="global")` — for each result: compare the first 80 chars of `content_preview` against the entry (case-insensitive, whitespace-normalized); if they match, skip (count as `skip_count`). If no content match but a result has matching simhash in metadata, also skip.
   - Otherwise: `openmemory_store(content="<compressed entry>", tags=["prompt-pattern"], user_id="global", metadata={"sector": "procedural", "simhash": "<simhash>"})`
   - Count stored entries as `prompt_count`

3. **Shadow active decisions.** Call `pm_list_decisions(status="active")`. For each decision:
   - Compute `simhash = md5(decision_summary)[:16]`
   - Call `openmemory_query(query=<full decision summary text>, k=3, user_id="proj:dotclaude")` — for each result: compare the first 80 chars of `content_preview` against the entry (case-insensitive, whitespace-normalized); if they match, skip (count as `skip_count`). If no content match but a result has matching simhash in metadata, also skip.
   - Otherwise: `openmemory_store(content="Decision [id]: <title> — <summary>", tags=["decision"], user_id="proj:dotclaude", metadata={"sector": "semantic", "decision_id": "<id>", "simhash": "<simhash>"})`
   - Count stored entries as `decision_count`

4. **Report.** Print: "Bootstrapped N memories (M prompt patterns, K decisions). Skipped J duplicates."
