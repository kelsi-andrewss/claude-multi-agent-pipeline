---
name: briefing
description: >
  Gemini synthesis + Claude critique + scope check + decision recording.
  Reads scout artifacts (presearch/.scout-<slug>.json), walks prev pointers to
  load clarify, research, and scope data, writes human-readable presearch briefing
  (presearch/<slug>.md). Standalone invocable. Use when the user says "/briefing <slug>",
  "/briefing --scout path/to/.scout-foo.json", or
  "/briefing --refine presearch/existing.md".
args:
  - name: args
    type: string
    description: >
      <slug> (looks up presearch/.scout-<slug>.json),
      --scout path/to/.scout-foo.json (explicit path),
      --research path/to/.research-foo.json (backward compat, treated as --scout),
      or --refine presearch/existing.md (update existing briefing with new research).
---

# Briefing Skill Invoked

User has requested: `/briefing {{args}}`

---

## Step 1: Parse args and load artifacts

Parse `{{args}}` into mode, flags, and input path:

**Flags** (strip from args after detection):
- `--deep` is NOT a flag for this skill directly — but check the scout artifact's metadata for `deep: true` (set upstream). If present, run extra Gemini passes in Step 5.

**Mode detection** (after stripping flags):
1. **Slug mode** (default): remaining arg is a plain string. Look for `presearch/.scout-<slug>.json`. Error if not found:
   ```
   Error: No .scout-<slug>.json found. Run /scout first, or use --scout <path>.
   ```
2. **Explicit scout mode**: `--scout <path>` — read the specified file directly. Extract slug from the artifact's `slug` field. Backward compat: `--research <path>` is also accepted and treated identically.
3. **Refine mode**: `--refine <path>` — path should be an existing `presearch/<slug>.md`. Read the existing briefing AND the corresponding `presearch/.scout-<slug>.json` (extract slug from the briefing filename). Both must exist.

**Load artifacts:**
- Read the `presearch/.scout-<slug>.json` file. Validate:
  - Has `"skill": "scout"` field (also accept `"skill": "research"` for backward compat during transition)
  - Has non-empty `data` field
  - Error with actionable message if validation fails:
    ```
    Error: Artifact is not a scout output (skill: "<actual>"). Expected skill: "scout". Did you mean to pass a different file?
    ```
- **Walk the `prev` chain** — the chain is now longer than before. From the scout artifact:
  1. Read `prev` array. It may contain paths to `.clarify-<slug>.json` and/or `presearch/.research-<slug>.json`.
  2. **Load clarify artifact**: if a `.clarify-<slug>.json` path is in `prev` and the file exists, read it. Extract:
     - `data.decisions` — resolved Q&A decisions and constraints
     - `data.constraints` — hard constraints from clarify phase
     - If the clarify file doesn't exist, continue without it — clarify is optional.
  3. **Load knowledge synthesis artifact**: if a `presearch/.research-<slug>.json` path is in `prev` (or in clarify's own `prev`), and the file exists, read it. Extract:
     - `data.synthesized_findings` — domain knowledge for Gemini synthesis
     - `data.citations` — source attribution to preserve in the briefing
     - `data.conflicts` — contradictions to surface in the briefing
     - If the research file doesn't exist, continue without it — research is optional.
  4. **Load scope artifact**: walk further up via research's `prev` (or clarify's `prev` if research was skipped). If `.scope-<slug>.json` exists, read it. Extract:
     - `data.stack_detected` — detected project stack
     - `data.in_scope` — must-include items
     - `data.out_of_scope` — explicitly excluded items
     - If the scope file doesn't exist, continue without it — scope context is optional.

---

## Step 2: Load stack constraints

Check the current working directory for project markers:
- `package.json`, `pubspec.yaml`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `CLAUDE.md`

If found: read relevant files to extract stack info (framework, language, existing dependencies, patterns). This becomes hard constraints for synthesis.

If the scout artifact's `data` already contains stack constraints (from upstream /scope, /research, or /clarify via prev chain), use those instead of re-scanning. Avoid duplicating constraint detection.

If nothing found and no upstream constraints: greenfield mode.

---

## Step 3: Synthesize with Gemini

