# MVP Implementation Plan — Advocate Agent

## Context

The `advocate/` directory contains only documentation (CLAUDE.md, REQUIREMENTS.md, ROADMAP.md, .env.example). Zero Python source files exist. This plan implements the full MVP tool set as a sequenced set of pipeline stories, starting with the shared foundation files and working up through the tools.

The ROADMAP.md specifies MVP Phase 1 ordering: models → fhir_client → tools → agent → main. The epics.json stories are already staged in `filling` state. We run them sequentially where there are shared write targets (models.py, agent.py) and in parallel where there is no overlap.

---

## Stories to Run (MVP Batch)

### Group 1 — Foundation (sequential, all touch models.py or agent.py)

Run in this order:

**1. story-054** — `SessionAwareMemory` + `SessionState` + `models.py` scaffold
- Creates: `advocate/agent.py`, `advocate/models.py`
- Establishes all shared Pydantic models (SessionState, TimelineEvent, SymptomTimelineInput/Output, SpecialistNavigatorInput/Output, AppointmentBriefInput/Output, SomaticClassifierOutput, VerificationResult)
- Implements `SessionAwareMemory` subclassing `ConversationBufferWindowMemory(k=10)`, overrides `load_memory_variables()` to prepend `session_state` as SystemMessage
- Creates stub `AgentExecutor` with empty tools list (tools added by later stories)
- Agent: architect / sonnet

**2. story-055** — Structured intake questionnaire + system prompt
- Creates: `advocate/prompts/system.py`
- Modifies: `advocate/agent.py`, `advocate/models.py`
- 8-question intake for "appointment scheduled" entry point (conversational, 1-2 at a time)
- Branching: GP → skip Q4; acute/urgent → redirect; somatic trigger at Q6
- `patient_language_buffer` populated from Q2, Q6, Q8 verbatim
- dependsOn: story-054
- Agent: architect / sonnet

### Group 2 — Tools (parallel, no overlap with each other)

Run in parallel after story-054 completes (they read models.py but only write their own tool files):

**3. story-048** — `symptom_timeline` tool
- Creates: `advocate/tools/symptom_timeline.py`
- Modifies: `advocate/models.py` (adds `TimelineEvent`, `SymptomTimelineInput`, `SymptomTimelineOutput`)
- FHIR queries: Encounter, Condition, Observation, MedicationRequest via `asyncio.gather()`
- Pagination: follow `Bundle.link[rel=next]` until exhausted, cap at 500 resources
- Chronological sort + dedup by (resource_type, date, display)
- Confidence tier: HIGH/MODERATE/LOW per presearch §16.5 logic
- Citation tagging: `[Source: ResourceType/id]` on every event
- dependsOn: story-054
- Agent: architect / sonnet

**4. story-049** — Somatic classifier middleware
- Creates: `advocate/prompts/somatic.py`
- Modifies: `advocate/models.py` (adds `SomaticClassifierOutput`)
- Separate Gemini Flash call (temp=0, max_tokens=50) after every patient turn
- Returns `{somatic_trigger: bool, reason: str}`, JSON parse error → default false
- Sets `session_state.somatic_mode_active = True` on trigger
- Accumulates `patient_language_buffer` from triggered turns
- `SomaticClassifierMiddleware` wraps `AgentExecutor.invoke()` — runs before agent turn
- dependsOn: story-054
- Agent: architect / sonnet

**5. story-050** — `specialist_navigator` tool
- Creates: `advocate/tools/specialist_navigator.py`
- Modifies: `advocate/models.py` (adds `SpecialistNavigatorInput`, `SpecialistNavigatorOutput`)
- Dual-mode: appointment prep (type from symptom constellation) + navigation (PCP-first vs direct)
- Guard rule: if `direct_to_specialist` AND `pathway_evidence` empty → downgrade to `PCP_first`
- Outputs: `recommended_specialty`, `referral_language`, `checklist_items`, `differentiates_from`
- dependsOn: story-054
- Agent: architect / sonnet

### Group 3 — NPPES Taxonomy (depends on specialist_navigator)

**6. story-051** — NPPES taxonomy code mapping
- Creates: `advocate/tools/nppes_taxonomy.py`
- Modifies: `advocate/tools/specialist_navigator.py` (adds `taxonomy_code` to output)
- Maps demo specialties → NPI taxonomy codes: neurotology (207YX0905X), rheumatology (207RR0500X), neurology (2084N0400X), psychiatry (2084P0800X)
- dependsOn: story-050
- Agent: quick-fixer / sonnet

### Group 4 — Agent Wire-up (depends on all tools)

**7. story-056** — Clarification-first sub-flow
- Modifies: `advocate/agent.py`, `advocate/prompts/system.py`
- Conditional prompt injection when `confidence_tier == LOW AND entry_point == navigation`
- Max 3 clarification turns before proceeding regardless
- dependsOn: story-055
- Agent: architect / sonnet

**8. story-057** — Agent error states
- Creates: `advocate/main.py` (FastAPI: `POST /chat`, `GET /health`, CORS)
- Modifies: `advocate/agent.py`, `advocate/models.py`
- FHIR 404 → questionnaire-only fallback
- `FHIRAuthError` → OAuth2 re-auth prompt
- Timeout → partial result with timeout flag
- Diagnosis redirect hard stop
- dependsOn: story-054, story-055
- Agent: architect / sonnet

Also need `fhir_client.py` — this is a prerequisite for any tool FHIR calls. **Create a new story** for it (story-048 and others depend on it):

