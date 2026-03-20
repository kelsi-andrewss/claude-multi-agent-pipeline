#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== Security regression tests ===" >&2
python3 -m pytest "$REPO_ROOT/decision_memory/test_e2e.py" \
  -v -k "TestFTS5Sanitization or TestBatchEmbeddingAlignment or TestDecisionScopeValidation or TestSQLInjectionRegression" \
  "$@"

echo "" >&2
echo "=== Audit fix regression tests (shell injection, scope matching, DB safety) ===" >&2
python3 -m pytest "$REPO_ROOT/.claude/tests/test_audit_fixes.py" \
  -v -k "TestShellInjectionRegression or TestScopeMatching or TestSignalProcessorFixes" \
  "$@"
