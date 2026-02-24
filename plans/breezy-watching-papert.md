# Fix backfill.py duration calculation

## Context

`backfill.py` computes `duration_seconds` as `last_ts - first_ts` (wall-clock session time), which includes idle time between prompts. The stop-hook and `patch-durations.py` both compute it correctly as the sum of per-turn active thinking time: for each user message, measure the gap to the first assistant reply, then sum those gaps.

This means backfilled sessions show inflated durations (e.g. a session with 5 minutes of active thinking spread over 2 hours shows as 7200s instead of 300s).

## Fix

Replace the duration logic in `src/backfill.py` (lines 52-53, 98-105) with the per-turn calculation from `patch-durations.py` (lines 30-61).

### File: `src/backfill.py`

1. **Collect message pairs during transcript parsing** (inside the `for line in f:` loop, lines 57-77):
   - Track `(type, timestamp)` tuples for `user` (non-sidechain) and `assistant` messages, same as `patch-durations.py` lines 38-41

2. **Replace wall-clock duration calc** (lines 98-105) with per-turn sum:
   - Walk the message list, find each user->assistant pair, sum `(t_assistant - t_user)` for each turn
   - Identical to `patch-durations.py` lines 47-61

3. **Remove `first_ts`/`last_ts` tracking** (lines 53-54, 61-63) — no longer needed for duration. Keep `first_ts` for session date extraction (line 87-91).

## Verification

1. Run `python3 src/backfill.py /path/to/project` on a project with existing sessions
2. Compare `duration_seconds` values against what `patch-durations.py` produces for the same sessions — they should match
3. Verify the duration values are reasonable (minutes, not hours)
