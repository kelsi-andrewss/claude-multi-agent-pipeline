# Global Dev Todos

## Investigate: why does `git push` take so long?
Pushing branches during story merges takes noticeably long. Possible causes to investigate:
- GitHub SSH key not cached / re-authenticating on each push
- Large repo size / pack file bloat from many worktrees
- Network latency to GitHub
- Pre-push hooks running unexpectedly
- `node_modules` symlinks confusing git pack
