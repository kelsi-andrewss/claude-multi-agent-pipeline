# Plan: Advocate Pre-Search Gap-Fill Round 3

## Context

Two prior rounds of gap-filling have been applied to `advocate_presearch_v10.md`. A third audit (explore agent, full file read) found 23 remaining gaps — 6 blocking, 9 high, 8 low. These must be resolved before coding starts. All changes are documentation only: one markdown file, no source code, no builds.

---

## File to Modify

`project_requirements_and _research/advocate_presearch_v10.md` (~1143 lines)

All other files are untouched.

---

## Gaps to Fix

### Blocking (6)

**B1 — FHIR_BASE_URL default value never specified**
- Location: Section 16.6
- Fix: Add to Section 16.6 before the query list: `FHIR_BASE_URL=https://demo.openemr.io/apis/default/fhir/` is the sprint default. Set in `.env` and load via `python-dotenv`.

**B2 — OAuth2 credentials and setup flow not documented**
- Location: Section 16.10 (sprint architecture) and Section 16.6
- Fix: Add a "16.0.5 — OAuth2 Sprint Setup" subsection with: (1) Client credentials flow for sandbox (not PKCE — PKCE is for production with real users); (2) How to obtain/register a client on the OpenEMR sandbox — link to `https://demo.openemr.io/oauth2/default/registration`; (3) Env vars: `OPENEMR_CLIENT_ID`, `OPENEMR_CLIENT_SECRET`, `OPENEMR_BASE_URL`, `FHIR_BASE_URL`; (4) Token exchange: `POST /oauth2/default/token` with `grant_type=client_credentials`; (5) FHIRpy usage: `AsyncFHIRClient(url=FHIR_BASE_URL, authorization=f"Bearer {token}")`.

**B3 — `fhir_raw` population path never specified**
- Location: Section 16.5, `AppointmentBriefInput`
- Fix: Add after `fhir_raw` field: "Populated by the agent: after `symptom_timeline` runs, the tool function stores raw FHIR bundle responses in `session_state.fhir_resources_retrieved` as `{resource_type: [list of raw FHIR JSON dicts]}`. The agent passes `session_state.fhir_resources_retrieved` as `fhir_raw` when calling `appointment_brief_generator`." Also add `fhir_raw: dict[str, list] = {}` as the corrected type annotation.

**B4 — `astream()` method missing from `SomaticClassifierMiddleware`**
- Location: Section 16.4
- Fix: Append `astream()` method to the class skeleton:
```python
async def astream(self, patient_message: str, session_state: SessionState):
    """Async streaming wrapper. Runs classifier, then streams executor.astream_events()."""
    trigger = self._classify(patient_message)
    if trigger["somatic_trigger"]:
        session_state.somatic_mode_active = True
        session_state.patient_language_buffer.append(patient_message)
    augmented_input = self._build_input(patient_message, session_state)
    async for event in self.executor.astream_events(augmented_input, version="v2"):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"].content
            if chunk:
                yield chunk
```

**B5 — `SessionAwareMemory` missing `k=10` in `__init__`**
- Location: Section 16.2
- Fix: Replace the class definition with one that passes `k` to super:
```python
class SessionAwareMemory(ConversationBufferWindowMemory):
    # SessionState is defined in Section 16.5 — ensure it is imported before this class
    session_state: SessionState = Field(default_factory=SessionState)

    def __init__(self, k: int = 10, **kwargs):
        super().__init__(k=k, **kwargs)

    def load_memory_variables(self, inputs: dict) -> dict:
        base = super().load_memory_variables(inputs)
        session_msg = SystemMessage(content=f"SESSION STATE:\n{self.session_state.model_dump_json(indent=2)}")
        base["history"] = [session_msg] + base.get("history", [])
        return base
```

