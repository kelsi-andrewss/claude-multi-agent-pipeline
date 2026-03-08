---
name: presearch
description: "Deep technical research that produces a structured briefing for /ship. Investigates APIs, frameworks, dependencies, and architecture before committing to stories. Use when the user says \"/presearch <topic>\", \"/presearch path/to/requirements.md\", \"/presearch presearch/existing-briefing.md\", or \"/presearch --deep <topic>\"."
args:
  - name: args
    type: string
    description: "Topic (quoted string or free text), requirements file path, presearch briefing path (refine mode), or flags (--deep, --quick, --no-ship)."
---

# Presearch Skill Invoked

User has requested: `/presearch {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine mode and flags:

**Flags** (strip from args after detection):
- `--deep` → extra research rounds (double web search/fetch budget)
- `--quick` → skip Q&A phase, go straight to research
- `--no-ship` → produce the doc but don't prompt to ship

**Mode detection** (after stripping flags):
1. **Refine mode**: remaining arg is a path starting with `presearch/` and ending `.md`, and the file exists → read it as existing briefing. Any text after the path is the refinement instruction.
2. **Requirements mode**: remaining arg is a path ending `.md` (not under `presearch/`), and the file exists → read it as seed requirements doc.
3. **Idea mode**: everything else → treat as the topic/idea.

---

## Step 1: Existing project detection

Scan the current working directory for project markers:
- `package.json`, `pubspec.yaml`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `CLAUDE.md`

If found: read the relevant files to extract stack info (framework, language, existing dependencies, patterns). This becomes a hard constraint — all recommendations must fit the existing stack. Store for inclusion in `## Constraints`.

If nothing found: greenfield mode, no stack constraints.

---

## Step 2: Q&A (skip if `--quick` or refine mode)

Scale depth to input clarity.

1. Load Gemini: `ToolSearch: select:mcp__gemini__gemini_chat`
2. Call `gemini_chat` with prompt:
   ```
   Analyze this project description. Identify:
   (a) ambiguities that need clarification
   (b) missing requirements implied but not stated
   (c) technical decision points where multiple valid approaches exist

   For each decision point, present 2-3 options with tradeoffs.
   Scale your analysis to the input — a clear, specific request needs fewer questions than a vague idea.

   <input contents>
   ```
3. Review Gemini's output. If no ambiguities and ≤1 decision point, skip Q&A — input was clear enough. Otherwise, batch into a single `AskUserQuestion`:

   ```
   I read through the requirements. A few things to resolve before research:

   **Clarifications:**
   1. <ambiguity> — do you mean X or Y?
   2. <gap> — the doc doesn't mention Z. Should we include it?

   **Tech decisions:**
   3. <Decision area>: <Option A> (pro, con) vs <Option B> (pro, con). I'd pick <recommendation> — <reasoning>.
   ```

4. Wait for user response. Record each decision.
5. If answers surface new ambiguities, ask ONE more round (max 2 rounds total).
6. Proceed to Step 3 with the resolved spec.

---

## Step 3: Seed research with Gemini

1. Load Gemini if not already loaded: `ToolSearch: select:mcp__gemini__gemini_chat`
2. Call `gemini_chat` with a research-focused prompt:
   ```
   You are a technical researcher. Given a project idea, identify:
   - Key APIs/services needed (with endpoint shapes, auth flows)
   - SDK packages (exact names, versions, install commands)
   - Architecture patterns and framework recommendations
   - Data models (entities, relationships, key fields)
   - Known gotchas (rate limits, breaking changes, version incompatibilities)

   Be specific — include real endpoint shapes, not guesses. Flag anything uncertain.

   Topic: <topic + file contents + resolved decisions from Step 2 + stack constraints from Step 1>
   ```

**Refine mode**: include the existing briefing content and the user's refinement request:
   ```
   Here's an existing technical briefing and a request to update it.
   Research the specific changes requested and produce an updated briefing.

   Existing briefing:
   <briefing contents>

   Refinement request: <user's instruction>
   ```

---

## Step 4: Web research

