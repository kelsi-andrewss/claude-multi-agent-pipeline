# Plan: advocate/ROADMAP.md

## Context

The Advocate agent layer is fully specified (architecture, tools, verification layers, Flutter UI, demo scenarios) but has zero implementation. This ROADMAP.md serves as the living checklist for the sprint — covering manual platform setup steps, token/credential acquisition, and phased implementation gates (MVP → Friday → Sunday). It must be written to remain logically consistent when read alongside the presearch doc and requirements doc, using wording that survives decisions still in flux (e.g. provider_finder service choice).

## Target file

`/Users/kelsiandrews/gauntlet/openemr/advocate/ROADMAP.md`

## Structure

Four phases, each with:
- Manual/external steps with specific links and what to copy/record
- Implementation tasks referencing the component briefs in REQUIREMENTS.md
- A clear gate check (what must pass before moving on)

---

## Phase 0 — Bootstrap (Before writing a single line of code)

### Section A: Credential & Token Acquisition (manual, sequential — each blocks the next)

**1. Google Cloud & Gemini**
- Go to https://console.cloud.google.com/ → create or select a project
- Enable APIs: "Generative Language API" (Gemini), "Cloud Run API", "Cloud Functions API", "Cloud Firestore API", "Firebase Auth"
- Go to APIs & Services → Credentials → Create API Key → restrict to "Generative Language API"
- Record as `GOOGLE_API_KEY` in `.env`
- Link: https://console.cloud.google.com/apis/credentials

**2. Firebase**
- Go to https://console.firebase.google.com/ → Add project (link to the GCP project above)
- Authentication → Sign-in method → Enable: Anonymous, Google, Email/Password
- Firestore → Create database (production mode, region: us-central1)
- Project Settings → Service Accounts → Generate new private key → download JSON
- Stringify the JSON: `python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))" service-account.json`
- Record `FIREBASE_PROJECT_ID` and stringified JSON as `FIREBASE_SERVICE_ACCOUNT` in `.env`
- Create Firestore document manually: collection `rotation_state` → document `counter` → field `next_index: 0`
- Link: https://console.firebase.google.com/

**3. LangSmith** ← CRITICAL: must be active from first deploy
- Go to https://smith.langchain.com/ → create account → Settings → API Keys → Create API Key
- Record as `LANGCHAIN_API_KEY` in `.env`
- Confirm `LANGCHAIN_TRACING_V2=true` and `LANGCHAIN_PROJECT=advocate` in `.env`
- This is the source of truth for the AI Cost Analysis deliverable — if not logging from day 1, dev spend data is lost

**4. OpenEMR OAuth2 Client**
- Go to https://demo.openemr.io → Admin → API Clients → Register new client
  - Scope: openid fhir-r4 patient/Patient.read patient/Encounter.read patient/Condition.read patient/Observation.read patient/MedicationRequest.read patient/AllergyIntolerance.read patient/DocumentReference.read patient/Procedure.read patient/DiagnosticReport.read
  - Grant type: client_credentials
- Record `OPENEMR_CLIENT_ID` and `OPENEMR_CLIENT_SECRET` in `.env`
- Verify FHIR endpoint responds: `curl https://demo.openemr.io/apis/default/fhir/metadata`
- Link: https://demo.openemr.io

**5. Fill `.env`**
- Copy `advocate/.env.example` to `advocate/.env`
- Fill all 10 variables
- Run `cat advocate/.env | grep -v "=$"` to verify nothing is blank
- Never commit `.env` to git

### Section B: Project Scaffolding (manual, one-time)

**6. Python environment**
```bash
cd advocate/
python3 -m venv venv
source venv/bin/activate
pip install langchain langchain-google-genai fhirpy fastapi uvicorn pydantic python-dotenv firebase-admin google-cloud-firestore pytest ruff httpx
```
- Then create `pyproject.toml` with these deps pinned

**7. Flutter setup**
- Install Flutter SDK: https://docs.flutter.dev/get-started/install
- `cd advocate/flutter && flutter create . --project-name advocate`
- Add to `pubspec.yaml`: `firebase_core`, `firebase_auth`, `cloud_firestore`, `flutter_riverpod`, `hooks_riverpod`, `flutter_secure_storage`, `shared_preferences`, `http`, `go_router`
- Run `flutterfire configure` to wire Firebase config (downloads `google-services.json` / `GoogleService-Info.plist`)
- Link: https://firebase.flutter.dev/docs/overview

**8. Seed Synthea patient**
- Download a Synthea FHIR bundle or generate via https://synthea.mitre.org/
- Run `python advocate/seed_patient.py <bundle.json>` once FHIR client is ready (Step MVP-3)
- Record the returned `patient_id` — used in all test cases

### Gate: Phase 0 complete when `.env` has no blank values and `curl` returns valid FHIR metadata

---

## Phase 1 — MVP (Tuesday gate)

**Goal**: 3 tools working end-to-end, auth, Flutter chat screen, deployed on Cloud Run, LangSmith logging, 5 eval cases passing.

### Implementation order (sequential — each builds on the previous)

