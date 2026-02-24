# Global Claude Preferences

## Communication style
- Be concise. Skip preamble and filler.
- When I ask "why did you choose X", explain the reasoning — don't just restate what X is
- If a task is ambiguous, ask one focused clarifying question rather than listing all possible interpretations

## Code style
- Prefer editing existing files over creating new ones
- Don't add comments, docstrings, or type annotations to code I didn't touch
- Don't add error handling for scenarios that can't happen
- Don't over-engineer — solve the current problem, not hypothetical future ones
- No emojis in code or commit messages
- Prefer CSS variables and dark-mode-aware tokens over hardcoded color values
- Avoid `!important` — use a more specific selector to resolve conflicts instead

## React
- When a hook needs fresh state inside an async callback (setTimeout, Firebase listener, API response handler), store it in a ref and read `.current` — don't close over state directly

## Firebase
- Always use `writeBatch` for mutations touching more than one related document — sequential writes create consistency windows
- `writeBatch` has a hard limit of 500 writes per batch. Always chunk loops that write to Firestore into batches of ≤500, committing each before starting the next

## Parallelism
- When a bash command (build, lint, test, git op) is independent of the next read or write, run it with `run_in_background: true` and proceed immediately — don't wait for it to finish before starting unrelated work.
- Read the background result only when the next decision actually depends on it.
- Concrete pattern: after finishing edits, launch `npm run build` in background and simultaneously `Read` the next file you need to verify — don't do them sequentially.
- Multiple independent Glob/Grep/Read calls must always be issued in a single message, never one at a time.

## Before suggesting a commit
- Run the linter if one exists in the project
- Stage specific files by name, never `git add -A`
- Never include secrets, API keys, or tokens in commit messages or code — they belong only in .env files

## Tracking
- After completing significant work (bug fix, feature, refactor, plan approval), append a prompt assessment entry to `<project>/.claude/tracking/key-prompts/YYYY-MM-DD.md` (today's date). Create the file if it doesn't exist, using the same header format as existing files in that folder.
- Use this format:
  ## [date] — [short title]
  **Category**: breakthrough | bug-resolution | architecture | feature
  **Context**: What problem was being solved?
  **The Prompt**: (exact or close paraphrase)
  **Why It Worked**: (what made the phrasing/framing effective)
  **Prior Attempts That Failed**: (for bugs: what didn't work; otherwise: N/A)
- Only write entries for genuinely high-signal prompts. Skip routine exchanges.
- When a planning session ends without implementation (plan rejected, approach changed, or pure research), still write a tracking entry — mark it as architecture category and note what was decided against and why.
- Do not ask permission — just append after significant work.

## Integration surfaces
When a project ships a feature that exposes a registry, hook, or plugin API that other features must wire into (e.g. command palette, context menu, keyboard shortcut registry, settings panel sections), add or update an `## Integration surfaces` section in that project's CLAUDE.md. Each entry names the surface, its owner file(s), and the registration pattern. This section is read by the epic-planner (see ORCHESTRATION.md §19.2) to auto-generate integration stories when parallel features share a surface. If the section does not exist in a project's CLAUDE.md, create it when the first surface ships.

## Main session orchestration rules
See ~/.claude/ORCHESTRATION.md — applies to the main session only, not to spawned agents.
