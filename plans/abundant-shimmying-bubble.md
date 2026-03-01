# Plan: Advocate Eval Test Suite for Demo Resubmission

## Context

Demo feedback: the reviewer couldn't see which tools were called, eval tests weren't clearly labeled or runnable, and there was a disconnect between the demo and project requirements. The fix is a comprehensive pytest eval suite that can be executed during the demo recording with clear, visible labels for each test scenario.

## Story

- **story-119** under **epic-007** (Evaluation and Dataset)
- Agent: architect, Model: sonnet
- 5 write targets: `advocate/tests/__init__.py`, `conftest.py`, `test_eval_verification.py`, `test_eval_tools.py`, `test_eval_agent.py`

## Files to Create

### 1. `advocate/tests/__init__.py` — empty

### 2. `advocate/tests/conftest.py` — shared fixtures

**FHIR bundles (3 fixtures):**
- `fhir_bundle_rich` — uppercase keys (`Condition`, `Observation`, `MedicationRequest`, `Encounter`) with recent dates (2025), multiple resource types. Used by verification layers.
- `fhir_bundle_empty` — `{}`. Triggers LOW confidence.
- `fhir_bundle_minimal_old` — one Condition dated 2022. Triggers LOW (>24mo).
- `fhir_raw_rich` — lowercase-plural keys (`conditions`, `observations`, `medications`, `patients`) for appointment_brief helpers.

**SessionState fixtures (6):**
- `session_default` — patient_id, entry_point="appointment_scheduled"
- `session_low_confidence` — entry_point="no_appointment", confidence_tier="LOW"
- `session_somatic_active` — somatic_mode_active=True, patient_language_buffer filled
- `session_escalation` — escalation_flags=["flag-1", "flag-2"]
- `session_with_specialist` — specialist_type="neurology", stages_completed=[]
- `session_insurance_done` — specialist_type="neurology", stages_completed=["insurance"]

### 3. `advocate/tests/test_eval_verification.py` — ~25 tests

**Layer 1: Citation (4 tests)**
- Valid source tag verified against FHIR (`[Source: Condition/cond-001]`)
- Invalid tag ID counted as unverified
- Unsourced clinical number gets `(patient-reported)` annotation
- Sourced number near citation tag left unchanged

**Layer 2: Hallucination Guard (5 tests)**
- Fabricated medication name → "not documented"
- Fabricated date → "not documented"
- Verified value in FHIR corpus preserved
- Inference phrase "you have" → "records include"
- Corpus lookup is case-insensitive (unit test `_value_in_corpus`)

**Layer 3: Boundary Check (5 tests)**
- "You have been diagnosed" → "records include a documented diagnosis"
- "You should take" → "your provider has prescribed"
- Disclaimer footer appended
- Footer not duplicated on second pass
- Clean text has zero violations

**Layer 4: Confidence Scoring (5 tests)**
- Empty FHIR → LOW (force recompute by clearing session confidence_tier)
- Old records (>24mo) → LOW
- Rich recent FHIR → HIGH
- Evidence summary format check
- Summary appended to output text

**Layer 5: Escalation (4 tests)**
- 2 escalation flags → triggered
- MODERATE confidence → not triggered
- LOW + high-stakes appointment type → triggered (use mock object with `appointment_type` attr since SessionState blocks extra fields)
- LOW + non-high-stakes → not triggered

**Pipeline Integration (2 tests)**
- All 5 layers in `layers_applied`
- Diagnostic phrase caught end-to-end

### 4. `advocate/tests/test_eval_tools.py` — ~30 tests

**Specialist Navigator (8 tests)** — import `run_specialist_navigator` (async), run via `asyncio.get_event_loop().run_until_complete()`:
- "headache migraine" → neurology
- "swollen joints" → rheumatology
- "vestibular vertigo" → neurotology
- "depression" → psychiatry
- Gibberish → defaults to neurology
- "first presentation" → PCP_first pathway
- "known neurological condition" → direct_to_specialist pathway
- Checklist has >= 3 items including symptom item

