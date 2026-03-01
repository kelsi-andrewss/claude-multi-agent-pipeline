# Plan: Stack Switch — Flutter + Firebase + Gemini for Advocate

## Context

Story-003 (now merged into `epic/advocate-impl-bootstrap`, PR #2) configured the project for a Python/LangChain/Claude/Streamlit/Railway stack. The user has decided to change the stack before any implementation code is written.

**Why**: The user wants to deploy Advocate across mobile (iOS/Android), web, and tablet (provider-facing) from a single codebase. Flutter is the only framework that delivers all four surfaces without duplicating code. Firebase provides auth, Firestore, Cloud Functions, and Hosting with native SDKs for all Flutter targets. Gemini completes the Google ecosystem story and demonstrates breadth beyond the user's previous Firebase/Gemini project (which was a different problem domain — React/Konva).

**What stays the same**: Everything about Advocate's product design, tools, verification layers, FHIR client patterns, acceptance criteria, and clinical safety boundaries. OpenEMR's FHIR R4 API remains the data source.

**What changes**: The delivery layer (how the agent is hosted and how users interact with it).

---

## Architecture

```
Flutter app (iOS / Android / Web / Tablet)
    |
    v
Firebase Cloud Functions (Python 3.11+)
    |
    +--> Gemini API (agent reasoning, tool execution)
    |
    +--> OpenEMR FHIR R4 API (patient data)
    |
    +--> Firestore (session state, conversation history)
```

- **Frontend**: Flutter — single Dart codebase for all 4 surfaces
- **Backend**: Firebase Cloud Functions (Python) — agent logic, FHIR client, verification pipeline
- **AI Model**: Gemini via `langchain-google-genai` (`ChatGoogleGenerativeAI`)
- **Data**: OpenEMR FHIR R4 API (unchanged)
- **State**: Firestore — session state, conversation history (replaces in-memory ConversationBufferWindowMemory)
- **Auth**: Firebase Auth — patient identity
- **Hosting**: Firebase Hosting (web), App Store / Play Store (mobile)
- **Observability**: LangSmith (unchanged — works from Cloud Functions)

---

## Files to Modify (on `epic/advocate-impl-bootstrap` branch)

All files below already exist on the epic branch from story-003.

### 1. `advocate/CLAUDE.md` — REWRITE

Changes with reasoning:

| Section | Change | Reasoning |
|---|---|---|
| Tech Stack | Claude Sonnet 4.6 → Gemini via `langchain-google-genai` | Stack switch to Google ecosystem |
| Tech Stack | `langchain-anthropic` / `ChatAnthropic` → `langchain-google-genai` / `ChatGoogleGenerativeAI` | Direct dependency swap |
| Tech Stack | FastAPI → Firebase Cloud Functions (Python) | Cloud Functions replaces the custom API layer |
| Tech Stack | Streamlit → Flutter | Multi-platform frontend replaces demo-only UI |
| Tech Stack | Railway → Firebase (Hosting + Cloud Functions) | Deployment platform change |
| Module Organization | Remove `app.py` (Streamlit), `api.py` (FastAPI) | Replaced by Cloud Functions entry point (`main.py`) and Flutter app |
| Module Organization | Add `main.py` (Cloud Functions entry point) | Firebase convention for Python Cloud Functions |
| Module Organization | Add `flutter/` directory reference | Flutter project lives alongside Python backend |
| LangChain Patterns | `ChatAnthropic(model="claude-sonnet-4-6")` → `ChatGoogleGenerativeAI(model="gemini-2.0-flash")` | Model swap. Use gemini-2.0-flash for latency; gemini-2.5-pro available for complex verification |
| LangChain Patterns | `astream_events` for Streamlit → Cloud Functions HTTP streaming or Firestore write-back | Flutter reads responses from Firestore or SSE endpoint |
| Async Patterns | Somatic classifier "separate Haiku call" → "separate Gemini Flash call, temp=0" | Haiku was Anthropic's fast model; Gemini Flash is the equivalent |
| Environment Variables | `ANTHROPIC_API_KEY` → `GOOGLE_API_KEY` or `GOOGLE_APPLICATION_CREDENTIALS` | Google auth replaces Anthropic auth |
| Environment Variables | Add Firebase config vars (`FIREBASE_PROJECT_ID`, etc.) | New infra dependency |
| Environment Variables | Remove Railway references | No longer deploying to Railway |
| Environment Variables | `load_dotenv()` note: in Cloud Functions, env vars come from Firebase config, not `.env` files | Different env var loading pattern |
| Coder pitfalls | Add: Gemini function calling uses different schema format than Claude tool_use | Key gotcha when porting tool definitions |
| Coder pitfalls | Add: Cloud Functions cold start (~1-3s) — set `min_instances=1` on latency-critical functions | Real latency concern |
| Coder pitfalls | Add: Firestore writes for session state must use transactions for concurrent access | Replaces in-memory state |

**Unchanged sections**: Python Style, Pydantic Patterns, FHIR Client, Testing, Performance Targets, Key Reference. These are all backend concerns unaffected by the stack switch.

### 2. `advocate/REQUIREMENTS.md` — TARGETED EDITS

Changes with reasoning:

| Location | Change | Reasoning |
|---|---|---|
| MVP checklist | "Deployed on Railway, publicly accessible" → "Deployed on Firebase (Cloud Functions + Hosting), publicly accessible" | Platform change |
| MVP checklist | "Conversation history maintained (ConversationBufferWindowMemory, k=10)" → "Conversation history maintained (Firestore-backed, last 10 turns)" | Firestore replaces in-memory for cross-device persistence |
| MVP checklist | Add: "Flutter web app connects to Cloud Functions endpoint" | New deliverable — the frontend |
| Friday checklist | "Somatic fallback classifier (Haiku, temp=0)" → "Somatic fallback classifier (Gemini Flash, temp=0)" | Model swap |
| Friday checklist | Add: "Flutter mobile builds (iOS/Android) functional" | New deliverable |
| Component 11 | Somatic classifier: "Haiku, temp=0" → "Gemini Flash, temp=0" | Model swap |
| Component 12 | agent.py model init: references to Claude → Gemini | Direct swap |
| Component 13 | "app.py / api.py — Streamlit frontend + FastAPI backend" → "main.py (Cloud Functions entry) + flutter/ (Flutter app)" | Completely different frontend/hosting |
| Component 13 | "Stream via astream_events" → "Stream via Firestore document writes or SSE from Cloud Functions" | Different streaming mechanism |

**Unchanged**: All 6 tool briefs (1-9), verification pipeline (10), eval suite (14), all acceptance criteria. These are backend/agent concerns.

### 3. `advocate/.env.example` — REWRITE

```
# OpenEMR FHIR
OPENEMR_CLIENT_ID=
OPENEMR_CLIENT_SECRET=
OPENEMR_BASE_URL=https://demo.openemr.io
FHIR_BASE_URL=https://demo.openemr.io/apis/default/fhir/

# Google / Gemini
GOOGLE_API_KEY=

# Firebase (auto-configured in Cloud Functions; needed for local dev)
FIREBASE_PROJECT_ID=
FIREBASE_SERVICE_ACCOUNT=

# LangSmith observability
LANGCHAIN_API_KEY=
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=advocate
```

Reasoning: `ANTHROPIC_API_KEY` removed (no longer using Claude). `GOOGLE_API_KEY` added for Gemini. Firebase project config added for local development (in deployed Cloud Functions, these are auto-injected).

### 4. Root `CLAUDE.md` — TARGETED EDITS

Changes on the epic branch version:

| Location | Change | Reasoning |
|---|---|---|
| Advocate intro line | "Python/LangChain agent layer" → "Python/LangChain agent layer with Flutter frontend" | Accuracy |
| Orchestration overrides: Build commands | Add Flutter build/test commands alongside Python ones | New frontend |
| Orchestration overrides: Coder pitfalls | Add Gemini-specific pitfalls, Cloud Functions cold start | New stack concerns |
| Orchestration overrides: Coder pitfalls | Remove `ChatAnthropic` reference | No longer applicable |
| Integration surfaces | Add: Flutter app routes, Firebase Cloud Functions endpoints | New surfaces from frontend |

### 5. `.gitignore` — APPEND

```
# Flutter
flutter/.dart_tool/
flutter/.packages
flutter/build/
flutter/.flutter-plugins
flutter/.flutter-plugins-dependencies
*.dart.js
*.js_
*.js.deps
*.js.map
```

Reasoning: Flutter generates build artifacts that shouldn't be committed.

---

## What does NOT change (and why)

These are explicitly preserved to show this isn't a ground-up rewrite:

- **All 6 tool designs** — they're Python functions that call FHIR and Gemini. The frontend doesn't affect them.
- **Verification pipeline** — runs server-side in Cloud Functions. Identical.
- **FHIR client** — FHIRpy, AsyncFHIRClient, .get() patterns. Unchanged.
- **Pydantic models** — backend data contracts. Unchanged.
- **Acceptance criteria** — performance, clinical safety, FHIR integrity, prompt injection defense, observability. All unchanged.
- **Testing approach** — pytest for backend, LangSmith for evals. Flutter adds `flutter test` for frontend.
- **Python style guide** — PEP 8, ruff, 120 char lines. Unchanged.

---

## New additions (not in original files)

### Flutter project structure (reference for `advocate/CLAUDE.md`)

```
advocate/
  flutter/
    lib/
      main.dart
      screens/
        chat_screen.dart
        brief_screen.dart
      widgets/
        message_bubble.dart
        verification_badge.dart
      services/
        cloud_functions_client.dart
        auth_service.dart
      models/
        message.dart
        session.dart
    pubspec.yaml
    test/
```

### Cloud Functions entry point (`main.py` replaces `app.py` + `api.py`)

```
advocate/
  main.py               # Cloud Functions HTTP entry point
  agent.py              # AgentExecutor (unchanged role)
  ...everything else unchanged...
```

### Firestore schema (new — for session state)

```
conversations/{conversationId}
  userId: string
  createdAt: timestamp
  lastActive: timestamp
  turns: [
    { role: "user"|"assistant", content: string, timestamp: timestamp }
  ]  // last 10 turns kept in-document
  somaticState: { active: bool, reason: string }
```

Reasoning: Replaces in-memory `ConversationBufferWindowMemory`. Firestore enables cross-device session continuity (start on phone, continue on tablet). 10-turn limit matches the original k=10 window.

---

## Implementation Sequence

Single coder pass — all changes are documentation/config, no runtime code yet.

1. Rewrite `advocate/.env.example`
2. Rewrite `advocate/CLAUDE.md` (apply all changes from table above)
3. Edit `advocate/REQUIREMENTS.md` (targeted line swaps from table above)
4. Edit root `CLAUDE.md` (targeted additions to overrides section)
5. Append Flutter ignores to `.gitignore`

## Story Setup

- **Epic**: epic-002 "Advocate Implementation Bootstrap" (existing)
- **Story**: "Stack switch: update config docs for Flutter + Firebase + Gemini"
- **Agent**: quick-fixer
- **Model**: Sonnet
- **writeFiles**: `advocate/CLAUDE.md`, `advocate/REQUIREMENTS.md`, `advocate/.env.example`, `CLAUDE.md`, `.gitignore`
- **needsTesting**: false
- **needsReview**: false

## Verification

- Confirm no remaining references to Claude/Anthropic/Streamlit/Railway/FastAPI in any of the 5 files
- Confirm OpenEMR FHIR references are preserved unchanged
- Confirm all 6 tool briefs and acceptance criteria are unchanged
- Confirm Flutter and Firebase patterns are consistent across CLAUDE.md and REQUIREMENTS.md
