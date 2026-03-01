# Plan: Advocate ROADMAP.md

## Context

Advocate is a conversational health navigation agent built on OpenEMR's FHIR R4 API. The codebase currently has only documentation and an `.env.example` — zero implementation code. This ROADMAP.md will be the single authoritative guide for the sprint (Feb 24 → Sunday), covering:

- Manual setup steps the developer must do themselves (platform accounts, OAuth registration, tokens)
- What to acquire (API keys, service account credentials, secrets)
- What to implement (in order, by phase)
- Links to relevant consoles and docs

The roadmap must use wording that stays consistent with the presearch doc and requirements doc even as implementation decisions continue to evolve (e.g., Railway vs. Cloud Run, Apify vs. Zembra for provider data).

---

## Output File

`project_requirements_and _research/ROADMAP.md`

---

## Structure

Hybrid: phases at top level, sub-sections by domain within each phase.

**Phases:**
- Phase 0 — Prerequisites (manual setup, credentials, account creation)
- Phase 1 — MVP Core (24hr gate: agent + 3 tools + 1 verification layer + FastAPI + seed patient + Railway deploy)
- Phase 2 — Friday Gate (16hr mark: 5 tools + all 5 verification layers + Flutter + 50+ evals)
- Phase 3 — Sunday Final (provider finder stretch + demo polish + collateral)

---

## Key Content Per Section

### Phase 0 — Prerequisites

**Manual steps (developer must do these by hand):**

1. **OpenEMR OAuth2 client registration**
   - URL: https://demo.openemr.io or local Docker (see CLAUDE.md docker section)
   - Path: Admin → API → API Clients → Register New Client
   - Acquire: `OPENEMR_CLIENT_ID`, `OPENEMR_CLIENT_SECRET`
   - Note: scope required — list FHIR resource types from presearch

2. **Synthea synthetic patient generation**
   - Install Synthea, generate 1 patient with chronic conditions
   - Script: `advocate/seed_patient.py` (to be written in Phase 1)
   - Manually confirm patient_id after seeding

3. **Google AI Studio — Gemini API key** (already done)
   - Verify `gemini-2.0-flash` is accessible on the key
   - URL: https://aistudio.google.com/app/apikey

4. **Firebase project** (already created)
   - Enable Firebase Auth (Anonymous + Email/Password + Google sign-in)
   - Enable Firestore in Native mode
   - Generate Service Account JSON: Firebase Console → Project Settings → Service Accounts → Generate new private key
   - Stringify for env var: `python -c "import json; f=open('key.json'); print(json.dumps(json.load(f)))"`
   - Enable Firebase Scheduler (Cloud Functions, Blaze plan required for scheduled functions)
   - Acquire: `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT`

5. **LangSmith project** (already have account)
   - Create project named `advocate`
   - Acquire: `LANGCHAIN_API_KEY`
   - Set `LANGCHAIN_TRACING_V2=true` — **must be active from first deploy, never disabled**

6. **Railway deployment target**
   - Create Railway account (if not done): https://railway.app
   - Create new project, add service from GitHub repo or Docker
   - Add all env vars from `.env.example` to Railway environment
   - Note: Railway does not require a Dockerfile for Python if using nixpacks — confirm build config

7. **Copy `.env.example` → `.env`** and fill all values before any local runs

---

### Phase 1 — MVP Core (24hr gate)

**Backend — Agent & Tools**
- `advocate/pyproject.toml` — dependencies (langchain, langchain-google-genai, fhirpy, fastapi, uvicorn, firebase-admin, python-dotenv, ruff, pytest, langsmith)
- `advocate/models.py` — shared Pydantic V2 models
- `advocate/fhir_client.py` — FHIRService wrapping AsyncFHIRClient
- `advocate/agent.py` — AgentExecutor, tool registration
- `advocate/tools/symptom_timeline.py` — Tool 1
- `advocate/tools/specialist_navigator.py` — Tool 2
- `advocate/tools/appointment_brief.py` — Tool 3
- `advocate/verification/citation.py` + `pipeline.py` — FHIR Citation layer (1 of 5)
- `advocate/prompts/system.py` — system prompt template
- `advocate/prompts/somatic.py` — somatic fallback prompts

**Auth & Infrastructure**
- `advocate/auth.py` — Firebase token verification, Firestore patient mapping, rotation transaction

**API**
- `advocate/main.py` — FastAPI app, firebase-admin init, LangSmith tracing enabled at startup
- Endpoints required for gate: `POST /session` (start), `POST /session/{id}/message` (send), `GET /health`

**Seeding**
- `advocate/seed_patient.py` — Synthea → OpenEMR via FHIR POST; prints patient_id on completion

**Tests**
- `advocate/tests/conftest.py` — mock FHIR client, sample Bundles
- 5 passing eval test cases (LangSmith eval suite)

**Deployment**
- Railway service running, env vars set, health endpoint returning 200

