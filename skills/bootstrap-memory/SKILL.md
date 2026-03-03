---
name: bootstrap-memory
description: Seed OpenMemory with existing knowledge from key-prompts, conventions, and decisions. Run once after OpenMemory infrastructure is set up.
args: []
---

# Bootstrap OpenMemory

One-time seeding of OpenMemory with existing knowledge. Safe to re-run — checks for prior bootstrap.

## Steps

1. **Health check.** Call `openmemory_list(user_id="global", limit=1)`. If unreachable, abort: "OpenMemory not reachable. Ensure Ollama is running (`ollama serve`) and the OpenMemory MCP server is registered."

2. **Check if already bootstrapped.** Call `openmemory_query(query="bootstrap", tags=["bootstrap"], user_id="global")`. If results exist, report: "Already bootstrapped (N existing bootstrap memories). Skipping." and stop.

3. **Seed key prompt patterns.** Read each file in `~/.claude/.claude/tracking/key-prompts/`. For each `##` entry:
   - Extract the title, category, context, prompt, and why-it-worked fields
   - `openmemory_store(content="<compressed entry>", tags=["bootstrap", "prompt-pattern"], user_id="global", metadata={"sector": "procedural"})`
   - Count stored entries as `prompt_count`

4. **Seed core conventions.** Store these curated conventions (not a bulk import):
   - "Coders only execute approved plan files — they never plan. §1 and §8."
   - "Stage files by name, never `git add -A`. Secrets risk. CLAUDE.md commits section."
   - "Stories with >5 write-target files or >200 estimated lines should be split. §8 size ceiling."
   - "Protected files require explicit user confirmation before launching coders. §14."
   - "Hooks: exit 0 = allow, exit 2 = block. Stdin receives JSON with tool_input."
   - "Session handoff: write ~/.claude/session-handoff.md before /clear. Keep under 10 lines. §10."
   - "Fast-path planning: quick-fixer + ≤2 files + no protected files + tasks defined = skip Gemini. §3."
   - "NEED_DECISION does not count toward escalation threshold. Only BLOCKED returns count. §8."

   Each: `openmemory_store(content="<convention>", tags=["bootstrap", "convention"], user_id="proj:dotclaude", metadata={"sector": "semantic"})`
   Count as `convention_count`

5. **Shadow active decisions.** Call `pm_list_decisions(status="active")`. For each decision:
   - `openmemory_store(content="Decision [id]: <title> — <summary>", tags=["bootstrap", "decision"], user_id="proj:dotclaude", metadata={"sector": "semantic", "decision_id": "<id>"})`
   - Count as `decision_count`

6. **Report.** Print: "Bootstrapped N memories (M prompt patterns, K conventions, J decisions)."
