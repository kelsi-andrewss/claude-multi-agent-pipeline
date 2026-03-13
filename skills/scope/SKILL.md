---
name: scope
description: "Capture lightweight project definition, detect existing stack, and classify domain complexity to determine whether deep research is needed before clarify. Use when the user says \"/scope <topic>\" or \"/scope --skip-qa <topic>\"."
args:
  - name: args
    type: string
    description: "Topic (quoted string or free text), or flags (--skip-qa)."
---

# Scope Skill Invoked

User has requested: `/scope {{args}}`

---

## Step 0: Parse args and detect mode

Parse `{{args}}` to determine flags and topic:

**Flags** (strip from args after detection):
- `--skip-qa` → skip the Q&A phase, write artifact with null Q&A fields

**Topic extraction** (after stripping flags):
- Everything remaining is the `topic` text.
- **If no topic**: prompt the user with `AskUser`: "What are you building?" and stop until answered.

**Slug derivation**: from the topic text, generate a slug — lowercase, hyphenated, max 40 chars. Strip articles and filler words. Examples:
- "fraction pedagogy app for elementary students" → `fraction-pedagogy-app-elementary`
- "change the login button color to blue" → `change-login-button-color-blue`
- "add real-time collaboration to our canvas" → `add-realtime-collaboration-canvas`

---

## Step 1: Stack detection

Scan the current working directory for project markers:
- `package.json`, `pubspec.yaml`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `CLAUDE.md`

If found: read the relevant files to extract framework, language, and existing dependencies. Store as `stack_detected` entries — an array of `{ marker, framework, language, dependencies }`. These become hard constraints for downstream skills.

If nothing found: greenfield mode. `stack_detected` is an empty array.

If multiple markers are found (e.g., `package.json` + `pyproject.toml`): detect all, store all in the `stack_detected` array.

If only `CLAUDE.md` is found with no other markers: read it for stack hints, but do not infer a specific framework. Store with `framework: null`.

---

## Step 2: Q&A flow

**Skip if `--skip-qa` flag is set.** Proceed to Step 3 with null Q&A fields.

Present a single batched `AskUser` prompt capturing essential project attributes:

```
Quick project definition:

1. **What are you building?** (one sentence)
2. **Who is it for?** (target users/audience)
3. **Target platform?** (web, mobile, CLI, API, library, etc.)
4. **In scope**: what MUST this include?
5. **Out of scope**: what should it explicitly NOT include?
```

Parse user responses into structured fields: `what`, `audience`, `platform`, `in_scope` (array), `out_of_scope` (array).

No follow-up rounds — this is intentionally lightweight. One prompt, one response.

---

## Step 3: Domain complexity classification

This is the core gating logic. Use the topic text + any Q&A answers + detected stack to determine whether `/research` should trigger before `/clarify`.

**Classification criteria:**

`needs_research = true` when ANY of:
- Topic involves a domain requiring specialized knowledge the system likely doesn't have (scientific, pedagogical, medical, legal, financial, regulatory)
- Topic is a BrainLift (learning tool, educational content, curriculum design)
- Topic involves APIs/services the system may not have current documentation for
- Topic involves unfamiliar integration patterns or protocols
- Domain ambiguity: the system can't confidently recommend an approach without external validation

`needs_research = false` when ALL of:
- Topic is a well-understood pattern (CRUD, UI changes, standard auth, common integrations)
- Stack is detected and the change fits within it
- No domain-specific knowledge required beyond standard engineering

**Bias**: err toward `needs_research = true`. False positives cost tokens; false negatives produce uninformed decisions downstream.

**Output of this step**: `needs_research` boolean + `complexity_reasoning` (one sentence explaining why).

---

## Step 4: Scope estimation and route_hint

Estimate scope from the topic, Q&A answers, and stack context:
- `files`: estimated write-target file count
- `stories`: estimated story count
- `complexity`: `small`, `medium`, or `large` per artifact contract thresholds:

| Complexity | Files | Stories | Rule |
|---|---|---|---|
| small | <=3 | 1 | Straightforward changes, single story |
| medium | 4-10 | 2-5 | Multiple files or stories |
| large | >10 | >5 | Either dimension exceeds medium |

Complexity is the max of the two dimensions.

**Route hint logic**:
- `quickfix` when: `scope.files <= 3` AND `complexity == "small"` AND `needs_research == false`
- `research` when: `needs_research == true`
- `standard` otherwise (skip research, go to clarify+scout)

---

## Step 5: Write artifact

Write `.scope-<slug>.json` in the current working directory.

**Schema** (conforms to `refs/artifact-contract.md`):

```json
{
  "slug": "<slug>",
  "skill": "scope",
  "scope": {
    "files": "<number>",
    "stories": "<number>",
    "complexity": "<small|medium|large>"
  },
  "route_hint": "<quickfix|research|standard>",
  "prev": [],
  "data": {
    "topic": "<original topic text>",
    "what": "<what is being built>",
    "audience": "<who is it for>",
    "platform": "<target platform>",
    "in_scope": ["<must-include items>"],
    "out_of_scope": ["<explicitly-excluded items>"],
    "stack_detected": [
      {
        "marker": "<file that triggered detection>",
        "framework": "<detected framework or null>",
        "language": "<detected language>",
        "dependencies": ["<key dependencies>"]
      }
    ],
    "needs_research": "<boolean>",
    "complexity_reasoning": "<one sentence explaining the classification>"
  }
}
```

**`prev` field**: always `[]` — scope is the chain root, it has no upstream artifacts.

**`--skip-qa` mode**: `what`, `audience`, `platform`, `in_scope`, `out_of_scope` are set to `null`. Stack detection and domain complexity classification still run.

---

## Step 6: Report

Print summary:

```
Scope: .scope-<slug>.json
Stack: <detected framework(s) or "greenfield">
Research needed: <yes/no> -- <complexity_reasoning>
Scope: <files> files, <stories> stories, <complexity>
Route: <quickfix|research|standard>
```

Do NOT prompt to run downstream skills. Routing is the orchestrator's job.

---

## Edge cases

- **Empty topic with no args**: `AskUser` fires before anything else (Step 0)
- **No project markers found**: greenfield mode, `stack_detected` is an empty array
- **`--skip-qa` on a vague topic**: artifact has null Q&A fields but domain complexity classification still runs on topic text alone
- **Ambiguous domain**: err toward `needs_research = true` (false positives cheaper than false negatives)
- **Multiple project markers** (e.g., `package.json` + `pyproject.toml`): detect all, store all in `stack_detected` array
- **CLAUDE.md found but no other markers**: read `CLAUDE.md` for stack hints, but don't infer a specific framework
