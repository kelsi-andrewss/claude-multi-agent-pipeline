# Tool & Model Learnings

Append-only log of model/tool capability observations. OpenMemory (procedural sector, global scope) is the queryable store — this file is the audit trail.

**Format**: `- [YYYY-MM-DD] <observation> (evidence: N occurrences)`

---

- [2026-03-04] `pm_dev_branch` returns `dev/<epic-slug>` which conflicts when a `dev` branch already exists (git ref prefix collision). Fallback to `epic/<slug>` causes the pipeline to lose track of the real merge hierarchy — the epic branch gets mentally promoted to "dev branch" and the actual `dev` branch disappears from the merge chain. Fix: detect existing `dev` branch and use it as the integration target, with the epic branch as staging below it. Resulted in accidental force-push to main. (evidence: 1 occurrence, legacylens)
- [2026-03-05] Haiku coders replace regexes wholesale instead of extending them. When told to "expand SYSTEM_MSG regex", Haiku replaced the entire pattern, dropped original XML detection patterns, and added `^(User:|Assistant:)` which matched every line. Fix: coder prompts for regex changes should explicitly list existing patterns to preserve, or say "add these patterns to the existing regex." (evidence: 2 occurrences, epic-86 story-496, epic-91 story-512)
- [2026-03-05] macOS screenshots saved from chat/browsers often contain non-breaking spaces (U+00A0) in filenames instead of regular spaces (U+0020). `mv` with quoted paths fails silently because the bytes don't match. Fix: use shell globs (`Screenshot*.png`) to sidestep encoding issues. (evidence: 1 occurrence)
- [2026-03-07] AUTO: Glob failed: <tool_use_error>Cancelled: parallel tool call Read(/Users/kelsiandrews/.claude/.claude/sett…) errored</tool_use_error>. Recovery: Read on settings.json (source: error-recovery, session: a5c1b557)
- [2026-03-07] AUTO: Read failed: File does not exist. Note: your current working directory is /Users/kelsiandrews/.claude.. Recovery: Glob (source: error-recovery, session: a5c1b557)
- [2026-03-07] AUTO: Assistant: I see the session start message said "Hook profile: standard" — let me find how profiles are managed (source: implicit-decision, session: a5c1b557)