**MVP-1: models.py**
- All Pydantic V2 models: `SessionState`, `SymptomTimelineInput/Output`, `SpecialistNavInput/Output`, `AppointmentBriefInput/Output`, `FHIRResource`, `VerificationResult`, `SomaticClassifierOutput`
- No circular imports — everything else imports from here

**MVP-2: fhir_client.py**
- `FHIRService` wrapping `AsyncFHIRClient`
- All field access via `.get()` — no bare dict access
- Handle 404 as skip, not crash
- Pagination: follow `Bundle.link[rel=next]`, stop at 500

**MVP-3: seed_patient.py + seed run**
- POST Synthea bundle to FHIR endpoint
- Idempotent (skip if patient exists)
- Run now and record `patient_id`

**MVP-4: Tools (3 MVP tools)**
- `tools/symptom_timeline.py` — Encounter + Condition + Observation, chronological, FHIR citations
- `tools/specialist_navigator.py` — specialist type + referral language + pcp_first flag
- `tools/appointment_brief.py` — clinical brief + patient prep sheet; "Patient's Own Words" only when somatic_mode_active=True or no FHIR match within 24 months

**MVP-5: verification/citation.py + pipeline.py (Citation layer only for MVP)**
- Every clinical fact traces to a FHIR resource ID
- Runs on every agent output before delivery

**MVP-6: agent.py**
- ReAct agent via `create_structured_chat_agent`
- `ConversationBufferWindowMemory(k=10)` in-memory
- Somatic classifier integrated (separate Gemini Flash call, temp=0, <50 tokens, fires on every human turn)
- Verification pipeline (citation layer) runs post-agent

**MVP-7: main.py (FastAPI)**
- `POST /chat` (body: `message`, `session_id`, `patient_id`)
- `GET /health`
- CORS middleware
- Firebase Admin initialized at startup
- `load_dotenv()` here only (not in library modules)

**MVP-8: auth.py**
- `verify_firebase_token` FastAPI dependency (validates Firebase ID token, returns `uid`)
- `get_patient_id` FastAPI dependency (Firestore `users/{uid}` → `patient_id`)
- New user: Firestore transaction on `rotation_state/counter`, assigns next Synthea patient rotation index

**MVP-9: Flutter — sign-in + chat**
- Sign-in screen: Anonymous, Google, Email/Password, "Demo Experience" button
- Chat screen: message input, response display, basic session state
- Firebase Auth wired: `authStateProvider` stream
- API calls to `/chat` with Firebase ID token in `Authorization` header

**MVP-10: Deploy to Cloud Run**
- `gcloud run deploy advocate --source advocate/ --region us-central1`
- Set all env vars via Cloud Run console (not .env — .env is local only)
- Verify `GET /health` returns 200 from the Cloud Run URL

**MVP-11: Eval suite (5 cases)**
- `tests/eval/` — 5 cases: appointment prep, specialist nav, empty records, diagnosis boundary violation, multi-turn
- Run against deployed endpoint, verify in LangSmith dashboard

### Gate: MVP complete when all 13 REQUIREMENTS.md MVP checkboxes are checked

---

## Phase 2 — Friday (Early Submission)

**Goal**: 2 more tools, all 5 verification layers, somatic fallback fully wired, 50+ evals, full Flutter UI, observability dashboard, eval dataset published.

**F-1: Tools (2 more)**
- `tools/clinical_translator.py` — patient→clinical direction only for sprint; outputs are "suggested," never authoritative
- `tools/dismissal_detector.py` — gap detection + follow-up questions + escalation flag; cross-session state in-memory dict

**F-2: Verification pipeline (all 5 layers)**
- `verification/hallucination.py` — verify numbers, dates, medication names, dosages against raw FHIR; unverified → "not documented"
- `verification/boundary.py` — semantic scan for diagnostic language ("you have X", "this means", "you should take"); rewrite or remove
- `verification/confidence.py` — High/Moderate/Low tier; display "Based on N records spanning M months"
- `verification/escalation.py` — fires on Low confidence + high-stakes appointment type; or dismissal pattern repeated for same concern
- Update `verification/pipeline.py` to chain all 5 layers

**F-3: Somatic fallback wiring**
- Somatic classifier already in agent.py (MVP-6); wire `patient_language` output to `clinical_translator` input
- Trigger "Patient's Own Words" section in appointment_brief when somatic active

**F-4: SSE agent state stream**
- `GET /session/{id}/state` — FastAPI `StreamingResponse` emitting tool call events, verification results, token usage
- Flutter `AgentStatePanelWidget` listens via `http` package EventSource
- Side panel on web/desktop (280dp), bottom sheet on mobile (40% height, collapsible)
- Visible only when `devModeProvider == true`

**F-5: Flutter — remaining screens**
- Timeline screen (symptom visualization)
- Prep screen (checklist + brief)
- Brief screen (clinical brief + "My Own Words")
- Settings screen (account, appearance, dev mode toggle)
- All 5 bottom nav tabs functional