**B6 — Tool registration with LangChain never specced**
- Location: Section 16.5
- Fix: Add "16.5.1 — LangChain Tool Registration" subsection with example:
```python
from langchain.tools import StructuredTool

symptom_timeline_tool = StructuredTool.from_function(
    func=run_symptom_timeline,          # the actual Python function
    name="symptom_timeline",
    description="Pull patient's symptom and encounter history from FHIR. "
                "Call this first when patient has no appointment scheduled. "
                "Inputs: patient_id (str), date_from (optional ISO date). "
                "Returns chronological timeline with confidence tier.",
    args_schema=SymptomTimelineInput,
)
# Register all tools in a list passed to AgentExecutor:
# tools = [symptom_timeline_tool, specialist_navigator_tool, ...]
# executor = AgentExecutor(agent=agent, tools=tools, memory=memory, verbose=True)
```
Note: tool descriptions are what the LLM reads to decide which tool to call. They must be concise, action-oriented, and describe inputs explicitly. Optional fields with defaults do not need to be passed by the LLM.

---

### High (9)

**H1 — `hallucination_guard()` caller and signature unclear**
- Fix: Add to Section 16.7 Layer 2: "Called inside `appointment_brief_generator` after brief is generated, before returning output. Signature: `def hallucination_guard(output_text: str, fhir_raw: dict[str, list]) -> tuple[str, list[str]]` — returns `(cleaned_text, replacements_log)`. If `fhir_raw` is empty, returns output with ALL numbers/dates/meds replaced with 'not documented'. Log replacements to LangSmith via `langsmith.trace()`."

**H2 — `session_id` generation never specced**
- Fix: Add to Section 16.2: "Session IDs are UUID4 strings generated at Streamlit app load: `session_id = str(uuid.uuid4())`, stored in `st.session_state['session_id']`. Passed to `DismissalInput.session_id` on each `dismissal_pattern_detector` call."

**H3 — Layer 5 escalation trigger ownership not pinned to a function**
- Fix: Add to Section 16.7 Layer 5: "Both checks run inside `appointment_brief_generator`, after all other verification layers. `HIGHSTAKES_SPECIALTIES = ['oncology', 'neurology', 'cardiology', 'surgery', 'psychiatry']`. Trigger 2 only fires if `dismissal_pattern_detector` was called this session AND returned `second_opinion_flag=True` — check `session_state.escalation_flags` for this. If Tool 5 is not yet built, skip Trigger 2 and leave a TODO comment."

**H4 — `clinical_language_translator` MVP scope ambiguous**
- Fix: Add to Section 5 Tool 4 description: "MVP scope: `patient_to_clinical` direction only. Friday stretch: `clinical_to_patient` direction. During Hours 14–16, implement `patient_to_clinical` first; add reverse direction only if time permits."

**H5 — Somatic re-trigger prevention logic is unimplementable as written**
- Fix: Replace "3+ consecutive turns" spec in Section 16.4 with: "Mode resets to False on the FIRST patient turn where the classifier returns `somatic_trigger: false`. No 3-turn requirement — reset immediately. This is simpler and avoids a turn counter."

**H6 — `st.session_state` ↔ `SessionState` sync pattern missing**
- Fix: Add to Section 16.2 after the `SessionAwareMemory` block: "Streamlit sync pattern: Initialize on app load: `if '_advocate_state' not in st.session_state: st.session_state['_advocate_state'] = SessionState(patient_id='synth-001')`. Pass to middleware: `middleware.invoke(user_input, st.session_state['_advocate_state'])`. After each invoke, `st.session_state['_advocate_state']` is mutated in place by middleware (Pydantic model is passed by reference — no explicit sync needed)."

**H7 — Confidence tier logic AND/OR ambiguity**
- Fix: Replace the confidence tier comment in Section 16.5 with:
```
# HIGH:     (>=3 resource types with >=1 entry each)
#           AND (most recent Encounter.period.end or Observation.effectiveDateTime <= 6 months ago)
# MODERATE: (1-2 resource types with data)
#           OR (>=3 types but most recent resource is 6-24 months ago)
# LOW:      (0 Condition resources)
#           OR (all resources >24 months old)
#           OR (only 1 resource type has data)
# If ambiguous, use the lower tier.
```

