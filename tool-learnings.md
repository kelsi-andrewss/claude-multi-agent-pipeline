# Tool & Model Learnings

Append-only log of model/tool capability observations. OpenMemory (procedural sector, global scope) is the queryable store — this file is the audit trail.

**Format**: `- [YYYY-MM-DD] <observation> (evidence: N occurrences)`

---

- [2026-03-04] `pm_dev_branch` returns `dev/<epic-slug>` which conflicts when a `dev` branch already exists (git ref prefix collision). Fallback to `epic/<slug>` causes the pipeline to lose track of the real merge hierarchy — the epic branch gets mentally promoted to "dev branch" and the actual `dev` branch disappears from the merge chain. Fix: detect existing `dev` branch and use it as the integration target, with the epic branch as staging below it. Resulted in accidental force-push to main. (evidence: 1 occurrence, legacylens)
- [2026-03-05] Haiku coders replace regexes wholesale instead of extending them. When told to "expand SYSTEM_MSG regex", Haiku replaced the entire pattern, dropped original XML detection patterns, and added `^(User:|Assistant:)` which matched every line. Fix: coder prompts for regex changes should explicitly list existing patterns to preserve, or say "add these patterns to the existing regex." (evidence: 1 occurrence, epic-86 story-496)
