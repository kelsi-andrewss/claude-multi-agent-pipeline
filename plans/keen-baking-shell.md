# Install: Add Windows OS check

## Context

Every shell script in this project (`install.sh`, `stop-hook.sh`, `init-templates.sh`, `uninstall.sh`) is pure bash with Unix path assumptions (`/`, `$HOME`, `chmod +x`, `mkdir -p`, etc.). None of this works on native Windows (cmd/PowerShell). Claude Code itself supports Windows via WSL, so a clear early error with WSL guidance is the right move — not a full port.

## Change

Add an OS check at the top of `install.sh`, immediately after `set -euo pipefail`:

```bash
# Windows detection — native Windows shells (Git Bash, MSYS, Cygwin) won't work correctly
if [[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* || -n "${WINDIR:-}" ]]; then
  echo "Error: claude-code-tracker requires a Unix shell (macOS, Linux, or WSL)." >&2
  echo "On Windows, install WSL and run this from a WSL terminal:" >&2
  echo "  https://learn.microsoft.com/windows/wsl/install" >&2
  exit 1
fi
```

### Why this check and not others

- `$OSTYPE` catches Git Bash (`msys`) and Cygwin — the two common "bash on Windows" environments that could execute the script but fail on path logic
- `$WINDIR` catches edge cases where `$OSTYPE` might not be set but the shell is still running on Windows
- WSL sets `$OSTYPE` to `linux-gnu`, so it passes through correctly — no false positives
- No need to check `win32` — bash scripts never run in native Windows cmd/PowerShell

## File

`install.sh` — add after line 2 (`set -euo pipefail`), before `SCRIPT_DIR=...`

## Verification

1. On macOS/Linux/WSL: `bash install.sh` runs normally (no change in behavior)
2. Simulated: `OSTYPE=msys bash install.sh` should print the error and exit 1
