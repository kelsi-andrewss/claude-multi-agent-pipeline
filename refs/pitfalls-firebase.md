# Pitfalls: Firebase / Firestore

- `writeBatch` has a hard limit of 500 operations per batch — always chunk loops into batches of <=500, committing each before starting the next
- `batch.update()` throws if the document is also being deleted in the same batch — use `batch.set({merge:true})` or guard with a deleteSet check
- Sequential writes create consistency windows — always use `writeBatch` for mutations touching more than one related document
- Firestore listeners (`onSnapshot`) must be unsubscribed on unmount — return the unsubscribe function from `useEffect`
- `serverTimestamp()` returns `null` in the local snapshot before the server round-trip — guard reads with a fallback
- Firestore `in` queries accept a maximum of 30 elements — split larger arrays into multiple queries and merge results
- Security rules are not filters — a query that could return unauthorized documents will fail entirely, not return a partial set
- Offline persistence can serve stale data — check `metadata.fromCache` when freshness matters
