#!/usr/bin/env bash
# Claude Code welcome banner — animated starfield with outline frame and shooting stars
# Respects CLAUDE_THEME (pastel|neon|sunset) and CLAUDE_ANIMATE (0=static)

THEME="${CLAUDE_THEME:-pastel}"
ANIMATE="${CLAUDE_ANIMATE:-1}"
reset=$'\033[0m'

# --- Color themes ---
case "$THEME" in
  neon)
    star_colors=(21 33 51 93 165 201 87 46)
    trail_colors=(17 27 45 87)
    c_accent=51; c_text=87; c_dim=245
    ;;
  sunset)
    star_colors=(178 208 214 202 196 220 172 209)
    trail_colors=(94 172 214 220)
    c_accent=220; c_text=223; c_dim=245
    ;;
  *) # pastel (default)
    star_colors=(183 218 158 151 225 189 147 222)
    trail_colors=(53 141 218 225)
    c_accent=218; c_text=158; c_dim=245
    ;;
esac

# --- Terminal width ---
COLS=${BANNER_COLS:-$(tput cols 2>/dev/null || echo 72)}
(( COLS < 72 )) && COLS=72
# Inner width for star content (between │ borders)
INNER_W=$(( COLS - 2 ))

# --- Starfield: fixed stars across 70×7 grid ---
# Row 0 — gaps: 7,5,6,4,7,5,8,5,6,7,5
star_col=(  2  9 14 20 24 31 36 44 49 55 62 67)
star_row=(  0  0  0  0  0  0  0  0  0  0  0  0)
star_chr=( "·" "⋆" "·" "✦" "✦" "✦" "·" "✦" "✧" "·" "✧" "⋆")
star_ci=(   0   1   2   3   4   5   6   7   0   1   2   3)
star_rev=(  0   0   0   0   0   1   1   1   1   1   2   2)
star_alt=( "⋆" "✦" "⋆" "✧" "·" "⋆" "✦" "⋆" "✧" "⋆" "✦" "·")

# Row 1 — gaps: 5,7,4,8,5,6,7,5,4,7
star_col+=( 5 10 17 21 29 34 40 47 52 56 63)
star_row+=( 1  1  1  1  1  1  1  1  1  1  1)
star_chr+=("✦" "✦" "·" "⋆" "✦" "✧" "·" "⋆" "✧" "✧" "⋆")
star_ci+=(  4   5   6   7   0   1   2   3   4   5   6)
star_rev+=( 2   2   2   3   3   3   3   3   4   4   4)
star_alt+=("✧" "⋆" "✦" "⋆" "✧" "·" "⋆" "✦" "⋆" "✧" "⋆")

# Rows 2-5 — full width with irregular spacing
star_col+=( 3 11 15 22 27 33 39 46 50 57 64)
star_row+=( 2  2  2  2  2  2  2  2  2  2  2)
star_chr+=("✧" "✦" "·" "⋆" "✦" "✦" "⋆" "✧" "✦" "⋆" "✧")
star_ci+=(  7   0   1   4   2   6   3   5   7   0   4)
star_rev+=( 1   3   0   2   1   0   2   3   4   1   2)
star_alt+=("✦" "⋆" "✧" "·" "✧" "·" "✦" "✦" "✧" "⋆" "✦")

star_col+=( 6  9 16 23 28 35 41 44 51 58 62)
star_row+=( 3  3  3  3  3  3  3  3  3  3  3)
star_chr+=("✧" "·" "⋆" "⋆" "⋆" "✦" "✦" "⋆" "·" "⋆" "⋆")
star_ci+=(  2   4   5   3   1   7   6   0   3   2   5)
star_rev+=( 0   2   1   4   3   0   2   1   4   3   0)
star_alt+=("⋆" "✦" "·" "✦" "✦" "✧" "✧" "⋆" "✦" "·" "✧")

star_col+=( 4 10 18 21 26 32 38 45 53 57 65)
star_row+=( 4  4  4  4  4  4  4  4  4  4  4)
star_chr+=("✦" "✦" "⋆" "·" "⋆" "✦" "✦" "⋆" "✧" "✦" "·")
star_ci+=(  1   7   4   6   0   3   5   2   7   1   6)
star_rev+=( 3   1   0   3   2   4   1   0   3   2   4)
star_alt+=("✧" "⋆" "✦" "⋆" "✦" "·" "✧" "✦" "✦" "✧" "⋆")

star_col+=( 7 13 17 24 30 36 43 48 54 61 66)
star_row+=( 5  5  5  5  5  5  5  5  5  5  5)
star_chr+=("⋆" "·" "⋆" "✦" "✧" "·" "✧" "✦" "·" "✧" "✧")
star_ci+=(  3   5   1   7   4   0   6   2   5   3   7)
star_rev+=( 2   0   4   1   3   2   0   4   1   3   2)
star_alt+=("·" "✦" "⋆" "✧" "✦" "⋆" "✦" "✧" "⋆" "✦" "✦")

