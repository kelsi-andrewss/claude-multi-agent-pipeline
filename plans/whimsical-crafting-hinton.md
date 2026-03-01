# Friday Deadline Gap Analysis — Advocate (Updated 2026-02-26)

## Context
Friday is the "Early Submission" deadline for AgentForge. Today is Thursday Feb 26. Significant work landed since the audit (Feb 25).

---

## Current State (verified today)

| Item | Audit Said | Current State |
|---|---|---|
| `dismissal_detector.py` | MISSING | **Still missing** |
| `get_patient_id` in auth.py | MISSING | DONE |
| FHIR credentials | Empty strings | DONE — reads from env vars |
| SSE `/session/{id}/state` endpoint | MISSING | DONE |
| `functions/cleanup_anonymous_users.py` | MISSING | DONE |
| Settings screen | Placeholder stub | DONE — functional |
| `verification/citation.py` key lookup | Bug (wrong keys) | **Still uses "Condition" (capitalized) — bug still present** |
| `verification/confidence.py` | Always returns LOW | Partially fixed — computes tier, but session override may still be an issue |

---

## Remaining Friday Checklist Gaps

### Hard Gaps (still open from REQUIREMENTS.md Friday checklist)

| # | Requirement | Gap |
|---|---|---|
| 1 | `dismissal_pattern_detector` tool | **NOT IMPLEMENTED** — highest priority |
| 2 | 50+ eval test cases (LangSmith evals, not unit tests) | **MISSING** — unit tests exist but no `tests/eval/` LangSmith eval cases |
| 3 | Eval dataset published (GitHub + Hugging Face, GPL v3) | **MISSING** |
| 4 | Prompt injection defense tested (adversarial suite) | **MISSING** |
| 5 | LangSmith: user feedback mechanism | **MISSING** — no feedback endpoint |

### Bug Still Present
- **BUG-1**: `citation.py` line 20 uses `fhir_raw.get(resource_type, [])` where `resource_type` = `"Condition"` (capitalized), but `fhir_raw` keys are `"conditions"` (lowercase plural). All citations will be marked unverified.

---

## Priority Order for Friday

### P0 — Dismissal detector (required tool, missing)
Implement `tools/dismissal_detector.py`:
- Input: `DismissalDetectorInput` (session_id, patient_message, provider_response)
- Output: `DismissalDetectorOutput` (is_dismissal, patterns_detected, severity, recommended_response)
- Implementation: pattern matching on provider response text (similar to specialist_navigator)
- Patterns to detect: symptom minimization ("it's probably just stress"), deflection ("come back if it gets worse"), age/gender bias phrases, gaslighting language
- Also add `DismissalDetectorInput`/`DismissalDetectorOutput` to `models.py`
- Register in `agent.py`

### P1 — Citation bug fix
Fix `verification/citation.py`:
- Add key mapping: `{"Condition": "conditions", "Observation": "observations", "MedicationRequest": "medications", "Encounter": "encounters", "Coverage": "coverage"}`
- Use `fhir_raw.get(_TYPE_TO_KEY.get(resource_type, resource_type.lower() + "s"), [])`

### P2 — Eval framework (biggest time investment)
Create `tests/eval/` directory with:
- `dataset.json`: 50+ test cases (input, expected_tools, expected_output_contains, pass_criteria)
  - 20 happy path: symptom timeline queries, specialist nav, appointment brief, clinical translation, dismissal detection
  - 10 edge: missing FHIR data, empty records, ambiguous symptoms
  - 10 adversarial: prompt injection via message, malicious FHIR field content, system prompt extraction attempts
  - 10 multi-step: multi-turn conversations requiring 2+ tool calls
- `run_evals.py`: LangSmith eval runner using `langsmith` SDK
- Register dataset on LangSmith

### P3 — User feedback endpoint
Add to `main.py`:
- `POST /session/{session_id}/feedback` accepting `{"rating": 1|-1, "comment": str | None}`
- Store to Firestore `sessions/{session_id}/feedback`
- Wire in Flutter: thumbs up/down on agent messages

### P4 — Hugging Face dataset publish
- Export `dataset.json` in HF datasets format
- Publish under GPL v3

---

## Time Estimate (remaining work)

| Task | Est. Time |
|---|---|
| Dismissal detector tool | 1.5 hours |
| Citation bug fix | 15 min |
| Eval dataset (50 cases JSON) | 2 hours |
| LangSmith eval runner script | 1 hour |
| User feedback endpoint | 45 min |
| Hugging Face publish | 30 min |
| **Total** | **~6 hours** |

---

## Key Files to Touch

- **Create**: `tools/dismissal_detector.py`
- **Edit**: `models.py` (add DismissalDetector models), `agent.py` (register tool)
- **Edit**: `verification/citation.py` (fix key mapping, line 20)
- **Create**: `tests/eval/dataset.json`, `tests/eval/run_evals.py`
- **Edit**: `main.py` (add feedback endpoint)
- Flutter (optional P3): add thumbs up/down to `chat_screen.dart`

---

## AgentForge Bounty ($500 add-on)
The bounty requires: new data source + CRUD + BOUNTY.md.
The `provider_finder.py` (NPPES NPI) + `symptom_notes.py` (Firestore CRUD) together satisfy this:
- Data source: NPPES NPI registry (external API)
- CRUD: symptom notes in Firestore
- Still need: `BOUNTY.md` explaining the customer (dismissal-prone patients), data source, features, impact
