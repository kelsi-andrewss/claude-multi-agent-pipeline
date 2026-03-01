# Context

Agent files in `~/.claude/agents/` have no `permissionMode`, `tools`, or `disallowedTools` declared. This means restrictions described in agent system prompts (e.g. "epic-planner never writes files") are enforced only by instruction-following, not by hard tool constraints. Adding proper frontmatter locks down each agent to exactly what it needs.

User wants a dedicated `planner` agent. Since `epic-planner` already handles both epic planning and interactive planning mode, keeping it as-is and just hardening its frontmatter satisfies this — no new file needed.

---

# Changes

## 1. `reviewer.md`
```yaml
permissionMode: default
tools: Read, Glob, Grep, Bash
disallowedTools: Write, Edit
```
Rationale: reviewer only reads diffs and files. No writes ever.

## 2. `quick-fixer.md`
```yaml
permissionMode: acceptEdits
```
Rationale: coder needs full tool access; `acceptEdits` removes edit prompts during automated pipeline runs. No tool restrictions — it must be able to read, write, bash, and commit.

## 3. `architect.md`
```yaml
permissionMode: acceptEdits
```
Same rationale as quick-fixer.

## 4. `todo-orchestrator.md`
```yaml
permissionMode: default
tools: Read, Glob, Grep, AskUserQuestion, Task
disallowedTools: Write, Edit, Bash
```
Rationale: classification-only agent. Hard-block on Write, Edit, Bash enforces "MUST NEVER edit/write source files, run builds, commit, push."

## 5. `git-ops.md`
```yaml
permissionMode: default
tools: Bash
disallowedTools: Read, Write, Edit, Glob, Grep
```
Rationale: git-ops only runs shell commands. Hard-block on all file tools enforces "NEVER read, edit, or write any source file."

## 6. `epic-planner.md`
```yaml
permissionMode: default
tools: Read, Glob, Grep, WebFetch, AskUserQuestion, Task
disallowedTools: Write, Edit, Bash
```
Rationale: research-only agent. Hard-block on Write, Edit, Bash enforces "never edits source files, runs builds, tests, or commits."

**Note**: The `description`, `name`, and all system prompt content stay unchanged. Frontmatter additions only.

## 7. `unit-tester.md`
```yaml
permissionMode: acceptEdits
```
Rationale: needs to write test files and run bash commands. `acceptEdits` removes prompts. No tool restrictions — it must read, write, and run tests.

---

## 8. `ORCHESTRATION.md` — §4 bypass clarification

**Current line (83)**:
```
**Bypass orchestrator entirely** for: pure questions or explanations, read-only research, git/commit/PR operations, non-project tasks.
```

**Replace with**:
```
**Bypass orchestrator entirely** for: pure questions or explanations, read-only research, git/commit/PR operations, and tasks that modify zero files in the working directory.

> **Note**: "non-project tasks" is NOT a bypass category. Documentation files checked into the project repo (`.md`, `.txt`, config docs, `CLAUDE.md`, `ORCHESTRATION.md`, etc.) are project files — editing them requires the full pipeline like any other file change. The only true bypasses are the four categories listed above.
```

---

# Files Modified
- `/Users/kelsiandrews/.claude/agents/reviewer.md`
- `/Users/kelsiandrews/.claude/agents/quick-fixer.md`
- `/Users/kelsiandrews/.claude/agents/architect.md`
- `/Users/kelsiandrews/.claude/agents/todo-orchestrator.md`
- `/Users/kelsiandrews/.claude/agents/git-ops.md`
- `/Users/kelsiandrews/.claude/agents/epic-planner.md`
- `/Users/kelsiandrews/.claude/agents/unit-tester.md`
- `/Users/kelsiandrews/.claude/ORCHESTRATION.md` (line 83 only)

---

# Verification
1. Open a new Claude Code session — agents should load without errors
2. Launch a `todo-orchestrator` task and verify it cannot call Bash (should be denied automatically)
3. Launch a `git-ops` task and verify it cannot call Read/Edit (should be denied automatically)
4. Launch `quick-fixer` on a test worktree — should auto-accept edits without prompts