# Row 6 — gaps: 8,7,5,9,6,7,8,6,7
star_col+=( 3 11 18 23 32 38 45 53 59 66)
star_row+=( 6  6  6  6  6  6  6  6  6  6)
star_chr+=("·" "✧" "✦" "·" "⋆" "✧" "·" "✦" "⋆" "✧")
star_ci+=(  2   4   6   0   3   5   1   7   4   6)
star_rev+=( 0   1   2   3   4   0   1   2   3   4)
star_alt+=("⋆" "✦" "✧" "⋆" "·" "✦" "⋆" "✧" "·" "✦")

NSTARS=${#star_col[@]}

# --- Scale star columns for wider terminals ---
if (( INNER_W != 70 )); then
  for ((i=0; i<NSTARS; i++)); do
    star_col[$i]=$(( star_col[i] * INNER_W / 70 ))
  done
fi

# --- Shooting stars: 3 streaks on open rows ---
streak_chars=("·" "╌" "─" "─" "✦")
ss_col=(  3 30 50)
ss_row=(  0  6  1)
ss_start=(1  5  9)
ss_len=( 22 20 18)

# Scale shooting star positions
if (( INNER_W != 70 )); then
  for ((i=0; i<3; i++)); do
    ss_col[$i]=$(( ss_col[i] * INNER_W / 70 ))
    ss_len[$i]=$(( ss_len[i] * INNER_W / 70 ))
  done
fi

# --- Fill extra stars for wider terminals ---
if (( COLS > 75 )); then
  _fill_chars=("·" "✧" "✦" "⋆")
  _seed=42
  # All rows full-width: fill gaps with varied step
  for row in 0 1 2 3 4 5 6; do
    declare -a _used=()
    for ((i=0; i<NSTARS; i++)); do
      (( star_row[i] == row )) && _used+=("${star_col[$i]}")
    done
    for ((c=3; c<INNER_W-2; c+=1)); do
      _near=0
      for u in "${_used[@]}"; do
        (( (c - u) > -6 && (c - u) < 6 )) && { _near=1; break; }
      done
      if (( !_near )); then
        _ch="${_fill_chars[$(( _seed % 4 ))]}"
        star_col+=("$c"); star_row+=("$row")
        star_chr+=("$_ch"); star_ci+=("$(( _seed % 8 ))")
        star_rev+=("$(( _seed % 5 ))")
        star_alt+=("${_fill_chars[$(( (_seed+1) % 4 ))]}")
        _used+=("$c")
        _seed=$(( (_seed * 31 + 17) % 997 ))
        _step=$(( 4 + (_seed % 4) ))
        c=$(( c + _step ))
      fi
    done
    unset _used
  done
  NSTARS=${#star_col[@]}
fi

# --- Greeting + metadata ---
dir=$(basename "$PWD")
branch=$(git branch --show-current 2>/dev/null || echo "—")
model="${CLAUDE_MODEL:-}"
# Truncate long names to fit border labels
(( ${#dir} > 15 )) && dir="${dir:0:14}…"
(( ${#branch} > 15 )) && branch="${branch:0:14}…"

hour=$(date +%H)
if (( 10#$hour >= 5 && 10#$hour < 12 )); then greeting="good morning"
elif (( 10#$hour >= 12 && 10#$hour < 17 )); then greeting="good afternoon"
elif (( 10#$hour >= 17 && 10#$hour < 21 )); then greeting="good evening"
else greeting="late night mode"; fi

# --- Git context ---
last_hash=$(git log -1 --format='%h' 2>/dev/null || echo "")
last_msg=$(git log -1 --format='%s' 2>/dev/null || echo "")
(( ${#last_msg} > 30 )) && last_msg="${last_msg:0:29}…"
last_time=$(git log -1 --format='%cr' 2>/dev/null || echo "")
modified=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')

# --- Worktrees (subtract 1 for main) ---
wt_total=$(git worktree list 2>/dev/null | wc -l | tr -d ' ')
wt_count=$(( wt_total - 1 ))
(( wt_count < 0 )) && wt_count=0

# --- Session context from epics.db ---
_db="$HOME/.claude/.claude/epics.db"
if [[ -f "$_db" ]]; then
  epic_count=$(sqlite3 "$_db" "SELECT count(*) FROM epics WHERE state='active';" 2>/dev/null || echo "0")
  story_count=$(sqlite3 "$_db" "SELECT count(*) FROM stories WHERE state NOT IN ('done','shipped') AND archived=0;" 2>/dev/null || echo "0")
else
  epic_count=0; story_count=0
fi

# --- Pre-build outline frame borders ---
_bc="\033[38;5;${c_accent}m"

# Top border: ╭─ Claude Code · {model} ─...─╮
if [[ -n "$model" ]]; then
  _top_label="─ Claude Code · ${model} "
else
  _top_label="─ Claude Code "
fi
_top_label_len=${#_top_label}
_top_fill=$(( COLS - 2 - _top_label_len ))
(( _top_fill < 0 )) && _top_fill=0
_top_dashes=""; for ((i=0; i<_top_fill; i++)); do _top_dashes+="─"; done
frame_top="${_bc}╭${_top_label}${_top_dashes}╮${reset}"

# Bottom border: ╰─...─ {dir} · {branch} ─╯
_bot_label=" ${dir} · ${branch} "
_bot_label_len=${#_bot_label}
_bot_fill=$(( COLS - 3 - _bot_label_len ))
(( _bot_fill < 0 )) && _bot_fill=0
_bot_dashes=""; for ((i=0; i<_bot_fill; i++)); do _bot_dashes+="─"; done
frame_bot="${_bc}╰${_bot_dashes}${_bot_label}─╯${reset}"

# --- Info lines (below the box) ---
git_line=""
if [[ -n "$last_hash" ]]; then
  git_line="  \033[38;5;${c_dim}m${last_hash} ${last_msg} · ${last_time} · ${modified} modified${reset}"
fi

session_parts="${epic_count} epics · ${story_count} stories · ${wt_count} worktrees"
session_line="  \033[38;5;${c_dim}m${session_parts}${reset}"

# --- Cursor management ---
cleanup() { printf '\033[?25h'; }
trap cleanup INT TERM EXIT

# --- Build flat grid: star_grid[row*INNER_W+col] = star index+1 (0=empty) ---
declare -a star_grid
_grid_size=$(( INNER_W * 7 ))
for ((i=0; i<_grid_size; i++)); do star_grid[$i]=0; done
for ((i=0; i<NSTARS; i++)); do
  star_grid[$((star_row[i]*INNER_W + star_col[i]))]=$((i+1))
done

# --- Render a single frame ---
render_frame() {
  local frame=$1
  local buf=""
  local ROWS=7

  # Top border
  buf+="${frame_top}\n"

  for ((row=0; row<ROWS; row++)); do
    local line=""
    for ((col=0; col<INNER_W; col++)); do
      local drawn=0

      # Check shooting stars (priority over background stars)
      for ((si=0; si<3; si++)); do
        if (( ss_row[si] != row )); then continue; fi
        if (( frame < ss_start[si] )); then continue; fi
        local head_pos=$(( ss_col[si] + frame - ss_start[si] ))
        if (( head_pos >= ss_col[si] + ss_len[si] )); then continue; fi
        local tail_start=$(( head_pos - 4 ))
        if (( col >= tail_start && col <= head_pos && col >= 0 )); then
          local char_idx=$(( col - tail_start ))
          if (( char_idx < 0 )); then continue; fi
          if (( char_idx > 4 )); then char_idx=4; fi
          local tc=${trail_colors[$char_idx]}
          if (( char_idx == 4 )); then tc=231; fi
          line+="\033[38;5;${tc}m${streak_chars[$char_idx]}"
          drawn=1
          break
        fi
      done

      if (( drawn )); then continue; fi

      # Check background star via flat grid
      local gi=${star_grid[$((row*INNER_W + col))]}
      if (( gi > 0 )); then
        local si=$((gi - 1))
        if (( frame >= star_rev[si] )); then
          local ci=${star_ci[$si]}
          local sc=${star_colors[$ci]}
          local ch="${star_chr[$si]}"
          # Twinkle: per-star period with pseudo-random phase
          local period=$(( 3 + (si * 7) % 4 ))
          local phase=$(( (si * 13) % period ))
          if (( frame >= 2 && (frame + phase) % period == 0 )); then
            ch="${star_alt[$si]}"
            local alt_ci=$(( (ci + 1) % 8 ))
            sc=${star_colors[$alt_ci]}
          fi
          line+="\033[38;5;${sc}m${ch}"
          drawn=1
        fi
      fi

      if (( !drawn )); then
        line+=" "
      fi
    done
    buf+="${_bc}│${reset}${line}${reset}${_bc}│${reset}\n"
  done

  # Bottom border
  buf+="${frame_bot}\n"

  # Blank line
  buf+="\n"

  # Greeting line
  if (( frame >= 11 )); then
    buf+="  \033[38;5;${c_accent}m✦${reset} \033[38;5;${c_text}m${greeting}${reset}\n"
  else
    buf+="\n"
  fi

  # Git context line
  if (( frame >= 11 )) && [[ -n "$git_line" ]]; then
    buf+="${git_line}\n"
  else
    buf+="\n"
  fi

  # Session context line
  if (( frame >= 11 )); then
    buf+="${session_line}\n"
  else
    buf+="\n"
  fi

  printf "%b" "$buf"
}

# --- Main ---
TOTAL_ROWS=13  # top border + 7 starfield + bottom border + 1 blank + 3 info lines

printf '\033[?25l'  # hide cursor
echo ""  # top margin

if (( ANIMATE == 0 )); then
  render_frame 11
  echo ""
else
  for ((i=0; i<TOTAL_ROWS; i++)); do echo ""; done

  for ((frame=0; frame<12; frame++)); do
    printf "\033[${TOTAL_ROWS}A"
    render_frame "$frame"
    sleep 0.08
  done
  echo ""
fi

printf '\033[?25h'  # restore cursor
