# Memory Queue

Entries that failed to store to OpenMemory. Drain on next healthy session.

**Format per entry:**
```
## [ISO date]
content: <the memory content>
tags: <comma-separated>
user_id: <scope>
sector: <procedural|semantic|episodic>
```

---