Extract search queries from Gemini's response — focus on the most critical unknowns (API docs, SDK docs, framework guides).
- If cost estimates are needed (non-internal project): include 1-2 searches for current pricing of recommended hosting/database/API vendors (e.g. "Vercel pricing 2026", "Supabase pricing tiers").

1. Load web tools: `ToolSearch: select:WebSearch,WebFetch`
2. Run 2-4 `WebSearch` calls in parallel for the most important topics.
3. `WebFetch` the top results (prefer official docs) — max 3 fetches.
4. If `--deep`: double the budget (4-8 searches, up to 6 fetches).
5. If any searches or fetches fail, continue with whatever succeeded. Flag gaps in Step 7 output with:
   ```
   > Warning: web research incomplete for [topic] — details from model knowledge, verify before shipping
   ```

---

## Step 5: Synthesize with Gemini

Call `gemini_chat` with ALL accumulated context in a single prompt:

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
- Coding patterns for coder consistency: HTTP client choice, error handling approach, validation library, naming conventions. These go in ## Architecture > ### Patterns and become the project CLAUDE.md.
- Risk assessment: for each major technical choice or external dependency, rate likelihood and impact (high/med/low) and state a mitigation. Focus on: API deprecation, scaling bottlenecks, vendor lock-in, breaking changes, cost surprises.
- Cost projections: estimate monthly operational costs at 3 tiers (1K, 10K, 100K users/month) covering compute, database, storage, third-party APIs, and managed services. Identify the primary cost drivers first, then use published pricing. Provide ranges ("$5-15/mo"), not single numbers. Flag rough estimates. For development: estimate complexity per MVP feature using T-shirt sizes (S/M/L/XL) — not hours or days.
- Deployment: for web apps, always include a publicly accessible deployment path. Recommend hosting platform (Vercel, Cloudflare Pages, Fly.io, Railway, etc.) with reasoning. Specify: build command, deploy command or CI/CD approach, domain/URL strategy, platform-specific config files, and where production secrets are stored (e.g. Vercel Dashboard, GitHub Secrets). Bootstrap (feature 0) should create deployment config files (vercel.json, fly.toml, etc.) — not provision infrastructure. For non-web projects (CLI tools, libraries, internal scripts), skip or adapt (e.g. npm publish, PyPI, homebrew).

Flag anything you're uncertain about.

Also assess complexity: estimate feature count. If >5 features, suggest MVP phasing — what ships first vs what can wait.

Original topic/requirements: <topic>
Resolved decisions from Q&A: <decisions>
Stack constraints: <constraints>
Web research results: <all web results>
```

---

## Step 6: Claude critique + scope check

Read Gemini's synthesis and cross-check:
- Are the APIs real? Do the package names exist? Are there contradictions?
- Do recommendations respect existing stack constraints from Step 1? Stack conflicts are failures — reject and find alternatives.
- Are cost estimates grounded in real pricing? Flag any that seem fabricated.
- Are risks actionable? Each risk needs a concrete mitigation, not "monitor closely."
- Does the deployment path actually work? Is the recommended platform compatible with the stack (e.g. don't recommend Vercel for a Python backend)?
- If `--deep`: run a second Gemini pass on any uncertain areas.

**Scope assessment**: if >5 features, present MVP phasing to user:
```
This is a large scope. I'd ship these first: [1, 2, 3]. Phase 2: [4, 5]. Cut entirely: [6].
```

Mark MVP vs Phase 2 vs Cut in the briefing's `## Features` section.

---

## Step 7: Write briefing + persist decisions

**File path:**
- Idea/requirements mode: `presearch/<slug>.md` (slug from topic: lowercase, hyphenated, max 40 chars)
- Refine mode: update the existing file in place. Preserve `## Constraints` and `## Decisions` sections unless the user's refinement instruction explicitly changes them.

**Briefing structure:**

