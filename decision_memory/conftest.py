"""Shared fixtures for decision_memory tests.

Provides project scaffolding, store instances, and real-repo worktree setup.
New test files should use these fixtures instead of defining their own.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Generator

import pytest

from decision_memory.store import DecisionStore
from decision_memory.types import Decision, DecisionScope


SAMPLE_DECISIONS = [
    Decision(
        id=None,
        content="All OpenMemory writes route through om_write.py",
        reasoning="Single write gate prevents dedup bypass",
        status="active",
        source="human",
        superseded_by=None,
        created_at=None,
        updated_at=None,
        scopes=[
            DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/om_write.py"),
        ],
    ),
    Decision(
        id=None,
        content="Memory infrastructure limited to 3 persistence surfaces",
        reasoning="Reduces drift and maintenance burden",
        status="active",
        source="human",
        superseded_by=None,
        created_at=None,
        updated_at=None,
        scopes=[
            DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="CLAUDE.md"),
            DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/signal_processor.py"),
        ],
    ),
    Decision(
        id=None,
        content="Correction detection uses semantic delta, not regex",
        reasoning="Regex can't distinguish instructions from corrections",
        status="active",
        source="human",
        superseded_by=None,
        created_at=None,
        updated_at=None,
        scopes=[
            DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/signal_processor.py"),
        ],
    ),
    Decision(
        id=None,
        content="Per-project decision DB uses FastEmbed ONNX at 256d Matryoshka",
        reasoning="Portable embeddings without Ollama daemon",
        status="active",
        source="human",
        superseded_by=None,
        created_at=None,
        updated_at=None,
        scopes=[
            DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="decision_memory/*"),
        ],
    ),
    Decision(
        id=None,
        content="friction.json is NOT dead storage — do not delete",
        reasoning="Actively written by parse_friction.py, read by generate-charts.py",
        status="deprecated",
        source="human",
        superseded_by=None,
        created_at=None,
        updated_at=None,
        scopes=[
            DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="tracking/friction.json"),
        ],
    ),
]


REAL_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path):
    """Create a fake project root with .claude/ and .git/."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude").mkdir()
    return tmp_path


@pytest.fixture
def store(project):
    """DecisionStore pointed at the tmp project. DB created on first write."""
    return DecisionStore(project)


@pytest.fixture
def seeded_store(store):
    """Store with all SAMPLE_DECISIONS already recorded. Returns the same store instance."""
    for d in SAMPLE_DECISIONS:
        store.record(d)
    return store


@pytest.fixture
def connection(store) -> Generator[sqlite3.Connection, None, None]:
    """Raw sqlite3.Connection from store, schema initialized. Closed on teardown."""
    store.ensure_ready()
    conn = store._get_connection()
    yield conn
    conn.close()


@pytest.fixture
def real_worktree(tmp_path) -> Generator[Path, None, None]:
    """Create a git worktree from the real repo into a tmpdir.

    Rebuilds decisions.db from the SQL dump (since .db is gitignored).
    Discard worktree after test.
    """
    branch_name = f"test-e2e-{os.getpid()}"
    wt_path = tmp_path / "worktree"

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(wt_path), "HEAD"],
        cwd=str(REAL_REPO),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Could not create worktree: {result.stderr.strip()}")

    dump_path = wt_path / ".claude" / "decisions.sql"
    if dump_path.exists():
        store = DecisionStore(wt_path)
        store.sync_from_dump()

    yield wt_path

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt_path)],
        cwd=str(REAL_REPO), capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=str(REAL_REPO), capture_output=True,
    )
