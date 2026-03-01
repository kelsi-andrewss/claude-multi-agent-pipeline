# Plan: Fix 3 Gaps in Advocate Research Docs

## Context

The gap analysis of the Advocate research package identified 3 issues that need to be resolved before implementation begins. These are documentation/planning fixes, not code changes. All edits are to the markdown files in `/Users/kelsiandrews/gauntlet/openemr/project_requirements_and _research/`.

The project requirements doc (`G4 Week 2 - AgentForge - Project Requirements.md`) mandates:
- GitHub repo must include `seed_patient.py`
- Demo video must show a working agent
- AI Cost Analysis must include **actual dev spend**, not just projections

---

## Gap 1: `seed_patient.py` is missing from the repo

**Problem:** The presearch specifies `seed_patient.py` completely (Section 16.11) and lists it as a required GitHub repo deliverable (Section 13), but the file doesn't exist. Everything in the 24-hour sprint depends on it — Hours 0-3 is auth + seeding before any tool work begins.

**Fix:** Add a note to `advocate_presearch_v10.md` Section 16.12 (24-Hour Execution Sequence) flagging that `seed_patient.py` must be created as Hour 0 — before repo setup — since it is the first dependency. Also update the deliverables table (Section 13) to mark this as "required, not stretch."

No content changes needed — the spec in Section 16.11 is already complete. This is a prioritization/visibility fix only.

---

## Gap 2: Demo 5 (Marcus) depends on stretch Tool 6

**Problem:** `advocate_demos_3_10.md` Demo 5 (Marcus, cardiac risk) is written assuming `provider_finder` (Tool 6) exists and is called. The presearch explicitly labels Tool 6 as "Stretch — Friday if time permits." If Tool 6 doesn't get built, Demo 5 is unrunnable — and the project requires a working demo video.

**Fix:** Two edits to `advocate_demos_3_10.md`:

1. Add a **conditional header** to Demo 5 at the top:
   > "Note: Demo 5 requires Tool 6 (provider_finder). If Tool 6 is not built by demo time, use the Demo 5 Fallback below."

2. Add a **Demo 5 Fallback** section at the end of Demo 5 that routes Marcus through the Tools 1-3 flow (symptom_timeline → specialist_navigator → appointment_brief_generator) focused on his cardiac risk factors and pre-cardiology checklist — no provider search. This produces a complete, compelling demo without Tool 6.

---

## Gap 3: Cost analysis is still a pre-sprint estimate

**Problem:** The project requirements mandate "actual dev spend" tracked during development. The presearch currently has a placeholder estimate ($0.04-0.07/session) with a note "to be validated against actual measurements during sprint." LangSmith is already in the stack and tracks token usage natively — but there's no reminder or mechanism to capture this.

**Fix:** Update `advocate_presearch_v10.md` Section 13 (Deliverables) AI Cost Analysis row to add:

> "Token tracking: LangSmith logs input/output tokens per request automatically. At sprint end, export token usage from LangSmith dashboard, apply Claude Sonnet pricing ($3/1M input, $15/1M output), and replace the pre-sprint estimate with actual measurements."

Also add a one-line note to Section 16.12 Hour 10-12 (LangSmith tracing step):
> "Verify LangSmith token usage is logging — this data feeds the AI Cost Analysis deliverable."

---

## Files to edit

- `/Users/kelsiandrews/gauntlet/openemr/project_requirements_and _research/advocate_presearch_v10.md`
  - Section 13: flag `seed_patient.py` as required (not stretch), add token tracking note to AI Cost Analysis row
  - Section 16.12: add Hour 10-12 LangSmith token verification note

- `/Users/kelsiandrews/gauntlet/openemr/project_requirements_and _research/advocate_demos_3_10.md`
  - Demo 5 header: add conditional note
  - Demo 5 end: add fallback conversation flow (Tools 1-3 only, cardiac checklist focus)

---

## Verification

After edits:
1. Read Demo 5 in `advocate_demos_3_10.md` — confirm conditional header is present and fallback is self-contained (no Tool 6 dependency)
2. Read Section 13 in `advocate_presearch_v10.md` — confirm `seed_patient.py` row is clearly marked required and cost analysis row has the LangSmith export note
3. Read Section 16.12 — confirm Hour 10-12 has the token logging verification note
4. Check that no content was removed — these are additions only
