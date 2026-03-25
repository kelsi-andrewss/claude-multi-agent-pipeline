---
name: gen-library
description: "Generate a UI component library via Gemini. Creates reusable components with clean interfaces that ui-coder agents import instead of generating per-story. Use /gen-library before /ship for projects with UI work."
args:
  - name: args
    type: string
    description: "Optional: --project-root <path>, --extend, design spec text. If no design spec, prompts for one."
---

# Gen Library Skill Invoked

User has requested: `/gen-library {{args}}`

## Flow control

**Continuous execution.** Steps 0 through 3 execute as one uninterrupted flow. Do not pause, narrate, summarize, or ask for confirmation between steps. The only legitimate stops are:
- An error that prevents the next step from running
- No design spec provided and `--extend` not set (explicit user gate in Step 0)

---

## Step 0: Parse args

Parse `{{args}}` for flags and design spec text.

**Flags:**
- `--project-root <path>` — override the project root. Next token is the absolute path. Default: current working directory.
- `--extend` — add components to an existing library instead of generating from scratch.

After stripping flags, remaining text is `design_spec`.

If `design_spec` is empty AND `--extend` is not set: prompt "Describe the design (colors, typography, style, target components):" and stop.

If `--extend` is set and `design_spec` is empty: extend with default component types that aren't already in the manifest.

---

## Step 1: Detect project context

1. Detect framework from project root (check package.json, pubspec.yaml, build.gradle.kts, Cargo.toml, go.mod, etc.).
2. Find 1-2 exemplar component files if they exist (glob for common component directories: src/components/, lib/src/, app/components/, etc.). Store paths as `exemplar_paths`.
3. If `--extend`: read `<project-root>/components/ui/manifest.json`.
   - If missing: warn "No existing library found. Generating new library instead." Clear the extend flag.
   - If found: store as `existing_manifest` for the MCP call.

---

## Step 2: Generate library

Load tool:
```
ToolSearch: select:mcp__gemini__gemini_component_library
```

Call `gemini_component_library` with:
- `design_spec`: the parsed design spec text
- `output_dir`: `<project-root>/components/ui`
- `exemplar_paths`: from Step 1 (or omit if none found)
- `project_root`: resolved project root
- `extend_manifest`: path to existing manifest.json if --extend, otherwise omit

---

## Step 3: Report

Read the generated manifest at `<project-root>/components/ui/manifest.json`.

Print:

```
Library generated: N components in <project-root>/components/ui/

  Button — action
  Card — display
  Form — input
  ...

Manifest: <project-root>/components/ui/manifest.json
Framework: <detected>

ui-coder agents will now import from this library instead of calling gemini_ui_code per-component.
```

If `--extend` was used, note how many were added vs already existed:
```
Library extended: M new components added (K existing preserved)
```
