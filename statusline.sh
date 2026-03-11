#!/usr/bin/env bash
# Claude Code status line — themed 2-line bar
# Reads session JSON from stdin, outputs ANSI-colored status

set -euo pipefail

THEME="${CLAUDE_THEME:-pastel}"
DATA=$(cat)

# --- Extract fields (null-safe) ---
model=$(echo "$DATA" | jq -r '.model.display_name // empty' 2>/dev/null || true)
ctx_pct=$(echo "$DATA" | jq -r '.context_window.used_percentage // empty' 2>/dev/null || true)
cost=$(echo "$DATA" | jq -r '.cost.total_cost_usd // empty' 2>/dev/null || true)
duration_ms=$(echo "$DATA" | jq -r '.cost.total_duration_ms // empty' 2>/dev/null || true)
lines_add=$(echo "$DATA" | jq -r '.cost.total_lines_added // empty' 2>/dev/null || true)
lines_rm=$(echo "$DATA" | jq -r '.cost.total_lines_removed // empty' 2>/dev/null || true)
in_tok=$(echo "$DATA" | jq -r '.context_window.current_usage.input_tokens // empty' 2>/dev/null || true)
out_tok=$(echo "$DATA" | jq -r '.context_window.current_usage.output_tokens // empty' 2>/dev/null || true)
branch=$(git branch --show-current 2>/dev/null || true)
hook_profile="standard"
if [[ -f /tmp/claude-hook-profile ]]; then
  hook_profile=$(cat /tmp/claude-hook-profile 2>/dev/null)
elif [[ -n "${CLAUDE_HOOK_PROFILE:-}" ]]; then
  hook_profile="$CLAUDE_HOOK_PROFILE"
fi

# --- Helpers ---
fmt_tokens() {
  local n="$1"
  [[ -z "$n" ]] && echo "--" && return
  if (( n >= 1000000 )); then
    printf "%.1fM" "$(echo "scale=1; $n / 1000000" | bc)"
  elif (( n >= 1000 )); then
    printf "%.1fk" "$(echo "scale=1; $n / 1000" | bc)"
  else
    echo "$n"
  fi
}

fmt_duration() {
  local ms="$1"
  [[ -z "$ms" ]] && echo "--" && return
  local s=$(( ms / 1000 ))
  if (( s >= 3600 )); then
    printf "%dh%dm" $(( s / 3600 )) $(( (s % 3600) / 60 ))
  elif (( s >= 60 )); then
    printf "%dm" $(( s / 60 ))
  else
    printf "%ds" "$s"
  fi
}

fmt_cost() {
  local c="$1"
  [[ -z "$c" ]] && echo "--" && return
  printf "$%.2f" "$c"
}

progress_bar() {
  local pct="${1:-0}" width=12
  local filled=$(( pct * width / 100 ))
  local empty=$(( width - filled ))
  local bar=""
  for ((i=0; i<filled; i++)); do bar+="▓"; done
  for ((i=0; i<empty; i++)); do bar+="░"; done
  echo "$bar"
}

c() { printf "\033[38;5;%sm" "$1"; }
reset="\033[0m"

# --- Theme colors ---
case "$THEME" in
  neon)
    c_bar=$(c 87)      # cyan
    c_bar_hi=$(c 205)   # magenta (high context)
    c_model=$(c 183)    # lavender
    c_cost=$(c 220)     # gold
    c_git=$(c 114)      # mint
    c_add=$(c 87)       # cyan
    c_rm=$(c 205)       # magenta
    c_dim=$(c 245)
    ;;
  sunset)
    c_bar=$(c 209)      # warm orange
    c_bar_hi=$(c 209)
    c_model=$(c 220)    # gold
    c_cost=$(c 210)     # coral
    c_git=$(c 223)      # peach
    c_add=$(c 220)      # gold
    c_rm=$(c 167)       # coral
    c_dim=$(c 245)
    ;;
  *) # pastel (default)
    c_bar=$(c 183)      # lavender
    c_bar_hi=$(c 183)
    c_model=$(c 158)    # mint
    c_cost=$(c 218)     # soft pink
    c_git=$(c 158)      # mint
    c_add=$(c 151)      # sage
    c_rm=$(c 174)       # rose
    c_dim=$(c 245)
    ;;
esac

# --- Neon gradient: shift bar color based on context % ---
if [[ "$THEME" == "neon" && -n "$ctx_pct" ]]; then
  if (( ctx_pct > 75 )); then
    c_bar=$(c 205)   # magenta
  elif (( ctx_pct > 50 )); then
    c_bar=$(c 177)   # violet
  else
    c_bar=$(c 87)    # cyan
  fi
fi

# --- Format values ---
pct_display="${ctx_pct:-0}"
bar=$(progress_bar "$pct_display")
model_display="${model:---}"
cost_display=$(fmt_cost "$cost")
dur_display=$(fmt_duration "$duration_ms")
in_display=$(fmt_tokens "$in_tok")
out_display=$(fmt_tokens "$out_tok")
add_display="${lines_add:-0}"
rm_display="${lines_rm:-0}"
branch_display="${branch:---}"

# --- Output ---
printf " ${c_bar}◐ %s%% %s${reset} ${c_dim}·${reset} ${c_model}%s${reset} ${c_dim}·${reset} ${c_cost}%s${reset} ${c_dim}·${reset} ${c_dim}%s${reset}\n" \
  "$pct_display" "$bar" "$model_display" "$cost_display" "$dur_display"

printf "  ${c_git}%s${reset} ${c_dim}·${reset} ${c_add}+%s${reset} ${c_rm}-%s${reset} ${c_dim}·${reset} ${c_dim}%s in${reset} ${c_dim}·${reset} ${c_dim}%s out${reset} ${c_dim}·${reset} ${c_dim}⚙ %s${reset}\n" \
  "$branch_display" "$add_display" "$rm_display" "$in_display" "$out_display" "$hook_profile"
