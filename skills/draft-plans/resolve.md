# Resolve Phase

## Step 1: Parse args and detect input mode

**Flags (strip before processing):**
- `--briefing <path>` → store `briefing_path`
- `--skip-critique` → set `skip_critique = true`

**Input modes:**
1. **Manifest mode**: token ends with `.json` and file exists. Read JSON:
   - If `data.epics` exists: iterate, flatten all `epic.stories` into one list
   - Else if `data.stories`: use directly
   - If `data.briefing_path` exists and `--briefing` not set, use it
2. **ID mode**: `story-\d+` → add to list. `epic-\d+` → call `pm_list_stories`, add all.
3. **Mixed**: manifest + IDs. Deduplicate.
4. **No args**: error with usage.

```bash
bash ~/.claude/scripts/emit-event.sh "skill.draft-plans.started" "claude" "draft-plans" '{"story_count":"'"$STORY_COUNT"'"}'
```

## Step 2: Resolve stories

For each story ID:
1. Call `pm_get_story(story_id)`, read detail file for tasks, write_files, read_files, agent, title.
2. Skip if `done`/`archived` or no tasks.

**Frontend detection** — classify by scanning `write_files`:
- Flutter: `lib/src/features/*/` with widget/screen/page in name, `.dart` in layout/ui/widget dirs
- React: `.tsx`/`.jsx` in `components/`/`pages/`/`views/`
- Vue: `.vue` files
- CSS: `.css`, `.scss`, `.sass`, `.less`, `.styl`

Rules: ANY match → `frontend: true`. ALL match → `frontend_only: true`. SOME → `mixed: true`.

**Fast-path detection:** ALL of: agent=quick-fixer, write_files ≤2, no protected files, has tasks → write plan inline (Step 3b fast-path). Others → agent-path.

Frontend flags are orthogonal to fast-path.

If no stories remain: "No eligible stories to plan."
