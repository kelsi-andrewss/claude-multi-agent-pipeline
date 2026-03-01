# Protected Files Template

This template is used by `/refine` to generate a project's `protected-files.md`.

## Questions to ask the user

1. "Which files should be protected from casual edits?" (suggest large/critical component files detected by scanning)
2. "Any files that always require testing when changed?" (suggest `src/utils/`, `src/hooks/`, files with `.test.*` counterparts)

## Output format: `<project>/.claude/protected-files.md`

```markdown
# Protected Files

## Edit-protected (require explicit user permission per story)
- src/components/ExampleComponent.jsx
- src/components/AnotherCritical.jsx

## Test-required (auto-set needsTesting when in writeFiles)
- src/utils/**
- src/hooks/**
```

## How these are consumed

- **Guard hook** (`guard-direct-edit.sh`): reads edit-protected list to block unauthorized edits
- **Orchestrator**: reads test-required list to auto-flag `needsTesting: true`
- **Coder prompts**: edit-protected files get the "Do NOT edit" warning unless story grants permission
- **/hotfix skill**: rejects if target file is in either list
- **/quickfix skill**: asks user if target file is in test-required list
