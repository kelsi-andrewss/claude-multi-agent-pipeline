# Decompose Phase

## Step 1: Decompose into stages

Based on `spec.pattern`, produce dependency-ordered stages from fixed DAGs:

### CRUD+UI
1. `db_migration` → 2. `rest_endpoints` → 3. `react_components` + 5. `permissions` (parallel) → 4. `test_suite`

### Integration
1. `integration_client` → 2. `sync_logic` → 3. `error_handling` → 4. `test_suite`

### Workflow
1. `state_machine` → 2. `transition_handlers` → 3. `notifications` + 5. `admin_ui` (parallel) → 4. `test_suite`

### Library-extension
1. `implementation` → 2. `registration` (collapse into 1 if same files) → 3. `test_suite`

### Analytics
1. `aggregation_queries` → 2. `api_endpoints` → 3. `dashboard_components` → 4. `test_suite`

### Stage enrichment

1. **Write files**: Call `pm_list_patterns(category=<product>)` for conventions. Generic placeholders if none.
2. **Acceptance criteria**: Behavioral given/when/then from spec fields and permissions.
3. **Tasks**: Implementation steps with file references.
4. **Conditional stages**:
   - `spec.audit: true` → append `audit_logging` stage
   - Empty `spec.permissions` → skip `permissions` stage
   - Missing/false `spec.ui` → skip UI stages, adjust test_suite dependencies

### Parallelism annotation

Two stages are parallelizable if neither depends on the other. Store parallel groups for manifest.

## Step 2: Delegate to Gemini for content planning

Launch foreground planner agent with spec metadata and stage list. Gemini produces concrete write_files, read_files, tasks, acceptance criteria per stage.

If `dry_run = true`, skip — use Step 1 placeholders.

On error: surface to user, stop.
