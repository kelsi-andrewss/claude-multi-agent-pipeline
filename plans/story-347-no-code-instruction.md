# Story 347 — Fix NO_CODE_INSTRUCTION conflict with planning calls

## Goal
`NO_CODE_INSTRUCTION` is prepended to every Gemini call, including planning calls (`pm_plan`, `pm_ship`) that need Gemini to return JSON (which could be considered "code"). This conflict causes Gemini to sometimes refuse to return structured JSON. Fix by making `NO_CODE_INSTRUCTION` opt-in rather than always-on.

## Changes

### 1. `gemini_client.py` — Add `system_instruction` parameter to `_gemini`
- Add an optional `system_instruction: str | None = None` parameter to `_gemini()`
- When provided, prepend `[System: {system_instruction}]` to the prompt inside `_gemini`
- Do NOT change the existing function signature in a breaking way — this is additive

### 2. `tools_gemini.py` — Pass NO_CODE_INSTRUCTION as system_instruction
- In `gemini_generate`: instead of manually building `[System: {combined_instruction}]\n\n{prompt}`, pass `combined_instruction` via `system_instruction` parameter to `_gemini`
- In `gemini_chat`: same pattern — pass the combined instruction via `system_instruction`
- In `plan`: include NO_CODE_INSTRUCTION in the system_instruction string passed to `_gemini`
- In `analyze`: include NO_CODE_INSTRUCTION in the system_instruction string passed to `_gemini`

### 3. `tools_pm_plan.py` — Do NOT include NO_CODE_INSTRUCTION
- Remove the `NO_CODE_INSTRUCTION` import
- The `_build_plan_prompt` already uses `PLAN_SYSTEM_INSTRUCTION` which says "Return ONLY valid JSON" — that's sufficient
- The `pm_critique` function's system_instruction currently includes `NO_CODE_INSTRUCTION` — remove it. It needs JSON output.
- Pass system instructions via the new `system_instruction` parameter to `_gemini` calls

### 4. `tools_pm_ship.py` — Do NOT include NO_CODE_INSTRUCTION
- The `SHIP_GROUPING_INSTRUCTION` and `_build_plan_prompt` calls should NOT include NO_CODE_INSTRUCTION
- These are planning calls that need JSON output
- No changes needed to the actual call pattern since `_build_plan_prompt` handles the system instruction via `[System: ...]` prefix — just ensure NO_CODE_INSTRUCTION is not in the prompt text

### 5. `tools_argue.py` — Already calls `_gemini` directly, no change needed
- `tools_argue.py` already builds its own `[System: {ARGUE_SYSTEM_INSTRUCTION}]` prefix
- It does NOT use NO_CODE_INSTRUCTION — correct behavior, no changes needed

## Key Constraint
- Do NOT break the calling convention. `_gemini(prompt, model=model)` must still work. The `system_instruction` parameter is additive and optional.

## Validation
- Server starts without errors
- `gemini_generate` still prepends NO_CODE_INSTRUCTION
- `pm_plan` calls do NOT include NO_CODE_INSTRUCTION in the prompt
- `pm_ship` calls do NOT include NO_CODE_INSTRUCTION in the prompt
