# Plan: Symptom Writer Tool + Dev/Prod Env Switching

## Context
Two related changes:
1. The agent is currently read-only against OpenEMR FHIR. When a patient reports a symptom (e.g. "I have brain fog"), the agent should write that back as a FHIR Observation resource — making it persistent and queryable by other tools.
2. The app hardcodes `load_dotenv()` with no argument, always reading `.env`. Two environment files exist (`.env.dev`, `.env.prod`) but there's no mechanism to select between them. The fix: read `ENV` env var at startup, load the correct file.

The agent does NOT diagnose — it records patient-reported symptoms only. FHIR Observation with `category=survey` is the correct resource for self-reported data.

---

## Part 1: Dev/Prod Env Switching

### Files to change
- `advocate/main.py` — replace bare `load_dotenv()` with env-aware load
- `advocate/seed_patient.py` — same replacement
- `Makefile` (project root) — update `dev` and `prod` targets to pass `ENV=dev` / `ENV=prod`

### Implementation

**`main.py` and `seed_patient.py`** — replace:
```python
load_dotenv()
```
with:
```python
_env = os.environ.get("ENV", "dev")
load_dotenv(f".env.{_env}", override=True)
```

This reads `ENV` from the shell environment (set by Makefile or Cloud Run config), falls back to `dev` if unset, and loads `.env.dev` or `.env.prod` accordingly. Never reads the file directly in code — `load_dotenv` is the only access point.

**`Makefile`** — ensure dev and prod targets set `ENV`:
```makefile
dev-backend:
    ENV=dev uvicorn advocate.main:app --reload --port 8000

prod:
    ENV=prod uvicorn advocate.main:app --port 8000
```
(Exact target names may vary — coder reads Makefile first and updates the correct targets.)

**Cloud Run / prod deploy**: Set `ENV=prod` as a platform env var in Cloud Run config. The `.env.prod` file is not present in the container — Cloud Run uses its own env var injection, so `load_dotenv` will find no file and fall back gracefully to already-set vars. This is correct behavior.

### Constraint
Never read `.env.dev` or `.env.prod` directly in code. `load_dotenv()` is the only access mechanism. Do not `open()`, `cat`, or `read()` those files anywhere.

---

## Part 2: Symptom Writer Tool

### Files to change
- `advocate/models.py` — add `SymptomWriterInput`, `SymptomWriterOutput`
- `advocate/fhir_client.py` — add `post_resource()` method to `FHIRService`
- `advocate/tools/symptom_writer.py` — new tool file
- `advocate/agent.py` — register the new tool

### Models (`models.py`)

```python
class SymptomWriterInput(BaseModel):
    symptom: str = Field(description="Patient-reported symptom in plain language, e.g. 'brain fog', 'fatigue'")
    onset_date: str = Field(description="Approximate onset date in YYYY-MM-DD format")
    severity: str = Field(default="moderate", description="mild | moderate | severe")

class SymptomWriterOutput(BaseModel):
    observation_id: str
    symptom: str
    recorded_at: str
    status: str  # "created" | "error"
    message: str
```

### FHIRService (`fhir_client.py`)

Add one method — follows exact same auth pattern as `_get()`:
```python
async def post_resource(self, resource_type: str, payload: dict) -> dict:
    token = await self._get_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{self.base_url}/{resource_type}",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/fhir+json",
            },
        )
    if response.status_code in (401, 403):
        raise FHIRAuthError(f"FHIR POST unauthorized: {resource_type}")
    if response.status_code not in (200, 201):
        raise RuntimeError(f"FHIR POST {resource_type} failed: {response.status_code} {response.text}")
    return response.json()
```

### Tool (`tools/symptom_writer.py`)

```python
async def run_symptom_writer(
    symptom: str,
    onset_date: str,
    severity: str,
    patient_id: str,
    fhir_service: FHIRService,
) -> dict:
    payload = {
        "resourceType": "Observation",
        "status": "preliminary",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "survey"}]}],
        "code": {"text": symptom},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": onset_date,
        "valueString": f"Patient-reported: {symptom} (severity: {severity})",
        "note": [{"text": "Recorded by Advocate AI from patient self-report"}],
    }
    result = await fhir_service.post_resource("Observation", payload)
    return SymptomWriterOutput(
        observation_id=result.get("id", "unknown"),
        symptom=symptom,
        recorded_at=onset_date,
        status="created",
        message=f"Symptom '{symptom}' recorded successfully.",
    ).model_dump()
```

### Agent registration (`agent.py`)

Add a `make_symptom_writer_tool(session_state, fhir_service)` factory function (same closure pattern as `make_symptom_timeline_tool`) so it has access to `patient_id` and `fhir_service` from session state. Register it in `registered_tools`.

Description for the tool: `"Record a patient-reported symptom to their FHIR record as an Observation. Use when the patient mentions a new symptom during conversation."`

---

## Verification

1. **Env switching**: `ENV=dev python -c "import os; from dotenv import load_dotenv; _e=os.environ.get('ENV','dev'); load_dotenv(f'.env.{_e}'); print(os.environ.get('OPENEMR_BASE_URL'))"` — should print dev URL. Repeat with `ENV=prod`.
2. **Symptom writer**: Start backend with `ENV=dev make dev-backend`, send message "I've had brain fog for the past week", verify agent calls `symptom_writer` tool, check OpenEMR FHIR for new Observation resource under the patient.
3. **Ruff**: `ruff check advocate/` must pass with no errors.