**H8 — Patient's Own Words divergence detection not specced for implementation**
- Fix: Add to Section 16.5 `AppointmentBriefOutput` block: "Divergence detection (MVP): inside `appointment_brief_generator`, after pulling FHIR Conditions, check if `patient_language_buffer` is non-empty AND no Condition was documented within 24 months matching the symptom domain. Use an LLM call (temp=0): 'Does the patient description [{patient_language}] correspond to any of these documented conditions: [{condition_list}]? Return JSON: {match: bool}'. If `match: false` OR `somatic_mode_active == True` → include `patients_own_words` in output."

**H9 — NPPES `clinical-status=remission` is invalid FHIR R4**
- Fix: In Section 16.6, change the Condition query to: `GET /Patient/{id}/Condition?clinical-status=active,recurrence,relapse&_count=100` (remove `remission`). Add note: "FHIR R4 Condition.clinicalStatus valid values: active, recurrence, relapse, inactive, remission, resolved — but OpenEMR sandbox only indexes the first three reliably. Filter `inactive`/`remission`/`resolved` in Python if needed."

---

### Low (8)

**L1 — NPPES rate limits**: Add to Section 16.5 `provider_finder` block: "NPPES rate limit: ~100 req/min per IP. Cache results per specialty+zip for the demo session. `@functools.lru_cache(maxsize=32)` on the lookup function is sufficient."

**L2 — Demo .docx file references**: Add note in Section 13 deliverables: "Demo scenario files are created during Hours 20–22. They are referenced in Section 10 but do not exist at sprint start."

**L3 — Risk 7 cross-reference fix**: Change "adversarial eval category" in Risk 7 to "the 'Adversarial' category in Section 9."

**L4 — Cost analysis timing**: Add to Section 16.12 Hour 22–24: "Measure actual token counts from LangSmith traces. Update AI Cost Analysis estimate in architecture doc."

**L5 — FHIRClient abstraction skeleton**: Add "16.5.2 — FHIRClient Abstraction" with skeleton class showing method signatures for `get_patient_encounters`, `get_conditions`, `get_observations`, `get_medications`. Methods raise `FHIRAuthError` on 401/403, return `[]` on 404, retry once on timeout.

**L6 — Layer 5 stub note in 16.12**: Add to Section 16.12 Hour 18–20: "If Tool 5 is not complete, skip escalation Trigger 2 and leave a TODO."

**L7 — Somatic classifier LLM model spec**: Add to Section 16.4: "Classifier uses `claude-haiku-4-5-20251001` (not Sonnet) to minimize latency and cost. ~100 input + ~20 output tokens per turn. Cost ~$0.0001/turn."

**L8 — TimelineEvent import clarification**: Add note at top of Section 16.5 shared models block: "All models in this section live in `models.py` at the project root. Import pattern: `from models import SessionState, TimelineEvent, ...`"

---

## Implementation Approach

Single `quick-fixer` agent, background, isolated worktree. Read file in chunks (150 lines at a time). Apply all 23 fixes as targeted insertions/replacements. Do not reformat surrounding text. Do not modify Section 15 (Change Log).

Priority order: B1→B6 first, then H1→H9, then L1→L8.

---

## Verification

After implementation, grep for:
- `FHIR_BASE_URL=` — confirms B1
- `oauth2/default/registration` — confirms B2
- `fhir_resources_retrieved` as `fhir_raw` source — confirms B3
- `astream_events` in SomaticClassifierMiddleware — confirms B4
- `def __init__(self, k: int = 10` — confirms B5
- `StructuredTool.from_function` — confirms B6
- `tuple[str, list[str]]` in hallucination_guard — confirms H1
- `uuid.uuid4()` — confirms H2
- `HIGHSTAKES_SPECIALTIES` — confirms H3
