# Plan: Synchronize Streaming Eval Events in `chat_stream`

## Context

`agent.py` has two parallel code paths: `chat` (unary) and `chat_stream` (streaming). The `chat` method runs three important steps after the distress check:
1. Emits a `somatic_eval` SSE event when the somatic classifier fires
2. Calls the validation classifier and emits a `validation_eval` SSE event when it fires
3. Runs `run_clinical_language_translator` when `somatic_mode_active` is set

`chat_stream` is missing all three. This means the Flutter agent-state panel never receives `somatic_eval` or `validation_eval` events during streaming sessions, and `session_state.clinical_descriptor` is never populated in the streaming path.

**File:** `/Users/kelsiandrews/gauntlet/advocate/.claude/worktrees/sync-streaming-eval/agent.py`

---

## Changes

### 1. Emit `somatic_eval` event after somatic classifier (line 764)

**Location:** After `self._last_somatic_reason = somatic_result.reason` (line 763), inside the existing `try` block (lines 760–765).

Replace the existing try block:
```python
        # --- Classifiers ---
        try:
            somatic_result = await self.somatic_classifier.process_turn(message)
            self._last_somatic_trigger = somatic_result.somatic_trigger
            self._last_somatic_reason = somatic_result.reason
        except Exception as exc:
            print(f"[agent] WARNING: somatic classifier failed: {exc}", file=sys.stderr)
```

With:
```python
        # --- Classifiers ---
        try:
            somatic_result = await self.somatic_classifier.process_turn(message)
            self._last_somatic_trigger = somatic_result.somatic_trigger
            self._last_somatic_reason = somatic_result.reason
            if somatic_result.somatic_trigger and self._event_queue is not None:
                self._event_queue.put_nowait(json.dumps({
                    "tool_name": "somatic_eval",
                    "status": "done",
                    "output": somatic_result.reason,
                    "timestamp": datetime.utcnow().isoformat(),
                }))
        except Exception as exc:
            print(f"[agent] WARNING: somatic classifier failed: {exc}", file=sys.stderr)
```

### 2. Add validation classifier call + `validation_eval` event (after line 765)

Insert a new `try` block immediately after the somatic classifier block (after line 765, before the distress check at line 767):

```python
        try:
            validation_result = await self.validation_classifier.process_turn(message)
            if validation_result.validation_trigger and self._event_queue is not None:
                self._event_queue.put_nowait(json.dumps({
                    "tool_name": "validation_eval",
                    "status": "done",
                    "output": validation_result.reason,
                    "timestamp": datetime.utcnow().isoformat(),
                }))
        except Exception as exc:
            print(f"[agent] WARNING: validation classifier failed: {exc}", file=sys.stderr)
```

### 3. Add `clinical_language_translator` block (after line 784, before main streaming path)

Insert after `session_state.heard_turns += 1` (line 784), before the `# --- Main streaming path ---` comment (line 786):

```python
        if (
            self.session_state.somatic_mode_active
            and not self.session_state.clinical_descriptor
            and self.session_state.patient_language_buffer
        ):
            combined_text = " ".join(self.session_state.patient_language_buffer)
            translation = await run_clinical_language_translator(
                direction="patient_to_clinical",
                text=combined_text,
                patient_language_buffer=self.session_state.patient_language_buffer,
                llm=self.llm,
            )
            self.session_state.clinical_descriptor = translation.get("translated_text", "")
            self.session_state.somatic_mode_active = False
            self.session_state.somatic_collected = True
```

---

## Ordering Note

The `chat` method runs classifiers *before* the distress check (line 620), whereas `chat_stream` already runs classifiers before the distress check (line 760). This ordering is consistent — no reordering needed.

One minor difference: in `chat`, the somatic nudge injection happens *after* classifiers (line 680), while in `chat_stream` it happens *before* classifiers (line 749). This pre-existing inconsistency is out of scope — the plan preserves the current `chat_stream` ordering.

---

## Critical Files

- `agent.py` — only file modified (worktree path: `.claude/worktrees/sync-streaming-eval/agent.py`)
- `prompts/validation.py` — `ValidationClassifierMiddleware.process_turn` (already imported in agent.py via `self.validation_classifier`)
- `prompts/somatic.py` — `SomaticClassifierMiddleware.process_turn` (already used)
- `tools/clinical_translator.py` — `run_clinical_language_translator` (already imported in agent.py)

---

## Verification

1. Run existing tests: `cd advocate && python -m pytest tests/ -x --tb=short`
2. Manual smoke test with a somatic-trigger message (e.g. "I just don't feel right, it's hard to explain") via `chat_stream` — confirm `somatic_eval` appears in `_event_queue`
3. Manual smoke test with a validation-trigger message (e.g. "you're not listening to me") — confirm `validation_eval` appears in `_event_queue`
4. Check `session_state.clinical_descriptor` is non-empty after a somatic-mode turn in streaming path
