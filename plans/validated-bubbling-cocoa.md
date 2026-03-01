# Advocate: AI Health Navigation Agent for OpenEMR

## Context

AgentForge sprint — build a production-ready AI agent on an open-source project. You chose OpenEMR (healthcare EHR). The agent ("Advocate") helps patients prepare for appointments, build symptom timelines, and navigate specialists. Two integration surfaces: a standalone Python/LangChain service (the AI brain) and a PHP custom module that embeds Advocate into OpenEMR's patient portal.

**Deadlines:** MVP Tuesday (24h), Eval framework Friday (4d), Final Sunday (7d).

---

## Architecture

```
Browser (Patient Portal)
    |
    v
PHP Module (oe-module-advocate)      <-- thin proxy, portal UI
    |  renders card + chat section via RenderEvent hooks
    |  proxies /chat requests, injects $pid from session
    v
Python FastAPI Service (advocate/)   <-- all AI logic
    |  LangChain agent, 6 tools, verification pipeline
    |  LangSmith observability
    v
OpenEMR FHIR R4 API                 <-- data source
    OAuth2 client_credentials
```

The PHP module never touches AI logic. The Python service never touches PHP. Clean boundary.

---

## Phase 1: Python Agent MVP (Hours 0-12)

### Directory: `/advocate/` (repo root)

```
advocate/
  pyproject.toml
  main.py                     # FastAPI app
  agent.py                    # LangChain agent + tool registry
  models.py                   # Pydantic models
  fhir_client.py              # FHIR API wrapper (OAuth2 + resource fetching)
  .env.example
  tools/
    __init__.py
    symptom_timeline.py       # MVP tool 1
    specialist_navigator.py   # MVP tool 2
    appointment_brief.py      # MVP tool 3
    clinical_translator.py    # Friday tool 4
    dismissal_detector.py     # Friday tool 5
    provider_finder.py        # Stretch tool 6
  verification/
    __init__.py
    pipeline.py               # Orchestrates all layers
    citation.py               # MVP: FHIR source attribution
    hallucination.py          # Friday
    boundary.py               # Friday: no diagnostic language
    confidence.py             # Friday
  prompts/
    system.py                 # System prompt + boundaries
  tests/
    conftest.py               # Mock FHIR client fixtures
    test_symptom_timeline.py
    test_specialist_nav.py
    test_appointment_brief.py
    test_citation.py
    test_agent.py
    eval/                     # Friday: 50+ LangSmith test cases
      test_cases.yaml
      eval_runner.py
```

### Implementation order

| Step | File | Time | Notes |
|------|------|------|-------|
| 1 | `pyproject.toml` | 15m | deps: langchain, langchain-google-genai, fhirpy, pydantic, fastapi, uvicorn, httpx, python-dotenv, langsmith. Optional: langchain-anthropic (for Claude swap later). Dev: pytest, pytest-asyncio, ruff |
| 2 | `models.py` | 30m | All Pydantic V2 models: `ChatRequest`, `ChatResponse`, `FHIRResourceRef`, `SymptomEntry`, `SpecialistResult`, `AppointmentBrief`, `VerificationResult`, `SessionState` |
| 3 | `fhir_client.py` | 1h | OAuth2 client_credentials flow to `/oauth2/default/token`. Methods: `get_patient()`, `search_conditions()`, `search_encounters()`, `search_observations()`, `search_medications()`, `search_allergies()`. Each returns list of dicts. Graceful 404 handling. |
| 4 | `tools/symptom_timeline.py` | 2h | Fetches Encounter + Condition + Observation. Builds chronological narrative. Each entry carries `fhir_resource_id` + `fhir_resource_type` for citation layer. Flags symptom/diagnosis discrepancies. |
| 5 | `tools/specialist_navigator.py` | 1.5h | Takes symptoms/conditions. LLM determines specialist type, PCP-first vs direct routing, generates referral language patient can use with GP. |
| 6 | `tools/appointment_brief.py` | 2h | Dual output: clinical brief (doctor-facing) + patient prep sheet. Fetches MedicationRequest, AllergyIntolerance, recent Conditions, Observations. |
| 7 | `verification/citation.py` | 1h | Post-processes agent output. Every clinical fact matched to a FHIR resource ID or marked "patient-reported" / "not documented". |
| 8 | `verification/pipeline.py` | 30m | Runs all active verification layers. MVP: citation only. Friday: all 5. |
| 9 | `prompts/system.py` | 30m | System prompt: role, clinical boundaries (never diagnose), tool usage, output format. |
| 10 | `agent.py` | 1.5h | `create_structured_chat_agent` with tool registry. `ConversationBufferWindowMemory(k=10)`. Verification pipeline runs on every response. |
| 11 | `main.py` | 1h | FastAPI: `POST /chat` (message + session_id + patient_id), `GET /health`. CORS middleware. |
| 12 | 5 test cases | 1.5h | (a) symptom timeline happy path, (b) specialist nav, (c) empty FHIR records, (d) clinical boundary violation caught, (e) multi-turn conversation |

