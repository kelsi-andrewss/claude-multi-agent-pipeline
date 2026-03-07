#!/usr/bin/env bash
# setup-memory.sh — Create auto memory symlinks for the current machine.
# Idempotent: skips existing symlinks, safe to re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MEMORY_DIR="$REPO_ROOT/memory"

# Encode a path for Claude Code's projects/ directory naming:
# replace / with - and . with -
encode_path() {
  echo "$1" | sed 's|/|-|g; s|\.|-|g'
}

HOME_ENCODED=$(encode_path "$HOME")
DOTCLAUDE_ENCODED=$(encode_path "$HOME/.claude")

# Map: <portable memory file> <encoded project path> <requires external dir>
declare -a MAPPINGS=(
  "global.md|${HOME_ENCODED}|"
  "dotclaude.md|${DOTCLAUDE_ENCODED}|"
  "advocate.md|$(encode_path "$HOME/gauntlet/advocate")|$HOME/gauntlet/advocate"
  "legacylens.md|$(encode_path "$HOME/gauntlet/week-3-legacylens")|$HOME/gauntlet/week-3-legacylens"
)

created=0
skipped=0

for mapping in "${MAPPINGS[@]}"; do
  IFS='|' read -r mem_file encoded_path ext_dir <<< "$mapping"

  # Skip external projects if their directory doesn't exist on disk
  if [[ -n "$ext_dir" && ! -d "$ext_dir" ]]; then
    echo "skip: $mem_file (project dir $ext_dir not found)"
    ((skipped++))
    continue
  fi

  target_dir="$REPO_ROOT/projects/${encoded_path}/memory"
  target_file="$target_dir/MEMORY.md"
  source_file="$MEMORY_DIR/$mem_file"

  # Create projects/<encoded>/memory/ directory
  mkdir -p "$target_dir"

  # If target already exists and is a symlink pointing to the right place, skip
  if [[ -L "$target_file" ]]; then
    existing=$(readlink "$target_file")
    if [[ "$existing" == "$source_file" ]]; then
      echo "skip: $target_file (already linked)"
      ((skipped++))
      continue
    fi
    # Wrong symlink — remove and recreate
    rm "$target_file"
  elif [[ -f "$target_file" ]]; then
    # Regular file exists — back up and replace with symlink
    mv "$target_file" "$target_file.bak"
    echo "backed up: $target_file → $target_file.bak"
  fi

  ln -s "$source_file" "$target_file"
  echo "linked: $target_file → $source_file"
  ((created++))
done

echo ""
echo "Done: $created created, $skipped skipped."
