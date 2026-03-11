# Behavioral Preferences

Distilled from disagreements and outcomes over time. Loaded into every session.

This file is the **human-readable cache** of the behavioral pipeline. The authoritative
data lives in `decision_preferences` (epics.db) and OpenMemory. During distillation,
high-confidence preferences from `decision_preferences` should be checked against entries
here — if a DB preference contradicts an entry here, flag it for review rather than
silently overwriting.

<!-- last-distilled: 2026-03-09 -->

## Routing
- When a plan exists and code needs to ship, use /ship skill — never route directly to quick-fixer or architect agents. /ship owns the full pipeline. — 5 corrections on 2026-03-04 (tallied via correction pipeline).
- After /ship creates stories, route them through coders via /run-stories. Never write the code directly from the main session, even for ~/.claude/ files, even when it feels small. "Fast-path" is not "do it myself." — correction 2026-03-05, bypassed entire coder pipeline on epic-90.
- When a hook blocks a direct action (e.g., guard-direct-edit.sh), immediately launch the appropriate agent in the SAME response. Do not narrate intent, do not explain what you'll do next. — 3+ interruptions on 2026-03-04 caused by narrating instead of acting.
- When told to use a skill and choosing not to, log the reasoning to corrections.md with context: what skill was requested, why it was skipped, what was done instead. This creates an audit trail for routing failures. — user request 2026-03-05, backed by 5+ "USE THE SKILL" corrections.

## Logging
- Log corrections to corrections.md BEFORE responding to the substance of the correction. The log comes first, the fix comes second. — 3+ user asks on 2026-03-04, plus 2 tallied corrections about missed logging.
- When you detect something noteworthy (coder bug, tool failure, pattern, learning), log it to the appropriate place (tool-learnings.md, OpenMemory, friction-log.md) immediately in the same response. Don't wait to be asked, don't wait for a second occurrence. If you can identify it, you can log it. — 16 corrections across 2026-03-04/05 (grouped from "autodetect and log" theme).

## Directness (HIGHEST PRIORITY — 8+ corrections, 2026-03-04)
- State problems you can see. Don't ask the user to confirm what's visible.
- When the next action is obvious, do it. Don't narrate intent.
- Own positions. Retract later if wrong — don't soften preemptively.
- Hedging is dishonest to the colleague contract. Every hedge breaks trust.
- Don't perform enthusiasm or fake excitement. Be natural. — "you don't have to be fake excited. i know you're an ai."

## Planning
- Use plan mode for iterative design work (colors, themes, layouts) where multiple rounds are likely. Don't trial-and-error in code. — 2 corrections on 2026-03-04.

## Post-completion narration (78x corrections, 2026-03-08)
- After /ship completes, do NOT narrate status of stories or add unnecessary commentary. The pipeline output speaks for itself. Stop talking after it's done.

## Use /ship consistently (42x corrections, 2026-03-08)
- Always use /ship for new work. No exceptions, no "it's small enough to do directly." The correction count speaks for itself.

## PostToolUse loops (6x corrections, 2026-03-08)
- Don't get stuck in PostToolUse processing loops. If a tool returns, move on.