```markdown
# <Title>

## Overview
<1-2 paragraph description of what we're building and why>

## Summary
<Under 2000 chars. Readable overview: what we're building, core approach, key tech decisions, stack. Stored as epic description in DB. Ship passes the full briefing to Gemini separately — Summary doesn't need structural details.>

## Features
### MVP
0. Bootstrap: <scaffold command> + install ALL dependencies from ## Dependencies + create shared types/interfaces from ## Shared Interfaces + create `.env.example` from ## Environment + set up test config (<test framework>) + create project CLAUDE.md from ## Architecture > Patterns + configure deployment from ## Deployment + configure <configs> (greenfield only — omit for existing projects)
1. <Feature one — clear, scoped, shippable. Include target file paths where possible, e.g. "User auth — src/lib/auth.ts, src/app/login/page.tsx">
2. <Feature two — same: name + key file paths>

### Phase 2 (optional)
3. <Feature that can wait>

### Cut (optional)
4. <Feature explicitly descoped, with reason>

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
- **State management**: <pattern if applicable, e.g. "React context for auth, server components for data">
- **Naming**: <conventions, e.g. "camelCase for functions, PascalCase for components, kebab-case for files">
- (Include only patterns relevant to the stack. Skip sections that don't apply.)
- (Bootstrap creates a project CLAUDE.md from these patterns so all coders follow them.)

### Project Structure (greenfield only — skip for existing projects)
```
<root>/
  src/
    <directory>/ — <purpose>
    <directory>/ — <purpose>
  <config files>
```
- Bootstrap command: `<exact CLI command to scaffold, e.g. npx create-next-app@latest --ts --tailwind --app --src-dir>`
- Config choices: <any non-default config decisions (eslint preset, tsconfig strictness, etc.)>

### Shared Interfaces
- `<path/to/types.ts>`: <Entity> — <key fields> (used by features: 1, 3)
- `<path/to/utils.ts>`: <helper> — <what it does> (used by features: 2, 4)
- (These create implicit ordering — features using shared interfaces depend on the bootstrap/setup story that creates them)

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

- External-facing: API deprecation, scaling limits, vendor lock-in, breaking changes, cost surprises
- Internal tooling: auth/security gaps, data privacy, secret management, bus factor
- Always include — adapt focus to project type, don't skip

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

- Use ranges ($5-15/mo), not single numbers. Flag rough estimates with ~
- Web search for current pricing of recommended vendors before estimating
- Skip for internal tools or projects where cost isn't a factor

### Deployment
- **Platform**: <Vercel | Cloudflare Pages | Fly.io | Railway | etc.> — <why this fits the stack>
- **Build**: `<build command>`
- **Deploy**: `<deploy command or CI/CD approach>`
- **URL**: <domain strategy — custom domain, platform subdomain, etc.>
- **Config**: <platform-specific config files needed, e.g. vercel.json, fly.toml>
- **Secrets**: <where production secrets are stored — Vercel Dashboard, GitHub Secrets, etc.>
- Bootstrap (feature 0) creates deployment config files — not provision infrastructure.
- For non-web projects: adapt (npm publish, PyPI, homebrew) or skip.

## Environment
- `<ENV_VAR_NAME>` — <what service/feature needs it> (required | optional)
- (Skip if no external services. Ship uses this for env preflight — Step 3b.)
- Bootstrap story should create `.env.example` with these var names (no values) and add `.env` to `.gitignore`.

## Decisions
- **<Decision area>**: <Choice> — <reasoning> (user decision | recommended + agreed | Claude override)

## Constraints
- <Hard requirements: platform, language, existing codebase patterns>
- <Existing stack detected>
- <Things explicitly out of scope>

## Reference
- <URL or doc snippet that informed a decision>
```

**`## Summary`** should be a readable overview. Tech decisions belong in `## Decisions`. Ship passes the full briefing to Gemini during planning — Summary doesn't need to duplicate structural info.

**Record decisions**: for each tech decision in `## Decisions`:
1. Load: `ToolSearch: select:mcp__gemini__pm_add_decision`
2. Call `pm_add_decision(title=<decision area>, decision=<choice>, context=<reasoning>)`
3. Load: `ToolSearch: select:mcp__openmemory__openmemory_store`
4. Shadow to OpenMemory: `openmemory_store(content="<decision area>: <choice> — <reasoning>", tags=["decision", "<decision-id>"], user_id="proj:<project>")`

---

## Step 8: Prompt to ship

Unless `--no-ship` was set:
- Print the briefing path
- Ask: `Ship it? (/ship presearch/<slug>.md)`

The user can review/edit the briefing before shipping.