1. Load Gemini: `ToolSearch: select:mcp__gemini__analyze`
2. Call `analyze` with ALL accumulated context (scout implementation data, knowledge synthesis from research if in chain, clarify decisions, scope context, stack constraints) in a single prompt:

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

Synthesize a Problem Statement from upstream data (scope artifact's problem/why/end_goal fields,
clarify decisions, research findings). Answer these questions explicitly:
1. What problem is being fixed? (what's broken, missing, or suboptimal)
2. Why is this problem being fixed? (consequence of inaction)
3. Why is this problem integral to the project? (how it connects to the project's purpose)
4. What is the end goal? (what "done" looks like — not "tests pass" but what the user can do)
If any of these can't be answered from upstream data, flag them as gaps.

Assess blast radius: for each major change, what could break? Trace downstream dependencies,
callers, consumers, runtime contracts. Frame as risk, not just dependency listing.

Define success criteria: how will we know this worked? Not test cases — observable outcomes.
What can the user do after this ships that they couldn't before? What metrics or behaviors change?

Flag anything you're uncertain about.

Also assess complexity: estimate feature count. If >5 features, suggest MVP phasing — what ships first vs what can wait.

If research conflicts exist, address each one: evaluate the sources, pick a position if possible, or surface both sides with your assessment.

Scout implementation data: <scout artifact data field (findings, api_shapes, testable_assertions)>
Knowledge synthesis: <research artifact data.synthesized_findings if in chain, or "none — research was skipped">
Research conflicts: <research artifact data.conflicts if in chain, or "none">
Research citations: <research artifact data.citations if in chain, or "none">
Scope context: <scope artifact data (in_scope, out_of_scope, stack_detected) if in chain, or "none">
Clarify decisions: <clarify decisions if loaded, or "none">
Stack constraints: <constraints from Step 2>
```

**For `--refine` mode**: include the existing briefing content and instruct Gemini to update rather than regenerate:

```
Here's an existing technical briefing and updated research. Produce an updated briefing.
Preserve the existing structure. Update sections where the new research provides better information.
Do not regenerate sections where the existing content is still accurate.

Existing briefing:
<briefing contents>

New scout data: <scout artifact data>
Knowledge synthesis: <research artifact data if in chain, or "none">
```

---

## Step 4: Build Test Strategy

Extract `testable_assertions` from the scout artifact's `data` field (if present).

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
If the scout artifact metadata contains `deep: true`: run a second `analyze` pass on uncertain areas identified in 5a. Feed the specific questions back to Gemini with the original scout and research context.

### 5c. Problem statement gate
Check whether the Problem Statement section answers all four questions. If any are missing or vague:
- If upstream scope artifact had `problem`, `why`, `end_goal` fields: use them.
- If clarify artifact addressed project-integral reasoning: use it.
- If STILL can't answer a question: flag it in the briefing as `**[UNANSWERED]**` with a note explaining what upstream data was missing. Do NOT invent answers — a flagged gap is better than a fabricated justification.

### 5d. Completeness and blast radius check
Verify the Blast Radius section against scout's completeness and blast_radius data:
- If scout reported `best-effort` confidence, surface the blind spots prominently.
- If scout's blast_radius identified runtime contracts, ensure they appear in the briefing.
- If Success Criteria are generic ("it works", "tests pass"), rewrite them to be observable and specific.

### 5e. Scope assessment
If >5 features in the synthesis:
- Mark features as MVP / Phase 2 / Cut in the `## Features` section
- Add reasoning for each phase assignment
- Criteria for phasing:
  - **MVP**: core value proposition, hard dependencies of other features, infrastructure setup
  - **Phase 2**: enhancement features, nice-to-haves that don't block core flow
  - **Cut**: features that add significant complexity without proportional value, or that can be reconsidered after MVP feedback

Write the phasing directly into the briefing output. This skill does NOT gate on user input for phasing — it writes its assessment and moves on.

---

## Step 5.5: Conflict resolution check

Before writing, scan the assembled briefing content for unresolved conflicts or gaps:

- **Clarify-vs-scout contradictions**: a clarify decision says X, but scout findings imply Y (e.g., clarify decided "use REST" but scout found the project uses tRPC exclusively)
- **Research conflicts**: the research artifact surfaced conflicting sources that were not resolved in Step 5
- **Missing critical info**: a required briefing section (Problem Statement, Features, Dependencies) has no content or only placeholder text
- **Scope mismatches**: scope artifact's `out_of_scope` items appear in the Features list, or `in_scope` items are missing

**If clean** (no conflicts, no gaps): proceed silently to Step 6.

**If conflicts or gaps found**: present them to the user with suggested resolutions:

```
Before writing the briefing, I found <N> unresolved conflicts:

1. **<Area>**: Clarify decided <X>, but scout found <Y>.
   Suggested resolution: <recommendation with reasoning>

2. **<Area>**: <gap description>
   Suggested resolution: <recommendation>

How should I resolve these?
```

Wait for user response. Incorporate their decisions into the briefing content.

If the user's response surfaces one new issue, do one follow-up. Briefing is synthesis, not discovery — keep this light. After the follow-up (or if no new issues), proceed to Step 6.

---

## Step 6: Write briefing

**File path:**
- Default: `presearch/<slug>.md` (slug from the scout artifact's `slug` field)
- `--refine` mode: update the existing file in place. Preserve `## Constraints` and `## Decisions` sections unless the scout or research data explicitly provides updated information for them.

**Briefing structure:**

```markdown
# <Title>

## Problem Statement
**What problem?** <what's broken, missing, or suboptimal today>
**Why fix it?** <consequence of NOT doing this — what breaks, stalls, or degrades>
**Why integral?** <how this connects to the project's core purpose — why this isn't optional>
**End goal:** <what "done" looks like — the observable outcome, not "tests pass">

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

## Blast Radius
For each major write target or change area:
- **<file or component>**: <what depends on it, what could break, downstream effects>
- Confidence: <exhaustive | best-effort — from scout completeness data>
- If scout reported blind spots, list them here

## Success Criteria
How we'll know this worked — observable outcomes, not test results:
- <What the user can do after this ships that they couldn't before>
- <What behavior or metric changes>
- <What failure mode is eliminated>

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
- Given a valid `presearch/.scout-<slug>.json`, the skill writes `presearch/<slug>.md` with all required sections
- Given `prev` pointers in the scout artifact, clarify data is loaded and incorporated
- Given research knowledge artifact in chain, synthesized_findings incorporated into Gemini synthesis prompt
- Given conflicts in research data, briefing surfaces them with resolution or both sides
- Given research citations in chain, briefing preserves source attribution
- Given scope artifact in chain, stack_detected/in_scope/out_of_scope inform constraints
- Given `testable_assertions` in scout data, `## Test Strategy` section appears with all four subsections
- Given >5 features, phasing is applied (MVP / Phase 2 / Cut with reasoning)

**Edge cases:**
- Scout artifact missing or malformed: actionable error message, not a stack trace
- Clarify file referenced in `prev` but doesn't exist: skill continues without it
- Research file referenced in chain but doesn't exist: skill continues without it
- Scope file referenced in chain but doesn't exist: skill continues without it
- `--refine` mode: existing Constraints and Decisions sections preserved unless explicitly changed
- `--scout` with explicit path: slug extracted from artifact, not from arg parsing
- `--research` flag accepted for backward compat, treated as `--scout`
- Old artifacts with `skill: "research"` accepted as scout artifacts during transition
- Empty `testable_assertions`: Test Strategy section still appears with edge cases from gotchas

**Integration boundaries:**
- Artifact contract: reads `slug`, `scope`, `prev`, `skill`, `data` fields per refs/artifact-contract.md
- Extended prev chain: scout -> clarify -> research -> scope (walks recursively)
- Output feeds /plan-stories: briefing must contain ## Features, ## Test Strategy, ## Technical Research
- Decisions recorded via pm_add_decision + OpenMemory shadow

**What NOT to test:**
- Tool loading (ToolSearch calls) — fails obviously if tools don't exist
- Gemini prompt formatting — not testable in isolation, verify by running the skill
- File I/O mechanics — use the skill end-to-end instead
