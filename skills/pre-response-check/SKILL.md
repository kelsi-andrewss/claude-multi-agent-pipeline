---
name: pre-response-check
description: >
  Invoke before responding to: (1) the first workflow or pipeline question
  in a session, (2) any code-changing request, (3) run/merge triggers,
  (4) any request where ORCHESTRATION.md rules might change the answer.
  Do NOT invoke for: follow-up questions in an ongoing exchange where
  files were already read this turn or the prior turn, pure factual Q&A
  unrelated to pipeline, simple greetings, or non-project topics.
---

# Pre-Response Orchestration Check

Read both files in parallel before acting:

1. `Read /Users/kelsiandrews/.claude/ORCHESTRATION.md`
2. `Read <project-root>/CLAUDE.md` — use `Glob **/CLAUDE.md` if root unknown.

## Constraints (apply after reading)

- **Zero-skip rule**: code-changing requests go through story → worktree → coder (background). No inline edits.
- **Lightweight path routing**: If a code-changing request qualifies for `/hotfix` (single file, ≤30 lines, known cause, not protected) or `/quickfix` (1-3 files, known cause, not protected), suggest the lighter path. Don't default to `/todo` for everything.
- **Route decision**: orchestrator (code-change or "todo:") vs direct coder (files + root cause known, no new story) vs bypass (Q&A, git ops, research) vs `/hotfix` or `/quickfix` (small known-cause fixes).
- **No pre-reading before delegation**: set up pipeline, then launch coder.
- **Protected files**: check `<project>/.claude/protected-files.md` (or fallback Konva list) for overlap before proceeding.
- **Workflow answers**: answer only from ORCHESTRATION.md — never from general knowledge.
- **Staleness check**: If `<project>/.claude/project-orchestration.md` exists, check ref hashes once per session. Surface warning if stale: "Project orchestration refs are stale. Run `/refine --refresh`."