> **New story needed: `advocate/fhir_client.py`**
> This is the `FHIRService` wrapper around `AsyncFHIRClient`. Without it, stories 048/050/061/064 cannot make any FHIR calls. It must be created before any tool story runs.
> Files: `advocate/fhir_client.py`
> Agent: architect / sonnet
> dependsOn: story-054 (needs models.py for `FHIRAuthError`)

---

## Execution Sequence

```
story-054  →  story-055  (foundation: models.py + agent.py + system.py)
                ↓
        [new fhir_client story]  (FHIRService: AsyncFHIRClient wrapper)
                ↓
story-048 ┐
story-049 ├── parallel (no file overlap)
story-050 ┘
                ↓
story-051  (depends on 050: adds taxonomy_code)
                ↓
story-056  →  story-057  (agent sub-flows + main.py)
```

---

## Key Specs (from advocate/REQUIREMENTS.md + presearch §16)

### models.py — required types
- `SessionState` — full session dict (patient_id, entry_point, stages_completed, somatic_mode_active, patient_language_buffer, confidence_tier, fhir_resources_retrieved, escalation_flags)
- `TimelineEvent(date, resource_type, display, source_id, patient_reported)`
- `SymptomTimelineInput(patient_id, date_from?, date_to?, resource_types?)`
- `SymptomTimelineOutput(timeline, confidence_tier, fhir_counts, gaps_detected, somatic_trigger_recommended)`
- `SpecialistNavigatorInput(symptom_summary, existing_specialist_contacts, appointment_type?)`
- `SpecialistNavigatorOutput(recommended_specialty, rationale, pathway, pathway_evidence, referral_language, checklist_items, differentiates_from)`
- `SomaticClassifierOutput(somatic_trigger: bool, reason: str)`

### fhir_client.py — interface
- `FHIRService(base_url, client_id, client_secret)` — manages OAuth2 token lifecycle
- Raises `FHIRAuthError` on 401/403; returns `[]` on 404; retries once on timeout
- Async methods: `get_encounters`, `get_conditions`, `get_observations`, `get_medications`, `get_coverage`
- Pagination: follows `Bundle.link[rel=next]` automatically

### FHIR queries (OpenEMR sandbox)
- Encounters: `GET /Patient/{id}/Encounter?date=ge{24mo_ago}&_count=100`
- Conditions: `GET /Patient/{id}/Condition?clinical-status=active,recurrence,relapse&_count=100`
- Observations: `GET /Patient/{id}/Observation?date=ge{24mo_ago}&_count=100`
- Coverage: returns 404 on sandbox → handle gracefully

### Confidence tier logic
- HIGH: ≥3 resource types with ≥1 entry AND most_recent ≤6 months ago
  OR ≥2 types AND any single type ≥5 entries AND most_recent ≤6 months ago
- MODERATE: 1-2 types with data, OR ≥3 types but most_recent 6-24 months ago
- LOW: 0 Condition resources, OR all >24 months old, OR only 1 type has data

### LangChain registration pattern (agent.py)
```python
StructuredTool.from_function(
    func=run_symptom_timeline,
    name="symptom_timeline",
    description="...",
    args_schema=SymptomTimelineInput,
    coroutine=run_symptom_timeline,  # required for async tools
)
```

---

## Critical Files

| File | Action | Story |
|---|---|---|
| `advocate/models.py` | Create | story-054 |
| `advocate/agent.py` | Create | story-054 |
| `advocate/prompts/system.py` | Create | story-055 |
| `advocate/fhir_client.py` | Create | new story |
| `advocate/tools/symptom_timeline.py` | Create | story-048 |
| `advocate/prompts/somatic.py` | Create | story-049 |
| `advocate/tools/specialist_navigator.py` | Create | story-050 |
| `advocate/tools/nppes_taxonomy.py` | Create | story-051 |
| `advocate/main.py` | Create | story-057 |

---

## Pitfalls for Coders

- `AsyncFHIRClient` must be `await`ed — never call sync. Use `asyncio.gather()` for parallel FHIR fetches within a tool.
- All FHIR field access uses `.get()` with defaults — never bare dict access (fields vary by resource completeness)
- OpenEMR sandbox Coverage → 404, not empty bundle; handle as `coverage_available=False`, not crash
- `StructuredTool` async tools require BOTH `func=` (sync stub) AND `coroutine=` (async impl) — omitting `coroutine` silently falls back to sync
- `ConversationBufferWindowMemory` must be instantiated once per session, not per request
- somatic classifier fires on every human turn but must NOT appear in the conversation history (intermediate call, not a chat message)
- `from __future__ import annotations` at top of every module (required per CLAUDE.md)
- `models.py` is shared by all tools — no tool should define models locally; import from `models.py`

---

## Pre-requisite: story-061 ID collision

epics.json has two entries with `id: "story-061"` — one in epic-003 (design system) and one in epic-010 (appointment_brief). The epic-010 entry must be renumbered before running any epic-010 stories. This fix should happen before running the MVP batch.

---

## Verification

After stories run:
1. `cd advocate && python -m pytest tests/ -x --tb=short` — tests should pass for tool input/output schema validation
2. `python -c "from models import SessionState, SymptomTimelineInput; print('models ok')"` — import check
3. `uvicorn main:app --reload` — health endpoint responds at `GET /health`
4. Manual curl test: `POST /chat` with `{"message": "I have a neurology appointment next week", "session_id": "test-1", "patient_id": "synth-001"}` → should invoke agent and return structured response
