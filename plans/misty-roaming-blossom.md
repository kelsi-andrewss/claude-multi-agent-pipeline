# Plan: MVP Epics Run Order

## Context

The Advocate codebase is greenfield — zero Python source files exist yet. The four MVP epics to execute are:

- **epic-011** — Clinical Language Translator (story-047)
- **epic-010** — Brief Generator + Insurance Check (stories 078, 062, 063, 064, 065)
- **epic-012** — Verification Pipeline (stories 066, 067, 068, 069, 070)
- **epic-016** — Flutter Frontend (stories 071–075)

These run AFTER the existing closed epics have established foundation work (epics 004, 005, 009, 013 are all closed — models.py, fhir_client.py, symptom_timeline, specialist_navigator, session memory, error states all exist conceptually but not on disk since the codebase is greenfield). This plan treats all files as net-new.

**Note:** Since nothing is built yet, the correct first step is actually to run the foundational stories (core models, FHIR client, seed data, agent scaffold) before the MVP epics. The stories below assume that foundation exists — see Prerequisite block.

---

## Prerequisite Check (Foundation — not in these 4 epics)

Before any MVP epic story can run, the following must exist:
- `advocate/models.py` — all Pydantic V2 models including `SessionState`, `SymptomTimelineOutput`, `SpecialistNavOutput`
- `advocate/fhir_client.py` — `FHIRService` with `AsyncFHIRClient` wrapper, pagination, 404 handling
- `advocate/agent.py` — ReAct agent scaffold with tool registry and somatic classifier hook
- `advocate/tools/symptom_timeline.py` — Tool 1 (story-048, closed)
- `advocate/tools/specialist_navigator.py` — Tool 2 (story-050, closed)

**Action required before running MVP epics:** Confirm whether the "closed" stories (048, 049, 050, 051, 054–057) have actually produced committed code on disk, or whether they were planned but never executed. If greenfield, those stories must run first.

---

## Story Run Order

### Phase A: Clinical Language Translator (epic-011)

**Must run first** — story-047 wires `patient_language_buffer` into the somatic pipeline in `agent.py`. The brief generator (epic-010) depends on `clinical_descriptor` being set in `session_state` before generating Patient's Own Words.

#### story-047 — Wire clinical_language_translator into somatic pipeline
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/tools/clinical_translator.py`, `advocate/agent.py`
- **Read:** `advocate/models.py`, `advocate/prompts/somatic.py`
- **Plan:**
  1. Create `TranslatorInput(direction, text, patient_language_buffer)` and `TranslatorOutput(translated_text, confidence, caveat, source_phrases)` in models.py
  2. Implement `clinical_language_translator` tool: `patient_to_clinical` direction (sprint scope only), outputs framed as "suggested clinical language — verify with provider"
  3. Wire into agent.py somatic pipeline: after classifier fires `somatic_trigger=True`, pass `session_state.patient_language_buffer` as tool input; store result in `session_state.clinical_descriptor`
  4. Guard: never translate `patient_language` twice — check `session_state.clinical_descriptor` before invoking tool
- **Pitfalls:**
  - Somatic classifier is synchronous (temp=0 Gemini Flash), not async — don't make it a LangChain tool
  - `patient_language_buffer` is `list[str]` — join with `" "` before passing to translator
  - Never overwrite `clinical_descriptor` once set; skip tool call if already populated

---

### Phase B: Brief Generator + Insurance Check (epic-010)

Run after Phase A. Stories 078 and 064 are independent; run in parallel. Stories 062, 063, 065 depend on their predecessors.

#### story-078 — appointment_brief_generator core dual output (parallel with story-064)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/tools/appointment_brief.py`, `advocate/models.py`
- **Read:** `advocate/fhir_client.py`, `advocate/tools/symptom_timeline.py`, `advocate/prompts/system.py`
- **Plan:**
  1. `AppointmentBriefInput(patient_id, appointment_type, specialist_type, session_state, fhir_raw)` and `AppointmentBriefOutput(patient_prep_sheet, clinical_brief, patients_own_words, fhir_citations, confidence_tier, evidence_summary)`
  2. Fetch FHIR resources appropriate to `appointment_type` (imaging for ortho, labs for rheum, meds for neuro)
  3. Generate clinical brief (doctor-facing markdown) and patient prep sheet (patient-facing markdown)
  4. Tag each clinical claim: `[Source: ResourceType/id]`
  5. Appointment-type-aware formatting: rheumatologist ≠ neurologist brief
  6. `patients_own_words` = None in this story (added in story-062)
