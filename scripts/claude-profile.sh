#!/bin/bash
# Switch hook profile: claude-profile [minimal|standard|strict]
# Without args, shows current profile.

PROFILE_FILE="$HOME/.claude/hook-profile"

# Migrate from old locations
for old in /tmp/claude-hook-profile "$HOME/.claude/tmp/claude-hook-profile"; do
  if [[ -f "$old" && ! -f "$PROFILE_FILE" ]]; then
    mv "$old" "$PROFILE_FILE" 2>/dev/null || true
    break
  fi
done
VALID_PROFILES=("minimal" "standard" "strict")

if [[ $# -eq 0 ]]; then
  current="standard"
  if [[ -f "$PROFILE_FILE" ]]; then
    current=$(cat "$PROFILE_FILE" 2>/dev/null)
  elif [[ -n "$CLAUDE_HOOK_PROFILE" ]]; then
    current="$CLAUDE_HOOK_PROFILE"
  fi
  echo "Current hook profile: $current"
  exit 0
fi

profile="$1"

valid=false
for p in "${VALID_PROFILES[@]}"; do
  if [[ "$profile" == "$p" ]]; then
    valid=true
    break
  fi
done

if [[ "$valid" != "true" ]]; then
  echo "Invalid profile: $profile" >&2
  echo "Valid profiles: minimal, standard, strict" >&2
  exit 1
fi

echo "$profile" > "$PROFILE_FILE"
echo "Hook profile set to: $profile (effective next hook invocation)"
