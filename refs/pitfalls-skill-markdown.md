# Pitfalls: Skill Markdown

- Skills are templates, not documentation — `<dev-branch>`, `<worktree-path>`, `{{args}}` are placeholders the executor fills in at runtime; don't escape or literalize them
- Bash code blocks are instructional, not copy-pasteable — they show the pattern; the executor adapts paths and variables to the current context
- Reference sections by header name, not line number — line numbers shift after every edit
- Step numbers are part of the skill's API — hooks, other skills, and ORCHESTRATION.md reference steps by number (e.g., "Step 3" or "§8"); renumbering without updating references breaks cross-cutting concerns
- Frontmatter (`name`, `description`, `args`) is machine-parsed — `name` must match the directory name, `args` entries define what `{{args}}` expands to
- The output policy section is a constraint on the executor, not a suggestion — "only output is the final report" means no intermediate narration
- Conditional logic uses markdown bold/blockquote formatting (`**If X:**`, `> Note:`) — these are control flow for the executor, not prose decoration
- When a skill calls another skill (`Skill: merge-worktree, args: "story-NNN"`), the inner skill runs with its own full instruction set — don't inline its logic
- Keep decision rules near the top (before steps) so the executor loads them into context before acting — rules buried after Step 6 may get lost to context compression