- **Pitfalls:**
  - `fhir_raw` must be passed through from agent — don't re-fetch inside the tool
  - `evidence_summary` derives from `confidence_tier` already set in `session_state` by `symptom_timeline`
  - FHIR field access always via `.get()` with defaults — never bare dict access

#### story-064 — insurance_coverage_check tool (parallel with story-078)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/tools/insurance_coverage.py`, `advocate/models.py`
- **Read:** `advocate/fhir_client.py`
- **Plan:**
  1. `InsuranceCoverageInput(patient_id, specialist_type, appointment_type)` and `InsuranceCoverageOutput(insurer_name, plan_type, requires_referral, prior_auth_likely, scheduler_script, checklist_item, coverage_available)`
  2. Query `GET /Patient/{id}/Coverage?status=active`; on 404 → `coverage_available=False`
  3. `prior_auth_likely` heuristic: `True` for surgery, oncology, mental_health
  4. Generate `scheduler_script` and `checklist_item` from coverage data or generic fallback
- **Pitfalls:**
  - OpenEMR sandbox returns 404 for Coverage — fallback path must be tested as the primary path
  - `requires_referral` = `None` (unknown) when `coverage_available=False`, not `False`

#### story-062 — Patient's Own Words conditional output (depends on story-078)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/tools/appointment_brief.py`
- **Read:** `advocate/models.py`, `advocate/tools/clinical_translator.py`
- **Plan:**
  1. After FHIR pull, check if `patient_language_buffer` is non-empty AND no matching FHIR Condition/Observation within 24 months (temp=0 LLM match check: `{match: bool}`)
  2. If `match=False` OR `somatic_mode_active=True` → generate third output section
  3. Prose version: short paragraph in patient's register, no clinical terms
  4. Bullet summary: 3–5 items same content for quick scanning
  5. Takes `session_state.clinical_descriptor` (from translator) as input — do not re-translate
- **Pitfalls:**
  - "No FHIR match within 24 months" is a separate temp=0 LLM call, not a string search
  - Either condition alone triggers the section — not AND
  - `patients_own_words` field is `Optional[str]`; prose + bullets go in one markdown string

#### story-063 — brief regeneration flow (depends on story-078)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/tools/appointment_brief.py`, `advocate/agent.py`
- **Read:** `advocate/models.py`
- **Plan:**
  1. In agent.py: after tool call, check `session_state.stages_completed` — if "prep" already in list, prompt user "Would you like me to update your brief?"
  2. On confirmation: re-invoke `appointment_brief_generator` with updated `session_state`; no caching of prior brief
  3. No version history — only current brief is stored
- **Pitfalls:**
  - Do not auto-regenerate without user confirmation
  - `stages_completed` is a `list[str]` — append "prep" after first brief generation

#### story-065 — insurance_coverage auto-fire trigger (depends on story-064)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/agent.py`
- **Read:** `advocate/tools/insurance_coverage.py`, `advocate/models.py`
- **Plan:**
  1. In agent.py tool post-processing: after `specialist_navigator` sets `session_state.specialist_type`, auto-invoke `insurance_coverage_check` if `specialist_type` is not None/unknown
  2. Skip if `specialist_type` is unknown or empty string
- **Pitfalls:**
  - Auto-fire in agent orchestration, not inside the specialist_navigator tool itself
  - Don't block the agent response waiting for insurance — fire async, append result to next turn context

---

### Phase C: Verification Pipeline (epic-012)

Stories 066–069 are independent (different files, different layers). Run all four in parallel. Story-070 depends on all four.

#### story-066 — FHIR Citation layer (parallel with 067, 068, 069)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/verification/citation.py`, `advocate/models.py`
- **Plan:**
  1. Parse output text for clinical claims; require `[Source: ResourceType/id]` tag
  2. Claims without tag → rewrite to "patient-reported" label or strip
  3. Input: `{text: str, fhir_raw: dict}` → output: `{verified_text: str, citations: list[str]}`

#### story-067 — Hallucination Guard layer (parallel with 066, 068, 069)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/verification/hallucination.py`, `advocate/models.py`
- **Plan:**
  1. 4 categories: numbers/dates, medication names/dosages, lab values, clinical inferences
  2. Cross-check each against `fhir_raw` dict before delivery
  3. Unverified values → "not documented"; clinical inferences → uncertainty language rewrites
  4. Log all replacements to LangSmith trace