### Key decisions

- **FastAPI over Firebase Cloud Functions** — zero infrastructure setup, instant `uvicorn main:app --reload`, trivial Railway deploy. Cloud Functions can be added later as `main_cf.py` importing the same `agent.py`.
- **LLM: Gemini Flash for MVP** — cheapest, fastest. Use `langchain-google-genai` package. Abstract behind LangChain's `ChatModel` interface so swapping to Claude (`langchain-anthropic`) later is a one-line config change. Include both packages in `pyproject.toml` optional deps.
- **Frontend: Portal only** — no Streamlit or React. The OpenEMR patient portal IS the demo. Shows real integration, not a toy.
- **FHIR auth** — client_credentials grant against local Docker OpenEMR (`http://localhost:8300/oauth2/default/token`). Register client via OpenEMR admin UI first.

---

## Phase 2: OpenEMR PHP Module (Hours 12-20)

### Directory: `/interface/modules/custom_modules/oe-module-advocate/`

```
oe-module-advocate/
  openemr.bootstrap.php       # Auto-included by module loader
  info.txt                    # "Advocate Health Navigation Agent"
  src/
    Bootstrap.php             # Event subscriptions
    Controller/
      PortalController.php    # Renders card + chat section + handles AJAX proxy
  templates/
    advocate/
      portal-card.html.twig   # Dashboard card (injected via EVENT_DASHBOARD_INJECT_CARD)
      chat-section.html.twig  # Collapsible chat UI (injected via EVENT_SECTION_RENDER_POST)
      chat-scripts.html.twig  # JS init (injected via EVENT_DASHBOARD_RENDER_SCRIPTS)
  public/
    css/
      advocate.css            # Chat UI styles
    js/
      advocate-chat.js        # Vanilla JS chat client
```

### How it hooks in (zero core file modifications)

1. **`openemr.bootstrap.php`** — follows telehealth module pattern exactly:
   ```php
   $classLoader->registerNamespaceIfNotExists(
       'OpenEMR\\Modules\\Advocate\\', __DIR__ . '/src'
   );
   $bootstrap = new Bootstrap($eventDispatcher);
   $bootstrap->subscribeToEvents();
   ```

2. **`Bootstrap.php`** — subscribes to 3 portal events:
   - `RenderEvent::EVENT_DASHBOARD_INJECT_CARD` → renders `portal-card.html.twig` (appears at line 661 of `home.html.twig` via `fireEvent()`)
   - `RenderEvent::EVENT_SECTION_RENDER_POST` → renders `chat-section.html.twig`
   - `RenderEvent::EVENT_DASHBOARD_RENDER_SCRIPTS` → renders `chat-scripts.html.twig`

3. **`portal-card.html.twig`** — matches existing card pattern from `_nav_icon.html.twig`:
   ```twig
   <a id="advocate-go" class="col-lg-2 col-md-4 col-sm-6 col-6 card bg-light ..."
      data-toggle="collapse" data-parent="#cardgroup"
      href="#advocate-chat-card"
      data-window-title="{{ 'Health Navigator' | xl }}">
       <h1 class="card-image">
           <i class="fa fa-2x fa-comments text-dark"></i>
       </h1>
       <div class="card-body pl-1 pr-1 pl-sm-3 pr-sm-3">
           <button class="btn btn-success d-block w-100 text-light">
               {{ 'Health Navigator' | xl }}
           </button>
       </div>
   </a>
   ```