**F-6: Flutter — auth flows**
- Google sign-in working
- Email/password sign-in working
- Account upgrade: anonymous → authenticated via `linkWithCredential()`

**F-7: Firebase Cloud Function**
- `functions/cleanup_anonymous_users.py` — deletes anonymous accounts inactive >90 days
- Deploy as Pub/Sub trigger + Firebase Scheduler (daily)
- Link: https://firebase.google.com/docs/functions/schedule-functions

**F-8: Prescripted walkthrough — Demo 1 (Serena)**
- `DemoScript` class for Serena persona
- Hard-stop annotations at: somatic trigger, brief generation, verification catch, escalation trigger
- Coach marks: bottom overlay cards on mobile, inline agent state panel on web

**F-9: Eval suite (50+ cases)**
- 20+ happy path, 10+ edge (empty records, missing Practitioner refs, pagination), 10+ adversarial (prompt injection: malicious Condition.code.display, system prompt extraction, Base64 in DocumentReference), 10+ multi-step
- All passing in LangSmith

**F-10: Publish eval dataset**
- GitHub: `advocate/tests/eval/` — public, GPL v3 license
- Hugging Face: upload dataset card + JSONL eval cases
- Link: https://huggingface.co/datasets

### Gate: Friday complete when all REQUIREMENTS.md Friday checkboxes are checked and LangSmith shows >90% eval pass rate

---

## Phase 3 — Sunday (Final)

**Goal**: All 10 demos, architecture doc, cost analysis, video, open source publish, social post.

**S-1: provider_finder tool (stretch)**
- NPPES NPI Registry (free, no auth): https://npiregistry.cms.hhs.gov/api/
- Review aggregation service: TBD (Healthgrades via Apify, or alternative — decision pending)
- If service decision not resolved: ship FHIR-only fallback (sufficient per spec)
- `functools.lru_cache(maxsize=32)` on NPPES responses per specialty+zip

**S-2: All 10 demo scenarios passing**
- Run each demo persona through the prescripted walkthrough
- Verify expected tool calls, output format, verification layer behavior per demos_updated.md

**S-3: Prescripted walkthroughs — Demo 2 (Maya) + Demo 3 (Ruth)**
- `DemoScript` classes for Maya and Ruth personas
- Same coach mark pattern as Serena

**S-4: Settings screen complete**
- Account management (sign out, upgrade anonymous)
- Appearance (theme picker: Sage/Terracotta/Lavender/Sand/Rose for patient, blue for provider)
- Developer mode toggle (persisted to `shared_preferences`)

**S-5: Agent architecture doc**
- 1-2 pages, use template from presearch Section 20
- Include: tool registry, verification pipeline, somatic fallback flow, FHIR auth, deployment topology

**S-6: AI cost analysis**
- Pull actual dev spend from LangSmith (input + output tokens, all API calls from Hour 0)
- Project at 100 / 1K / 10K / 100K users per month
- Document assumptions (avg turns per session, tool call distribution, verification layer token overhead)

**S-7: Demo video (3-5 min)**
- Use Demo Experience prescripted walkthrough as base (Flutter sign-in → persona selection → chat)
- Show: somatic fallback triggering, verification layer catch, clinical brief output, agent state panel
- Record with screen capture; voiceover optional

**S-8: Open source**
- Ensure `advocate/` backend is clean, documented, and public-ready (no secrets, no PHI)
- README in `advocate/` with setup instructions (mirrors Phase 0 steps above)
- Social post on X or LinkedIn: link to GitHub repo + eval dataset + demo video

### Gate: Sunday complete when all REQUIREMENTS.md Sunday checkboxes are checked

---

## Quick Reference: All tokens/credentials needed

| Credential | Where to get | Env var |
|---|---|---|
| Gemini API key | https://console.cloud.google.com/apis/credentials | `GOOGLE_API_KEY` |
| Firebase project ID | https://console.firebase.google.com/ | `FIREBASE_PROJECT_ID` |
| Firebase service account JSON | Firebase Console → Project Settings → Service Accounts | `FIREBASE_SERVICE_ACCOUNT` |
| LangSmith API key | https://smith.langchain.com/ → Settings → API Keys | `LANGCHAIN_API_KEY` |
| OpenEMR OAuth2 client ID | https://demo.openemr.io → Admin → API Clients | `OPENEMR_CLIENT_ID` |
| OpenEMR OAuth2 client secret | Same as above | `OPENEMR_CLIENT_SECRET` |

All six must be in `.env` before any backend code will run.

---

## Notes on in-flux decisions

- **provider_finder review service**: "review aggregation service" wording is used throughout — implementation choice (Apify/Healthgrades or alternative) does not affect the roadmap structure; FHIR-only is the documented fallback.
- **SSE format**: exact event schema TBD in F-4 implementation; endpoint path and Flutter consumption pattern are locked.
- **Multi-turn persistence**: MVP uses in-memory `ConversationBufferWindowMemory(k=10)`; post-sprint upgrade path to Firestore is optional and not in scope.
- **Healthgrades/Apify licensing**: provider_finder is stretch — defer the licensing decision until S-1.
