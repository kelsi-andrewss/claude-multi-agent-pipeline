---
name: link-local
description: >
  Symlink the current npm project's local source as the global install,
  or restore the published version. Use when the user says "/link-local",
  "/link-local unlink", or "test local package".
args:
  - name: action
    type: string
    description: "'link' (default) to use local source, 'unlink' to restore published version."
---

# Link Local: {{action}}

## Steps

1. **Verify context**: Confirm `package.json` exists in the current project root. If not, stop: "No package.json found — this skill requires an npm project."

2. **Read package name**: Extract the `name` field from `package.json`.

3. **Dispatch on action**:

### `link` (default, or no args)

```bash
npm link
```

- Verify the symlink: `ls -la $(npm root -g)/<package-name>`
- Report: "Linked: global `<package-name>` now points to `<project-root>`. All hooks/scripts will use your local source. Run `/link-local unlink` to restore the published version."

### `unlink`

```bash
npm unlink
npm install -g <package-name>
```

- Verify: `ls -la $(npm root -g)/<package-name>` — should no longer be a symlink.
- Report: "Unlinked: restored published `<package-name>@<version>` from npm registry."

4. **Error handling**: If any command fails, surface the error verbatim. Common issues:
   - Permission denied → suggest `sudo` or check nvm setup
   - Package not found on registry (unlink) → "Package not published yet. Remove the link manually: `npm unlink -g <package-name>`"
