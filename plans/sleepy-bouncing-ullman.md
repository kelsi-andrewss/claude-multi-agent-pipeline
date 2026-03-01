# Bounty Compliance Plan

## Context

The AgentForge bounty awards $500 for the most impactful customer use case with: a real data source, agent-driven CRUD, evals, observability, and verification. We need to assess what Advocate already covers vs. what gaps remain.

## What Already Exists (Strong)

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Real data source | **Strong** | OpenEMR FHIR R4 via OAuth2, pagination, FHIRService |
| Verification | **Strong** | 5-layer pipeline: citation, hallucination, boundary, confidence, escalation |
| Observability | **Partial** | LangSmith @traceable on 3 fns, SSE callback on tool calls — no structured logging |
| Evals | **Partial** | 50+ pytest cases, injection guard, verification layer; no LangSmith dataset format |
| CRUD (auth layer) | **Partial** | Firestore users/{uid} R/W — but agent tools never call it |
| BOUNTY.md | **Missing** | File does not exist |

## Critical Gaps

### Gap 1 — Agent-Driven CRUD (BLOCKER)

**Bounty requirement**: "Store stateful data tied to the data source in the app and expose CRUD operations the agent uses."

**Current state**: All 6 tools are read-only. They read FHIR, write to in-memory `session_state` only — nothing persists. The agent never calls Firestore write operations.

**Fix**: Add at least one agent tool that does persistent CREATE + UPDATE. Best fit: a **symptom notes tool** — lets the agent save/update patient-reported symptoms to Firestore (`patients/{patient_id}/notes`). This is relevant to the problem space (patient advocacy), uses the same patient_id data source, and gives the agent a meaningful reason to write (capture patient's own language for appointment briefs).

**Minimum implementation**:
- New Firestore collection: `patients/{patient_id}/notes` with fields `note_text`, `created_at`, `updated_at`, `session_id`
- Tool: `save_symptom_note(patient_id, note_text)` — CREATE in Firestore
- Tool (or same tool with update): `get_symptom_notes(patient_id)` — READ from Firestore
- Wire into agent as two new tools
- Demo path: user describes symptoms → agent saves note → agent reads saved notes when building appointment brief

### Gap 2 — BOUNTY.md (BLOCKER)

**Bounty requirement**: File must exist covering: customer, feature(s), data source used, impact.

**Fix**: Write `BOUNTY.md` at project root with:
- Customer: patients with complex/chronic conditions navigating fragmented care
- Feature: FHIR-backed symptom advocacy agent with verification pipeline
- Data source: OpenEMR FHIR R4 (encounters, conditions, medications, observations, coverage)
- Impact: quantified (% dismissal reduction, time-to-prep, eval pass rates)

### Gap 3 — Observability (Minor)

**What we have**: LangSmith traces on 3 functions, SSE tool-call events.
**What's missing**: Structured logging (Python `logging` module), no request/response log on FastAPI, no persistent audit trail.

**Fix (lightweight)**: Add Python `logging` setup in `main.py` — use `logging.getLogger(__name__)` with JSON formatter, log each `/chat` request in/out with session_id and latency. This is a 20-line change that closes the gap for the bounty.

### Gap 4 — Evals format (Minor)

**What we have**: pytest-based evals, not LangSmith dataset format.
**What's missing**: LangSmith eval datasets that produce a measurable pass rate dashboard.

**Fix**: This is optional for the bounty — pytest evals plus LangSmith tracing likely satisfies "evals" criteria. Defer unless we have time.

---

## Recommended Implementation Order

1. **BOUNTY.md** — write first (no code, high visibility)
2. **Agent CRUD tools** — `save_symptom_note` + `get_symptom_notes` tools wired into agent
3. **Structured logging** — 20-line `logging` setup in `main.py`

## Files to Create/Modify

| File | Action |
|------|--------|
| `BOUNTY.md` | **Create** — bounty deliverable doc |
| `advocate/tools/symptom_notes.py` | **Create** — Firestore CRUD tool |
| `advocate/agent.py` | **Edit** — register 2 new tools |
| `advocate/main.py` | **Edit** — add structured logging |
| `advocate/models.py` | **Edit** — add SymptomNote model |
| `tests/test_tools/test_symptom_notes.py` | **Create** — tests for new tool |

## Verification

After implementation:
- `python -m pytest tests/ -x --tb=short` passes
- `ruff check .` clean
- Agent can save a note and retrieve it in same session
- BOUNTY.md present at repo root with all 4 required sections