4. **`chat-section.html.twig`** — collapsible card (portal SPA pattern):
   - Message list container, text input, send button
   - Bootstrap 4.6, matches existing portal styling
   - `id="advocate-chat-card"` matches the card's `href`

5. **`advocate-chat.js`** — vanilla JS + fetch:
   - `POST` to `PortalController.php` AJAX endpoint
   - Sends CSRF token (`CsrfUtils::collectCsrfToken()`)
   - Controller proxies to Python service, injecting `$pid` from portal session
   - No React, no Angular — plain JS matches the portal's jQuery/Bootstrap stack

### Security

- **Patient ID enforcement:** `verify_session.php` sets `$pid` from authenticated session. The proxy always uses this — patient cannot query other patients' data.
- **CSRF:** All AJAX calls include OpenEMR's CSRF token, validated server-side.
- **Python service URL:** configured in module settings, never exposed to browser.

### Reference files

| File | Why |
|------|-----|
| `interface/modules/custom_modules/oe-module-comlink-telehealth/openemr.bootstrap.php` | Exact bootstrap pattern to follow |
| `src/Events/PatientPortal/RenderEvent.php` | 4 event constants for portal injection |
| `templates/portal/home.html.twig:661` | Where `fireEvent(eventNames.dashboardInjectCard)` renders module cards |
| `templates/portal/partial/_nav_icon.html.twig` | Card HTML structure to match |
| `portal/verify_session.php` | Session auth — sets `$pid`, loads globals |
| `portal/home.php:210-316` | `buildNav()` — nav menu structure for reference |

---

## Phase 3: Deploy + Integrate (Hours 20-24)

1. **Python service → Railway**: `Procfile: web: uvicorn advocate.main:app --host 0.0.0.0 --port $PORT`
2. **OpenEMR Docker** (existing `docker/development-easy/`): module auto-discovered, enable via Admin > Modules
3. **Seed test patient**: run `advocate/seed_patient.py` against local FHIR API
4. **Integration test**: portal login → click Health Navigator → send message → see response
5. **5 pytest test cases passing**

---

## Phase 4: Friday Enhancements (Days 2-4)

### Python
- Tools 4-5: `clinical_translator.py`, `dismissal_detector.py`
- All 5 verification layers active
- Somatic fallback classifier (temp=0, separate LLM call)
- LangSmith tracing: `LANGCHAIN_TRACING_V2=true`
- 50+ eval test cases in `tests/eval/test_cases.yaml`
- SSE streaming for `/chat/stream`

### PHP module
- SSE proxy support in controller
- Typing indicator + loading states in chat JS
- Verification badges in UI (confidence tier, citation count)

### Observability
- LangSmith: traces, latency, token usage, eval scores
- Error tracking + cost per request

---

## Phase 5: Sunday Final (Days 5-7)

- Tool 6: `provider_finder.py` (NPPES NPI registry)
- Architecture doc (1-2 pages)
- AI cost analysis (dev spend + projections at 100/1K/10K/100K users)
- 3-5 min demo video
- Open source: publish module as reusable package + eval dataset
- Social post

---

## Verification

### End-to-end test flow
1. `docker compose up` in `docker/development-easy/`
2. Seed patient: `python advocate/seed_patient.py`
3. Start Python service: `cd advocate && uvicorn main:app --reload`
4. Run tests: `cd advocate && pytest`
5. Enable module: Admin > Modules > Install oe-module-advocate
6. Configure module: set Python service URL in module config
7. Patient portal login → Dashboard → click "Health Navigator" card → send message → verify response with FHIR citations

### What to validate
- Agent returns structured responses with FHIR resource citations
- Clinical boundary check blocks diagnostic language
- Empty FHIR records handled gracefully (not hallucinated)
- Portal card renders correctly in dashboard grid
- Chat proxy enforces patient ID from session (not from client)
- CSRF token validated on every AJAX call
