---
name: briefing
description: >
  Gemini synthesis + Claude critique + scope check + decision recording.
  Reads research artifacts (.research-<slug>.json), walks prev pointers to
  load clarify data, writes human-readable presearch briefing (presearch/<slug>.md).
  Standalone invocable. Use when the user says "/briefing <slug>",
  "/briefing --research path/to/.research-foo.json", or
  "/briefing --refine presearch/existing.md".
args:
  - name: args
    type: string
    description: >
      <slug> (looks up .research-<slug>.json in cwd),
      --research path/to/.research-foo.json (explicit path),
      or --refine presearch/existing.md (update existing briefing with new research).
---

# Briefing Skill Invoked

User has requested: `/briefing {{args}}`

---

## Step 1: Parse args and load artifacts

Parse `{{args}}` into mode, flags, and input path:

**Flags** (strip from args after detection):
- `--deep` is NOT a flag for this skill directly — but check the research artifact's metadata for `deep: true` (set upstream). If present, run extra Gemini passes in Step 5.

**Mode detection** (after stripping flags):
1. **Slug mode** (default): remaining arg is a plain string. Look for `.research-<slug>.json` in cwd. Error if not found:
   ```
   Error: No .research-<slug>.json found in current directory. Run /research first, or use --research <path> to specify the artifact.
   ```
2. **Explicit research mode**: `--research <path>` — read the specified file directly. Extract slug from the artifact's `slug` field.
3. **Refine mode**: `--refine <path>` — path should be an existing `presearch/<slug>.md`. Read the existing briefing AND the corresponding `.research-<slug>.json` (extract slug from the briefing filename). Both must exist.

**Load artifacts:**
- Read the `.research-<slug>.json` file. Validate:
  - Has `"skill": "research"` field
  - Has non-empty `data` field
  - Error with actionable message if validation fails:
    ```
    Error: Artifact is not a research output (skill: "<actual>"). Expected skill: "research". Did you mean to pass a different file?
    ```
- Walk the `prev` pointer: if the research artifact has a `prev` array containing a path to `.clarify-<slug>.json`, and that file exists, read it. Extract:
  - `data.decisions` — resolved Q&A decisions and constraints
  - `data.constraints` — hard constraints from clarify phase
  - If the clarify file doesn't exist, continue without it — clarify is optional.

---

## Step 2: Load stack constraints

Check the current working directory for project markers:
- `package.json`, `pubspec.yaml`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `CLAUDE.md`

If found: read relevant files to extract stack info (framework, language, existing dependencies, patterns). This becomes hard constraints for synthesis.

If the research artifact's `data` already contains stack constraints (from upstream /research or /clarify), use those instead of re-scanning. Avoid duplicating constraint detection.

If nothing found and no upstream constraints: greenfield mode.

---

## Step 3: Synthesize with Gemini

1. Load Gemini: `ToolSearch: select:mcp__gemini__gemini_chat`
2. Call `gemini_chat` with ALL accumulated context (research data, clarify decisions, stack constraints, web research results from the research artifact) in a single prompt:

```
Given this research, produce a structured technical briefing. Include:
- Concrete API shapes (not guesses)
- Exact package names and versions
- Architecture recommendation with tradeoffs
- For greenfield projects: directory structure with purpose annotations, exact bootstrap/scaffold CLI command, and config choices
- Shared interfaces/types that multiple features will import — include file paths and which features use them (these determine story ordering)
- Data model with entities and relationships
- Dependency list
- Gotchas
- Required environment variables (name + what service needs it)
- For each feature: include the key file paths it will create/modify (e.g. "User auth — src/lib/auth.ts, src/app/login/page.tsx")
- For greenfield: a Bootstrap item (feature 0) listing the scaffold command, shared type files to create, and initial configs
- Recommended test framework for the stack (e.g. vitest for Vite projects, jest for CRA, pytest for Python) — Bootstrap will set this up
- Coding patterns for coder consistency: HTTP client choice, error handling approach, validation library, naming conventions. These go in ### Patterns and are REFERENCE MATERIAL for plan-stories coders — they inform how coders write code for this project. They are NOT a CLAUDE.md template. Do NOT mention creating a project CLAUDE.md from these patterns.
- Risk assessment: for each major technical choice or external dependency, rate likelihood and impact (high/med/low) and state a mitigation. Focus on: API deprecation, scaling bottlenecks, vendor lock-in, breaking changes, cost surprises.
- Cost projections: estimate monthly operational costs at 3 tiers (1K, 10K, 100K users/month) covering compute, database, storage, third-party APIs, and managed services. Identify the primary cost drivers first, then use published pricing. Provide ranges ("$5-15/mo"), not single numbers. Flag rough estimates. For development: estimate complexity per MVP feature using T-shirt sizes (S/M/L/XL) — not hours or days.
- Deployment: for web apps, always include a publicly accessible deployment path. Recommend hosting platform with reasoning. Specify: build command, deploy command or CI/CD approach, domain/URL strategy, platform-specific config files, and where production secrets are stored. Bootstrap (feature 0) should create deployment config files — not provision infrastructure. For non-web projects (CLI tools, libraries, internal scripts), skip or adapt.

Flag anything you're uncertain about.

Also assess complexity: estimate feature count. If >5 features, suggest MVP phasing — what ships first vs what can wait.

Research data: <research artifact data field>
Clarify decisions: <clarify decisions if loaded, or "none">
Stack constraints: <constraints from Step 2>
Web research results: <web_results from research artifact data, if present>
```

