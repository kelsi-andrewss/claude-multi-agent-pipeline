#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== Security regression tests ===" >&2
python3 -m pytest "$REPO_ROOT/decision_memory/test_e2e.py" \
  -v -k "TestFTS5Sanitization or TestBatchEmbeddingAlignment or TestDecisionScopeValidation or TestSQLInjectionRegression" \
  "$@"
