#!/bin/bash
# Hook profile gate — sourced by every hook.
# Three levels: minimal (1), standard (2, default), strict (3).
# Reads from /tmp/claude-hook-profile, then $CLAUDE_HOOK_PROFILE, then defaults to standard.

_profile_to_level() {
  case "$1" in
    minimal) echo 1 ;;
    strict)  echo 3 ;;
    *)       echo 2 ;;  # standard or unknown
  esac
}

get_profile_level() {
  local profile=""
  if [[ -f /tmp/claude-hook-profile ]]; then
    profile=$(cat /tmp/claude-hook-profile 2>/dev/null)
  fi
  if [[ -z "$profile" ]]; then
    profile="${CLAUDE_HOOK_PROFILE:-standard}"
  fi
  _profile_to_level "$profile"
}

require_profile() {
  local required="$1"
  local current
  current=$(get_profile_level)
  if (( current < required )); then
    # Drain stdin to prevent broken pipe, then exit silently
    cat > /dev/null 2>/dev/null || true
    exit 0
  fi
}