**For `--refine` mode**: include the existing briefing content and instruct Gemini to update rather than regenerate:

```
Here's an existing technical briefing and updated research. Produce an updated briefing.
Preserve the existing structure. Update sections where the new research provides better information.
Do not regenerate sections where the existing content is still accurate.

Existing briefing:
<briefing contents>

New research data: <research artifact data>
```

---

## Step 4: Build Test Strategy

Extract `testable_assertions` from the research artifact's `data` field (if present).

Combine with gotchas and API edge cases from Gemini synthesis output (Step 3).

Build the `## Test Strategy` section with four subsections:

- **Critical paths**: from research testable assertions. These are the core behaviors that must work. Example: "Auth flow completes end-to-end", "Data persists across page reload".
- **Edge cases**: from gotchas section. Rate limits, error responses, empty states, boundary values.
- **Integration boundaries**: from API shapes. What can break between services — auth token expiry, webhook payload format changes, SDK version mismatches.
- **What NOT to test**: wiring (route configs, component composition, dependency injection) — it fails obviously. Types — the type system catches these. Don't duplicate what the compiler already verifies.

This section feeds into /plan-stories so test stories are informed by research, not invented by Gemini in a vacuum.

---

## Step 5: Claude critique + scope check

Cross-check Gemini's synthesis:

