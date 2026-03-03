# Friction Log

Course corrections that deviate from the expected workflow path.
- **Automatic**: logged at workflow trigger points (escalation, restart, conflict, etc.)
- **Judgment**: logged when Claude recognizes significant rerouting. Requires a counterfactual.

**Format per entry:**

```
## [date] — [category] — [story-id or "session"]
**Type**: automatic | judgment
**Skill**: which skill was running (or "manual" / "main-session")
**Expected**: what should have happened
**Actual**: what did happen
**Counterfactual**: what would have happened without this correction
**Recurrence**: first-seen | recurring (ref prior entries)
```

**Categories:**

| Category | Trigger | Type |
|---|---|---|
| `escalation` | Model upgrade (§9) | automatic |
| `restart` | Plan rewrite (§9) | automatic |
| `blocked` | Coder returns BLOCKED | automatic |
| `decision` | Coder returns NEED_DECISION | automatic |
| `conflict` | Merge conflict (merge-worktree Step 3) | automatic |
| `retry` | Test failure → sent back to coder (run-stories 5b) | automatic |
| `reroute` | Claude changes approach mid-execution | judgment |
| `discovery` | Assumption proven wrong during execution | judgment |

---
