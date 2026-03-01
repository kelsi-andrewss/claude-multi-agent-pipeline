# Pitfalls: React

- Async callbacks (setTimeout, Firebase listeners, API response handlers) close over stale state — store values in a ref and read `.current` inside the callback
- `useEffect` cleanup must cancel subscriptions, timers, and listeners — missing cleanup causes memory leaks and double-fire bugs
- Never read React state after an `await` — capture all needed values into local `const` variables before the first `await`
- `useMemo` / `useCallback` dependencies: include every referenced variable — ESLint exhaustive-deps catches most but not refs
- Event handler props on child components: wrap in `useCallback` to avoid unnecessary re-renders when parent re-renders
- `useState` setter with object/array: always spread previous state (`setFoo(prev => ({...prev, key: val}))`) — direct mutation is silent corruption
- `useRef` changes do NOT trigger re-renders — if you need the UI to react to a ref change, pair with a state toggle
- Conditional hooks are forbidden — never put a hook inside an `if`, loop, or early return
