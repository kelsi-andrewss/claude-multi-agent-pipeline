# Plan: GitHub Actions CI/CD + Local Dev Scripts

## Context
Advocate is a Flutter (frontend) + FastAPI/Python (backend) monorepo. No CI/CD exists yet. Deployment target is Firebase Hosting (Flutter web) + Cloud Run (FastAPI). User wants:
- Lint + test on every PR
- Deploy backend to Cloud Run on merge to main
- Deploy frontend to Firebase Hosting on merge to main
- Firebase Hosting preview channels on PRs (Flutter only; staging points at prod backend)
- Local dev: Makefile with individual + combined targets

---

## Files to create

All paths relative to `/Users/kelsiandrews/gauntlet/advocate/advocate-new/`

```
.github/
  workflows/
    ci.yml           # Lint + test on PRs
    deploy.yml       # Deploy to prod on merge to main
    preview.yml      # Firebase Hosting preview channel on PRs
Makefile             # Local dev targets
```

---

## 1. Makefile (local dev)

Location: `advocate-new/Makefile`

Targets:
- `make dev-backend` — `cd` into project root, source `.env`, start uvicorn with `--reload` on port 8000
- `make dev-frontend` — `cd flutter/`, run `flutter run -d chrome` (web) or `flutter run` (mobile)
- `make dev` — run both concurrently using shell background jobs + `wait`, colored prefixes via inline `echo`
- `make test-backend` — `python -m pytest tests/ -x --tb=short`
- `make test-frontend` — `cd flutter && flutter test`
- `make lint-backend` — `ruff check .`
- `make lint-frontend` — `cd flutter && flutter analyze`
- `make build-frontend` — `cd flutter && flutter build web`
- `make help` — print target list

Notes:
- `.env` is loaded via `export $(shell cat .env | grep -v '^#' | xargs)` in make targets that need it
- Use `MAKEFLAGS += --no-print-directory` to suppress noise
- `dev` target kills background jobs on Ctrl-C via `trap`

---

## 2. CI workflow — `ci.yml`

Trigger: `pull_request` to `main`

Jobs (parallel):

**backend-ci**
- `ubuntu-latest`, Python 3.11
- `pip install -r requirements.txt`
- `ruff check .`
- `python -m pytest tests/ -x --tb=short`
- Needs secrets: `GOOGLE_API_KEY`, `FIREBASE_PROJECT_ID`, `OPENEMR_CLIENT_ID`, `OPENEMR_CLIENT_SECRET`, `OPENEMR_BASE_URL`, `FHIR_BASE_URL`, `LANGCHAIN_API_KEY` (all from GitHub Actions Secrets, passed as env vars)
- `LANGCHAIN_TRACING_V2=false` in CI to avoid noise (tests use mocks)

**frontend-ci**
- `ubuntu-latest`, Flutter stable channel
- `cd flutter && flutter pub get`
- `flutter analyze`
- `flutter test`
- No secrets needed (tests mock Firebase)

---

## 3. Deploy workflow — `deploy.yml`

Trigger: `push` to `main` (after CI passes via `needs: ci` or separate job ordering)

Jobs (sequential — backend first, then frontend since firebase.json rewrites to Cloud Run):

**deploy-backend**
- Authenticate to GCP via `google-github-actions/auth` using `GCP_SA_KEY` secret (JSON service account)
- `docker build -t gcr.io/YOUR_PROJECT_ID/advocate-api:${{ github.sha }} .`
- `docker push gcr.io/YOUR_PROJECT_ID/advocate-api:${{ github.sha }}`
- `gcloud run deploy advocate-api --image gcr.io/YOUR_PROJECT_ID/advocate-api:${{ github.sha }} --region us-central1 --platform managed --set-env-vars "..." --allow-unauthenticated`
- Env vars passed to Cloud Run via `--set-env-vars` using GitHub Secrets

**deploy-frontend** (needs: deploy-backend)
- Flutter stable channel
- `cd flutter && flutter build web --release`
- `firebase deploy --only hosting` via `firebase-tools` npm package
- Auth: `FIREBASE_SERVICE_ACCOUNT` secret passed to `FirebaseExtended/action-hosting-deploy`

---

## 4. Preview workflow — `preview.yml`

Trigger: `pull_request` (opened, synchronize, reopened)

Job:

**preview-frontend**
- Flutter stable channel
- `cd flutter && flutter build web --release`
- `FirebaseExtended/action-hosting-deploy@v0` with `channelId: pr-${{ github.event.number }}`
- Posts preview URL as PR comment automatically (built into the action)
- Auth: `FIREBASE_SERVICE_ACCOUNT` secret
- Note: Preview Flutter build points at prod backend URL (no staging Cloud Run)

---

## GitHub Secrets required

| Secret | Used by |
|---|---|
| `GCP_SA_KEY` | deploy.yml — Docker push + Cloud Run deploy |
| `FIREBASE_SERVICE_ACCOUNT` | deploy.yml + preview.yml — Firebase Hosting deploy |
| `GOOGLE_API_KEY` | ci.yml backend tests |
| `FIREBASE_PROJECT_ID` | ci.yml backend tests |
| `OPENEMR_CLIENT_ID` | ci.yml backend tests |
| `OPENEMR_CLIENT_SECRET` | ci.yml backend tests |
| `OPENEMR_BASE_URL` | ci.yml backend tests |
| `FHIR_BASE_URL` | ci.yml backend tests |
| `LANGCHAIN_API_KEY` | ci.yml backend tests |
| `GCP_PROJECT_ID` | deploy.yml (used in image tag + gcloud command) |
| `CLOUD_RUN_REGION` | deploy.yml (defaults to us-central1) |

---

## Key decisions

- `LANGCHAIN_TRACING_V2=false` in CI so tests don't push traces for mock runs
- Backend deploy uses Container Registry (`gcr.io`) — can switch to Artifact Registry later
- Flutter preview builds point at prod backend (not a separate staging Cloud Run) — simpler, acceptable for UI-only reviews
- `FirebaseExtended/action-hosting-deploy` handles both prod deploy and preview channels; single action, different `channelId`
- No Docker layer caching in v1 — add `--cache-from` later if build times are painful
- Service account for GCP needs roles: `Cloud Run Admin`, `Storage Admin`, `Service Account User`

---

## Verification

1. Local: `make dev` starts both services; confirm backend at http://localhost:8000/health, Flutter at http://localhost:5000
2. CI: Open a PR → both `backend-ci` and `frontend-ci` jobs appear in GitHub Checks
3. Preview: PR gets a Firebase Hosting preview URL comment within ~3 min
4. Deploy: Merge to main → Cloud Run service updates, Firebase Hosting updates
