---
name: bootstrap-memory
description: Seed OpenMemory with existing knowledge from key-prompts, decisions, tool learnings, and behavioral prefs. Safe to re-run — uses per-entry dedup.
args: []
---

# Bootstrap OpenMemory

Incremental seeding of OpenMemory with project knowledge. Safe to re-run — checks each entry for duplicates before storing.

## Steps

0. **Setup auto memory symlinks.** Run `~/.claude/scripts/setup-memory.sh`. This creates the machine-specific `projects/<encoded>/memory/` directories and symlinks them to the portable `memory/*.md` files. If the script fails, warn but continue — OpenMemory seeding doesn't depend on symlinks.

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

4. **Seed tool learnings.** Read `~/.claude/tool-learnings.md`. For each `- ` prefixed line (skip headers and blank lines):
   - Extract the learning text (strip leading `- `)
   - Compute `simhash = md5(learning_text)[:16]`
   - Call `openmemory_query(query=<learning_text>, k=3, user_id="global")` — apply same dedup logic (first 80 chars content match OR simhash match → skip)
   - Otherwise: `openmemory_store(content="<learning_text>", tags=["tool-learning"], user_id="global", metadata={"sector": "procedural", "simhash": "<simhash>"})`
   - Count stored entries as `learning_count`

5. **Shadow behavioral prefs.** Read `~/.claude/behavioral-prefs.md`. For each `- ` prefixed line under `##` headings (skip the metadata comment and blank lines):
   - Extract the preference text (strip leading `- `)
   - Compute `simhash = md5(pref_text)[:16]`
   - Call `openmemory_query(query=<pref_text>, k=3, user_id="proj:dotclaude")` — apply same dedup logic
   - Otherwise: `openmemory_store(content="<pref_text>", tags=["behavioral-pref"], user_id="proj:dotclaude", metadata={"sector": "procedural", "simhash": "<simhash>"})`
   - Count stored entries as `pref_count`

6. **Report.** Print: "Bootstrapped N memories (P prompt patterns, D decisions, L tool learnings, B behavioral prefs). Skipped J duplicates."
