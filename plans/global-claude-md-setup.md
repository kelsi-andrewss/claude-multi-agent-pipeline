# Global CLAUDE.md Setup

## Goal
Create `~/.claude/CLAUDE.md` with personal preferences that apply across all Claude Code sessions and projects.

## File to Create
`/Users/kelsiandrews/.claude/CLAUDE.md`

## Proposed Content

```markdown
# Global Claude Preferences

## Workflow
- Always enter plan mode before implementing non-trivial changes (more than 2-3 files or any architectural decision)
- Never commit without explicit instruction — do not auto-commit after completing work
- Never push to remote unless explicitly asked
- When there are multiple valid approaches, recommend one and explain why rather than listing all options

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

## Before suggesting a commit
- Run the linter if one exists in the project
- Stage specific files by name, never `git add -A`
```

## Verification
1. `cat ~/.claude/CLAUDE.md` shows the content above
2. Start a new Claude Code session — the preferences should be active immediately (no project-specific setup needed)