#### story-068 — Clinical Boundary Check layer (parallel with 066, 067, 069)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/verification/boundary.py`, `advocate/models.py`
- **Plan:**
  1. Regex pre-filter: "you have", "this means", "you should take"
  2. Confirmed violations: temp=0 LLM confirmation call → rewrite or strip
  3. Append legal framing footer to every output
  4. System prompt extraction attempts: handled by base agent instructions, not this layer

#### story-069 — Evidence Confidence Scoring layer (parallel with 066, 067, 068)
- **Agent:** quick-fixer | **Model:** sonnet
- **Write:** `advocate/verification/confidence.py`, `advocate/models.py`
- **Plan:**
  1. Accept `confidence_tier` from `session_state` (set by `symptom_timeline`)
  2. Append `evidence_summary` string to every output: "This brief is based on N documented records spanning X months"
  3. Tier thresholds: HIGH (≥3 resource types, recent ≤6mo OR ≥2 types with ≥5 entries), MODERATE (1-2 types or 6-24mo old), LOW (0 Conditions or all >24mo)

#### story-070 — Wire all 5 layers into pipeline (depends on 066, 067, 068, 069, 060)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/verification/pipeline.py`, `advocate/agent.py`
- **Read:** all four verification layer files
- **Plan:**
  1. `run_verification_pipeline(text, fhir_raw, session_state) -> VerificationResult`
  2. Chains: citation → hallucination → boundary → confidence → escalation (Layer 5)
  3. Layer 5 Trigger 1: LOW confidence + high-stakes appointment type → append warning
  4. Layer 5 Trigger 2: `dismissal_pattern_detector.second_opinion_flag` check (story-060 provides this)
  5. Wire into `agent.py`: call pipeline on every agent response before delivery
- **Pitfalls:**
  - story-060 (`advocate/verification/escalation.py`) is a dependency — verify it exists before running story-070
  - Pipeline must handle partial failures — if one layer errors, pass text through unmodified with warning logged

---

### Phase D: Flutter Frontend (epic-016)

Stories 071 is the scaffold — must run first. Stories 072, 073, 074 all depend on 071 and can run in parallel. Story-075 depends on 071 + 072.

#### story-071 — Flutter scaffold (blocks all others in epic-016)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/flutter/pubspec.yaml`, `advocate/flutter/lib/main.dart`, `advocate/flutter/lib/app.dart`, `advocate/flutter/lib/navigation/router.dart`, `advocate/flutter/lib/features/auth/sign_in_screen.dart`, `advocate/flutter/lib/services/auth_service.dart`, `advocate/flutter/lib/theme/advocate_theme.dart`
- **Plan:**
  1. Flutter 3.x project with Riverpod, go_router, firebase_core, firebase_auth, shared_preferences, flutter_secure_storage
  2. `AdvocateTheme` with 5 patient variants (sage/terracotta/lavender/sand/rose) via `ColorScheme.fromSeed`, plus provider theme (blue seed)
  3. Sign-in screen: Google OAuth, email/password, "Continue Anonymously", "Demo Experience" buttons
  4. go_router with auth guard: unauthenticated → `/sign-in`, authenticated → `/chat`
  5. `AuthService` wrapping Firebase Auth for all four flows
  6. Dev mode badge visible in debug builds only (`kDebugMode`)
- **M3 spec reference:** seed colors and theme structure defined in `advocate-m3-design-spec.md`

#### story-072 — Chat UI (depends on story-071, blocks story-075)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/flutter/lib/features/chat/chat_screen.dart`, `advocate/flutter/lib/features/chat/chat_provider.dart`, `advocate/flutter/lib/shared/widgets/message_bubble.dart`, `advocate/flutter/lib/shared/models/message.dart`
- **Plan:**
  1. SSE stream consumer for agent response tokens (stub endpoint for MVP — real wire in story-075)
  2. Message bubbles: patient right-aligned, agent left-aligned, markdown rendering
  3. Tool-call loading indicator while agent executes
  4. Thumbs up/down feedback widget on each agent message; POST stub to LangSmith feedback API
  5. Bottom nav: Chat | Timeline | Prep | Brief | Settings (5 tabs per M3 spec)