### 5a. Factual verification
- Are the APIs real? Do the package names exist? Are there contradictions between different sections?
- Do recommendations respect stack constraints from Step 2? Stack conflicts are failures — reject and find alternatives, don't ship a briefing with incompatible recommendations.
- Are cost estimates grounded in real pricing? Flag any that seem fabricated or wildly off.
- Are risks actionable? Each risk needs a concrete mitigation, not "monitor closely."
- Does the deployment path work? Is the recommended platform compatible with the stack (e.g. don't recommend Vercel for a Python-only backend)?

### 5b. Deep mode (optional)
If the research artifact metadata contains `deep: true`: run a second `gemini_chat` pass on uncertain areas identified in 5a. Feed the specific questions back to Gemini with the original research context.

### 5c. Scope assessment
If >5 features in the synthesis:
- Mark features as MVP / Phase 2 / Cut in the `## Features` section
- Add reasoning for each phase assignment
- Criteria for phasing:
  - **MVP**: core value proposition, hard dependencies of other features, infrastructure setup
  - **Phase 2**: enhancement features, nice-to-haves that don't block core flow
  - **Cut**: features that add significant complexity without proportional value, or that can be reconsidered after MVP feedback

Write the phasing directly into the briefing output. This skill does NOT gate on user input — it writes its assessment and moves on. The user reviews the briefing after.

---

## Step 6: Write briefing

**File path:**
- Default: `presearch/<slug>.md` (slug from the research artifact's `slug` field)
- `--refine` mode: update the existing file in place. Preserve `## Constraints` and `## Decisions` sections unless the research explicitly provides updated information for them.

**Briefing structure:**

```markdown
# <Title>

## Overview
<1-2 paragraph description of what we're building and why>

## Summary
<Under 2000 chars. Readable overview: what we're building, core approach, key tech decisions, stack. Stored as epic description in DB. Ship passes the full briefing to Gemini separately — Summary doesn't need structural details.>

## Features
### MVP
0. Bootstrap: <scaffold command> + install ALL dependencies from ## Dependencies + create shared types/interfaces from ## Shared Interfaces + create `.env.example` from ## Environment + set up test config (<test framework>) + configure deployment from ## Deployment + configure <configs> (greenfield only — omit for existing projects)
1. <Feature one — clear, scoped, shippable. Include target file paths where possible>
2. <Feature two — same format>

### Phase 2 (optional)
3. <Feature that can wait — include reasoning for deferral>

### Cut (optional)
4. <Feature explicitly descoped — include reason for cutting>

## Technical Research

### APIs & Services
- <Service name>: <what it does, key endpoints/methods, auth pattern>
- SDK: `<package-name>` — <version, install command>

### Architecture
- <Framework/pattern decisions with reasoning>

### Patterns
- **HTTP client**: <fetch | axios | ky> — used for all API calls
- **Error handling**: <pattern, e.g. "try/catch with custom AppError class, never swallow errors">
- **Validation**: <zod | yup | joi | manual> — used at all API boundaries
- **State management**: <pattern if applicable>
- **Naming**: <conventions>
- (Include only patterns relevant to the stack. Skip sections that don't apply.)
- (These are reference material for plan-stories coders. They inform coding style and consistency across stories.)

### Project Structure (greenfield only — skip for existing projects)
```
<root>/
  src/
    <directory>/ — <purpose>
  <config files>
```
- Bootstrap command: `<exact CLI scaffold command>`
- Config choices: <non-default config decisions>

### Shared Interfaces
- `<path/to/types.ts>`: <Entity> — <key fields> (used by features: 1, 3)
- `<path/to/utils.ts>`: <helper> — <what it does> (used by features: 2, 4)
- (These create implicit ordering — features using shared interfaces depend on Bootstrap)

### Data Model
- <Entity>: <key fields, relationships>
- (Skip if no persistence layer)

### Dependencies
- `<package>` — <why needed>

### Gotchas
- <Known pitfalls, rate limits, breaking changes, version incompatibilities>

### Risks
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| <risk description> | High/Med/Low | High/Med/Low | <concrete mitigation> |

### Cost Estimate
**Development complexity:**
| Feature | Size | Notes |
|---------|------|-------|
| 0. Bootstrap | S | <scaffolding, config> |
| 1. <Feature> | M | <what drives complexity> |

**Monthly operational costs:**
| Component | 1K users | 10K users | 100K users |
|-----------|----------|-----------|------------|
| Compute | <range> | <range> | <range> |
| Database | <range> | <range> | <range> |
| Third-party APIs | <range> | <range> | <range> |
| **Total** | **<range>** | **<range>** | **<range>** |

- Skip for internal tools or projects where cost isn't a factor

### Deployment
- **Platform**: <recommendation> — <why this fits the stack>
- **Build**: `<build command>`
- **Deploy**: `<deploy command or CI/CD approach>`
- **URL**: <domain strategy>
- **Config**: <platform-specific config files>
- **Secrets**: <where production secrets are stored>
- For non-web projects: adapt or skip

## Test Strategy

### Critical paths
- <Core behaviors from research testable assertions>

### Edge cases
- <From gotchas: rate limits, error responses, empty states, boundary values>

### Integration boundaries
- <From API shapes: what can break between services>

### What NOT to test
- Wiring (route configs, component composition, dependency injection) — fails obviously
- Types — the type system catches these
- Don't duplicate what the compiler already verifies

## Environment
- `<ENV_VAR_NAME>` — <what service/feature needs it> (required | optional)
- Skip if no external services

## Decisions
- **<Decision area>**: <Choice> — <reasoning> (user decision | recommended + agreed | Claude override)

## Constraints
- <Hard requirements: platform, language, existing codebase patterns>
- <Existing stack detected>
- <Things explicitly out of scope>

## Reference
- <URL or doc snippet that informed a decision>
```

---

## Step 7: Record decisions

For each tech decision listed in the briefing's `## Decisions` section:

1. Load: `ToolSearch: select:mcp__gemini__pm_add_decision`
2. Call `pm_add_decision(title=<decision area>, decision=<choice>, context=<reasoning>)`
3. Load: `ToolSearch: select:mcp__openmemory__openmemory_store`
4. Shadow to OpenMemory: `openmemory_store(content="<decision area>: <choice> — <reasoning>", tags=["decision", "<decision-id>"], user_id="proj:<project>")`

Where `<project>` is derived from the cwd project name.

---

## Step 8: Report

Print:
- The briefing file path
- Feature count and scope assessment (MVP count, Phase 2 count, Cut count)
- If >5 features: explicitly note that MVP phasing was applied
- Number of decisions recorded

Do NOT prompt to ship. That is the orchestrator's job (Phase 2 rewiring). Just report what was written.

---

## Test Strategy

### How to verify this skill works

**Critical paths:**
- Given a valid `.research-<slug>.json`, the skill writes `presearch/<slug>.md` with all required sections
- Given `prev` pointers in the research artifact, clarify data is loaded and incorporated
- Given `testable_assertions` in research data, `## Test Strategy` section appears with all four subsections
- Given >5 features, phasing is applied (MVP / Phase 2 / Cut with reasoning)

**Edge cases:**
- Research artifact missing or malformed: actionable error message, not a stack trace
- Clarify file referenced in `prev` but doesn't exist: skill continues without it
- `--refine` mode: existing Constraints and Decisions sections preserved unless explicitly changed
- `--research` with explicit path: slug extracted from artifact, not from arg parsing
- Empty `testable_assertions`: Test Strategy section still appears with edge cases from gotchas

**Integration boundaries:**
- Artifact contract: reads `slug`, `scope`, `prev`, `skill`, `data` fields per refs/skill-graph.md
- Output feeds /plan-stories: briefing must contain ## Features, ## Test Strategy, ## Technical Research
- Decisions recorded via pm_add_decision + OpenMemory shadow

**What NOT to test:**
- Tool loading (ToolSearch calls) — fails obviously if tools don't exist
- Gemini prompt formatting — not testable in isolation, verify by running the skill
- File I/O mechanics — use the skill end-to-end instead
