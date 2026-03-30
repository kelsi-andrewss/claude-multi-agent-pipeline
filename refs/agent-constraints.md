# Agent Constraints

Injected into all spawned agent prompts. Keep this under 15 lines.

- **Branches**: merge to `dev`, never `main`. Use `story-<id>/<slug>` naming.
- **Write targets**: no shared write targets with other in-progress stories.
- **Size**: >5 files or >200 lines in a single story → stop and report `BLOCKED: scope exceeded`.
- **Return contract**: end with `DONE: <summary>`, `NEED_DECISION: <question>`, or `BLOCKED: <reason>`.
- **Commits**: stage files by name, never `git add -A`. No secrets in code or messages.
- **Protected files**: if a plan lists protected files, confirm with the user before editing.
