# Plan: Install/uninstall skills from repo + cross-platform skill

## Context
The repo now ships `skills/view-tracking/SKILL.md`. The install/uninstall scripts need to copy/remove these skills to `~/.claude/skills/`. Additionally, the skill itself uses `open` (macOS-only) and needs to work on Linux and WSL (Windows).

**Windows scope**: install.sh already explicitly rejects native Windows shells and redirects to WSL. So "Windows support" = WSL (bash runs fine). No need for cmd/PowerShell shims. The gap is only in the skill's `open` command.

---

## Changes

### 1. `install.sh` — add skills block (after line 37, shared for both Homebrew and direct)

```bash
# Install skills to ~/.claude/skills/
if [[ -d "$SCRIPT_DIR/skills" ]]; then
  for skill_dir in "$SCRIPT_DIR/skills"/*/; do
    skill_name="$(basename "$skill_dir")"
    mkdir -p "$HOME/.claude/skills/$skill_name"
    cp "$skill_dir/SKILL.md" "$HOME/.claude/skills/$skill_name/SKILL.md"
    echo "Skill installed: $skill_name"
  done
fi
```

Placement: after the closing `fi` on line 37, before the `python3` settings patch on line 40.

### 2. `uninstall.sh` — add Windows detection + skills removal block

**Add Windows detection** (mirrors install.sh, add after line 2 `set -euo pipefail`):
```bash
if [[ "$OSTYPE" == msys* || "$OSTYPE" == cygwin* || -n "${WINDIR:-}" ]]; then
  echo "Error: claude-code-tracker requires a Unix shell (macOS, Linux, or WSL)." >&2
  exit 1
fi
```

**Add skills removal block** (after line 25, the closing `fi` of the Homebrew/direct branch):
```bash
# Remove skills this package installed
if [[ -d "$SCRIPT_DIR/skills" ]]; then
  for skill_dir in "$SCRIPT_DIR/skills"/*/; do
    skill_name="$(basename "$skill_dir")"
    dest="$HOME/.claude/skills/$skill_name"
    if [[ -d "$dest" ]]; then
      rm -rf "$dest"
      echo "Skill removed: $skill_name"
    fi
  done
fi
```

### 3. `skills/view-tracking/SKILL.md` — cross-platform `open` command

Replace hardcoded `open` with a platform-aware open command. Instruct Claude to detect the OS and use:
- macOS: `open <file>`
- Linux / WSL: `xdg-open <file>`

The skill body should tell Claude to run:
```bash
if [[ "$OSTYPE" == darwin* ]]; then
  open "<file>"
else
  xdg-open "<file>" 2>/dev/null || echo "Could not open <file> automatically. Path: <file>"
fi
```

---

## Files to modify
- `install.sh` (add skills block after line 37)
- `uninstall.sh` (add Windows detection after line 2; add skills removal after line 25)
- `skills/view-tracking/SKILL.md` (replace `open` with platform-aware open)

---

## Verification
1. Run `bash install.sh` on macOS — check `~/.claude/skills/view-tracking/SKILL.md` exists
2. Run `bash uninstall.sh` — check `~/.claude/skills/view-tracking/` is removed
3. Run `bash install.sh` in WSL — should complete without error (Python, bash all available)
4. Run `bash uninstall.sh` in native Windows Git Bash — should exit with clear error message
5. Invoke `/view-tracking` on macOS → `open` used; on Linux/WSL → `xdg-open` used