#### story-073 — Stage progress indicator (depends on story-071)
- **Agent:** quick-fixer | **Model:** haiku
- **Write:** `advocate/flutter/lib/shared/widgets/stage_indicator.dart`, `advocate/flutter/lib/shared/models/journey_stage.dart`
- **Plan:**
  1. 5 stages: Recognition | Navigation | Provider Search | Setup Checklist | Appointment Prep
  2. Horizontal stepper above active content area
  3. `JourneyStage` enum with label + icon
  4. Active/completed/pending visual states using `ColorScheme` roles (no hardcoded colors)

#### story-074 — Clinical brief viewer (depends on story-071)
- **Agent:** quick-fixer | **Model:** sonnet
- **Write:** `advocate/flutter/lib/features/brief/brief_screen.dart`, `advocate/flutter/lib/shared/models/clinical_brief.dart`
- **Plan:**
  1. Tabbed layout: Clinical Brief | Patient Prep | Your Own Words (tab hidden if `patients_own_words == null`)
  2. Copy-to-clipboard button for each section
  3. `ClinicalBriefModel(clinical_brief, patient_prep_sheet, patients_own_words, confidence_tier, evidence_summary)`
  4. Evidence summary displayed as footer chip with tier color

#### story-075 — Wire Flutter to FastAPI (depends on story-071 + story-072)
- **Agent:** architect | **Model:** sonnet
- **Write:** `advocate/flutter/lib/services/advocate_api.dart`, `advocate/flutter/lib/services/local_storage_service.dart`, `advocate/flutter/lib/shared/models/session.dart`
- **Plan:**
  1. `AdvocateApiService`: `POST /chat` with Firebase ID token in `Authorization: Bearer` header
  2. `SSE` stream consumer for real-time response tokens
  3. `LocalStorageService`: `session_patient_override` in shared_preferences (demo mode), auth tokens in flutter_secure_storage
  4. `SessionModel(session_id, patient_id, stages_completed, current_tool)`
  5. 401 → trigger Firebase re-auth; 500 → show error snackbar with retry
- **Pitfalls:**
  - Never trust client-supplied `patient_id` — backend resolves from Firebase UID; client only sends message + session_id
  - Capture all Riverpod state before async gaps; never read provider after `await`

---

## Parallel Execution Map

```
Phase A (epic-011):
  story-047

Phase B (epic-010):
  [story-078, story-064] parallel
    → story-062 (depends 078)
    → story-063 (depends 078)
    → story-065 (depends 064)

Phase C (epic-012):
  [story-066, story-067, story-068, story-069] parallel
    → story-070 (depends all four + story-060)

Phase D (epic-016):
  story-071
    → [story-072, story-073, story-074] parallel
        → story-075 (depends 071 + 072)
```

Phase B, C, D can all run in parallel with each other (no shared write-targets). Phase A must complete before epic-011 story-047 can be considered unblocked.

---

## Prerequisite Verification (Run Before Launching Stories)

Before running any story above, verify these files exist on disk (they should be from closed stories):
- `advocate/models.py`
- `advocate/fhir_client.py`
- `advocate/agent.py`
- `advocate/tools/symptom_timeline.py`
- `advocate/tools/specialist_navigator.py`
- `advocate/verification/escalation.py` (needed for story-070 Layer 5)
- `advocate/tools/dismissal_detector.py` (needed for story-070 Layer 5 Trigger 2)

If any are missing, those foundation stories must run first before launching the MVP epic stories.

---

## Critical File Paths

- Spec: `advocate/CLAUDE.md`, `advocate/REQUIREMENTS.md`, `advocate/ROADMAP.md`
- Presearch: `project_requirements_and _research/advocate_presearch_v10.md`
- M3 design: `project_requirements_and _research/advocate-m3-design-spec.md`
- All tool write targets listed per story above

---

## Verification

After all stories merge:
1. `uvicorn advocate.main:app --reload` starts without import errors
2. `POST /chat` with Synthea patient ID returns a JSON response with `clinical_brief` and `patient_prep_sheet`
3. Verification pipeline runs and returns `confidence_tier` on every response
4. Flutter web build (`flutter build web`) compiles without errors
5. Sign-in screen loads in browser; anonymous auth creates a Firebase user
6. Chat screen sends a message and receives a streamed agent response
7. LangSmith dashboard shows traces for the request including tool calls and verification layer calls
