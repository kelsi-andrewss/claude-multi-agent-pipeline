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
- **Route decision**: orchestrator (code-change or "todo:") vs direct coder (files + root cause known, no new story) vs bypass (Q&A, git ops, research).
- **No pre-reading before delegation**: set up pipeline, then launch coder.
- **Protected files**: check for Konva/testable file overlap before proceeding.
- **Workflow answers**: answer only from ORCHESTRATION.md — never from general knowledge.