**Symptom Timeline Helpers (6 tests)** — import `_extract_date`, `_extract_display`, `_compute_confidence_tier`, `_detect_gaps`:
- effectiveDateTime extracted
- onsetDateTime fallback
- period.start fallback
- Empty resource → "unknown"
- Condition display from text vs coding fallback
- HIGH confidence tier (3+ types, recent date)
- LOW confidence tier (no date)
- Gap detection: missing conditions, >1yr gap between events

**Appointment Brief Helpers (8 tests)** — import `_extract_patient_name`, `_extract_dob`, `_resource_display`, `_select_resource_types`, `_compute_evidence_summary`, `_extract_fhir_citations`:
- Patient name extraction + empty fallback
- DOB extraction + missing fallback
- Condition resource_display includes [Source:] tag
- GP resource types exclude DocumentReference
- Neurology specialist adds DocumentReference
- Rheumatology adds Procedure + DiagnosticReport
- Evidence summary format + empty case
- Citation extractor deduplicates

**Insurance Helpers (8 tests)** — import `_requires_prior_auth`, `_infer_requires_referral`, `_build_scheduler_script`, `_build_checklist_item`:
- mental_health → prior auth required
- oncologist → prior auth required
- standard specialist → no prior auth
- HMO → referral required; PPO → not required; no coverage → None
- Scheduler script with/without coverage
- Checklist item with/without coverage

### 5. `advocate/tests/test_eval_agent.py` — ~20 tests

**Diagnosis Boundary (5 tests)** — import `AdvocateAgent._check_diagnosis_boundary`:
- "you have" flagged
- "you should take" flagged
- "this indicates" flagged
- Clean text not flagged
- Case-insensitive check

**Regen Intent + Affirmative (6 tests)** — import `_message_has_regen_intent`, `_message_is_affirmative`:
- "regenerate" → detected
- "update" → detected
- Unrelated message → not detected
- "yes" → affirmative; "sure, go ahead" → affirmative; "no" → not affirmative

**Auto-Fire Insurance (4 tests)** — import `_should_auto_fire_insurance`:
- Specialist set + insurance not done → triggers
- Insurance already completed → no trigger
- No specialist type → no trigger
- specialist_type="unknown" → no trigger

**ClarificationSubFlow (5 tests)** — import `ClarificationSubFlow`:
- LOW + no_appointment → should_clarify=True
- appointment_scheduled entry → should_clarify=False
- Exhausted after MAX_CLARIFICATION_TURNS (3)
- Not exhausted at turn 2
- MODERATE confidence → should_clarify=False

**SomaticClassifierMiddleware (2 tests)** — import from `advocate.prompts.somatic`:
- No LLM → somatic_trigger=False, reason="no classifier configured"
- process_turn with no LLM → somatic_mode_active stays False

## Critical Implementation Notes

1. **SessionState blocks extra attributes** (Pydantic V2 default `extra='ignore'`). For escalation tests needing `appointment_type`, use a `types.SimpleNamespace` mock with the required fields.

2. **pytest-asyncio 1.3.0 is installed** but version is old. Use manual `asyncio.get_event_loop().run_until_complete()` pattern instead of `@pytest.mark.asyncio` for reliability.

3. **LangSmith `@traceable`** no-ops when env vars aren't set — no mocking needed.

4. **FHIR key naming**: verification layers use uppercase (`"Condition"`), appointment_brief helpers use lowercase plural (`"conditions"`). Separate fixture families handle this.

5. **confidence_tier recompute**: `run_confidence_scoring` returns session's existing tier if non-empty. Tests that need to verify computed tiers must clear it: `session.confidence_tier = ""`.

6. **Demo output**: every test starts with `print("\n[EVAL: Category > Layer > Scenario]")`. Run with `python -m pytest tests/ -v -s` from `advocate/` dir. The `-s` flag shows print output in terminal.

## Run Command

```bash
cd advocate && source venv/bin/activate && PYTHONPATH=.. python -m pytest tests/ -v -s --tb=short
```

## Verification

After implementation:
1. Run the full suite — all ~68 tests should pass in <5s
2. Verify print labels appear in terminal output (requires `-s` flag)
3. Check that no test makes network calls (no FHIR, no LLM, no Firebase)
4. Verify imports resolve correctly with `PYTHONPATH=..`