**Gate checklist (must all pass):**
- [ ] `symptom_timeline`, `specialist_navigator`, `appointment_brief_generator` return valid output
- [ ] FHIR Citation verification layer active on all outputs
- [ ] 5 eval cases passing in LangSmith
- [ ] `/health` returns 200 on Railway
- [ ] Firebase Auth token verified on at least one protected endpoint
- [ ] LangSmith traces showing in dashboard
- [ ] `seed_patient.py` ran successfully, patient_id in Firestore

---

### Phase 2 — Friday Gate (16hr mark)

**Backend — Remaining Tools**
- `advocate/tools/clinical_translator.py` — Tool 4 (`patient_to_clinical` direction only)
- `advocate/tools/dismissal_detector.py` — Tool 5

**Verification — Remaining 4 Layers**
- `advocate/verification/hallucination.py`
- `advocate/verification/boundary.py`
- `advocate/verification/confidence.py`
- `advocate/verification/escalation.py`
- Wire all into `pipeline.py`

**Flutter Frontend**
- `advocate/flutter/` initialized (`flutter create --platforms web,ios,android`)
- Auth flow: anonymous sign-in → chat → upgrade to email/Google
- 5 tabs: Welcome, Chat, Patients (list), Briefs, Flags (from CLAUDE.md nav)
- Agent state panel (SSE from `GET /session/{id}/state`)
- Persona selection + demo walkthrough (DemoScript + WalkthroughController)
- Theme: M3 tokens, at least 1 patient theme variant (Sage)
- Additional FastAPI endpoint: `GET /session/{id}/state` (SSE stream)

**Testing & Evals**
- `advocate/tests/test_tools/` — unit tests for all 5 tools
- `advocate/tests/test_verification/` — tests for all 5 verification layers with known-bad inputs
- 50+ eval cases in LangSmith (20 happy path, 10 edge, 10 adversarial, 10 multi-step)

**Gate checklist (must all pass):**
- [ ] All 5 tools returning valid output
- [ ] All 5 verification layers active
- [ ] Clinical boundary check catching diagnostic language
- [ ] Hallucination guard catching invented values
- [ ] Flutter web build succeeds (`flutter build web`)
- [ ] Flutter auth flow: anonymous sign-in works end-to-end
- [ ] 50+ evals passing in LangSmith
- [ ] Anonymous account cleanup Cloud Function deployed (Firebase Scheduler, daily)

---

### Phase 3 — Sunday Final

**Provider Finder (Stretch)**
- `advocate/tools/provider_finder.py` — Tool 6
- NPPES NPI Registry (free, public): `https://npiregistry.cms.hhs.gov/api/`
- Apify/Healthgrades integration (sprint only — ToS note in code): `APIFY_API_KEY` needed
- Note: production alternative is Zembra (Zocdoc data); Apify is sprint-only

**Demo Polish**
- 10 demo scenarios passing end-to-end (from `advocate_demos_updated.md`)
- Hard-stop moments annotated in walkthrough
- Coach marks on web/mobile

**Collateral**
- Architecture doc updated
- AI cost analysis from LangSmith token data
- Demo video (3–5 min) recorded
- Eval dataset published to GitHub + Hugging Face (GPL v3)

**Gate checklist:**
- [ ] All 10 demo scenarios pass
- [ ] Provider finder returns at least 3 results for test query
- [ ] LangSmith cost report exported
- [ ] Demo video uploaded
- [ ] Eval dataset published

---

## Tokens / Credentials Summary Table

| Credential | How to Acquire | Where to Set | Status |
|---|---|---|---|
| `OPENEMR_CLIENT_ID` | Admin → API Clients → Register | `.env` + Railway | Manual step |
| `OPENEMR_CLIENT_SECRET` | Same as above | `.env` + Railway | Manual step |
| `GOOGLE_API_KEY` | https://aistudio.google.com/app/apikey | `.env` + Railway | Already done |
| `FIREBASE_PROJECT_ID` | Firebase Console → Project Settings | `.env` + Railway | Already done |
| `FIREBASE_SERVICE_ACCOUNT` | Firebase Console → Service Accounts → Generate key → stringify | `.env` + Railway | Manual step |
| `LANGCHAIN_API_KEY` | https://smith.langchain.com → Settings → API Keys | `.env` + Railway | Already done |
| `APIFY_API_KEY` | https://apify.com → Settings → Integrations (Phase 3 stretch only) | `.env` + Railway | Optional |

---

## Critical Constraints (Do Not Change)

- `LANGCHAIN_TRACING_V2=true` must be active from first deploy — token data for cost deliverable
- Never call `load_dotenv()` in library modules — only in `main.py`
- All FHIR field access via `.get()` — no bare dict access
- All multi-document Firestore mutations via `writeBatch`
- Verification pipeline must run on every agent output before delivery
- Sprint uses synthetic data only (Synthea) — no real PHI

---

## Reference Docs

- Presearch + tool schemas: `project_requirements_and _research/advocate_presearch_v10.md`
- Sprint checklist + acceptance criteria: `advocate/REQUIREMENTS.md`
- Implementation guide: `advocate/CLAUDE.md`
- Design system: `project_requirements_and _research/advocate-m3-design-spec.md`
- Demo scenarios: `project_requirements_and _research/advocate_demos_updated.md`
