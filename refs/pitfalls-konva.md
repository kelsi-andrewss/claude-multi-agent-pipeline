# Pitfalls: Konva

- Konva `Group` nodes return `0` from `.width()` and `.height()` — use `.getClientRect()` for live bounding box
- `Transformer` must be explicitly destroyed on unmount or target change — stale transformers cause ghost handles
- `getClientRect()` returns coordinates in absolute (stage) space — convert with `node.getAbsoluteTransform().copy().invert()` if you need relative coords
- `onDragMove` fires at high frequency — debounce Firestore writes, never write inside the handler directly
- `React.memo` on Konva components: shallow-compare props carefully — object/array props (like `points`, `dash`) create new references each render
- `node.cache()` improves performance but must be invalidated manually after any visual property change
- Layer `listening(false)` disables all events on that layer — use for static background layers only
- `image.onload` is async — do not assume the image is ready in the same render cycle
