# Pitfalls: CLAUDE.md / Orchestration Config

- CLAUDE.md teaches *how to think*, not *what to do* — describe the reasoning model ("responsible engineers check in before irreversible actions") rather than enumerating every specific action ("always ask before deleting files")
- Rules that explain their *why* get followed; rules that just state *what* get cargo-culted or ignored when context shifts
- Prefer principles over checklists — "changes should be scoped" is durable; "always run lint, then test, then commit" breaks the moment the project adds a new tool
- ORCHESTRATION.md is the constitution, skills are the procedures — don't duplicate procedure steps in ORCHESTRATION.md and don't embed constitutional principles in skills
- Section numbers in ORCHESTRATION.md are stable references (§1, §8) — adding a section means picking the next number, not renumbering existing ones
- `behavioral-prefs.md` is a cache, not a source of truth — the authoritative data lives in `decision_preferences` (epics.db) and OpenMemory; prefs here are distilled summaries
- Protected files are declared in `<project>/.claude/protected-files.md`, not enforced by CLAUDE.md prose — if you want a file protected, add it to the list; don't just write "never edit X"
- Hook registration requires both `hooks.<event>` and `permissions.allow` entries in `settings.json` — missing either silently fails
- Validate `settings.json` after every edit (`python3 -c "import json; json.load(open('settings.json'))"`) — a trailing comma or missing quote breaks all hooks
- When adding a new integration surface (registry, hook API, plugin point), document it in the project's CLAUDE.md so future sessions know to wire into it
