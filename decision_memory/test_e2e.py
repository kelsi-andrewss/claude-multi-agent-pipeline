"""End-to-end tests for the decision memory system.

Exercises: store → dump → rebuild → search → rules → hook simulation.
Uses a tmpdir so production data is never touched.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_memory.store import DecisionStore
from decision_memory.search import SearchEngine
from decision_memory.dump import dump_to_sql
from decision_memory.rules_generator import generate_rules
from decision_memory.types import Decision, DecisionScope
from decision_memory.embeddings import EmbeddingProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path):
    """Create a fake project root with .claude/ and .git/."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude").mkdir()
    return tmp_path


@pytest.fixture
def store(project):
    return DecisionStore(project)


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


# ---------------------------------------------------------------------------
# 1. Store: record and retrieve
# ---------------------------------------------------------------------------

class TestStore:
    def test_record_and_get(self, store):
        d = SAMPLE_DECISIONS[0]
        did = store.record(d)
        assert did >= 1

        fetched = store.get(did)
        assert fetched is not None
        assert fetched.content == d.content
        assert fetched.reasoning == d.reasoning
        assert fetched.status == "active"
        assert fetched.source == "human"
        assert len(fetched.scopes) == 1
        assert fetched.scopes[0].scope_value == "hooks/lib/om_write.py"

    def test_record_multiple(self, store):
        ids = []
        for d in SAMPLE_DECISIONS:
            ids.append(store.record(d))
        assert len(ids) == len(SAMPLE_DECISIONS)
        assert len(set(ids)) == len(ids), "IDs should be unique"

    def test_list_all_active(self, store):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        active = store.list_all(status="active")
        assert len(active) == 4  # 5 total minus 1 deprecated

    def test_list_all_no_filter(self, store):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        all_decisions = store.list_all()
        assert len(all_decisions) == 5

    def test_get_nonexistent(self, store):
        store.record(SAMPLE_DECISIONS[0])  # init DB
        assert store.get(9999) is None


# ---------------------------------------------------------------------------
# 2. Dump: SQL portability
# ---------------------------------------------------------------------------

class TestDump:
    def test_dump_creates_sql_file(self, store, project):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        assert dump_path.exists()
        content = dump_path.read_text()
        assert "INSERT OR REPLACE INTO decisions" in content
        assert "INSERT OR REPLACE INTO decision_scopes" in content

    def test_dump_is_valid_sql(self, store, project):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Load into a fresh in-memory DB
        conn = sqlite3.connect(":memory:")
        conn.executescript(dump_path.read_text())
        count = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert count == len(SAMPLE_DECISIONS)

        scope_count = conn.execute("SELECT COUNT(*) FROM decision_scopes").fetchone()[0]
        expected_scopes = sum(len(d.scopes) for d in SAMPLE_DECISIONS)
        assert scope_count == expected_scopes
        conn.close()

    def test_dump_preserves_quotes(self, store, project):
        """SQL dump escapes single quotes in content."""
        d = Decision(
            id=None,
            content="Don't use regex — it's unreliable",
            reasoning="Kelsi's rule: semantic > lexical",
            status="active",
            source="human",
            superseded_by=None,
            created_at=None,
            updated_at=None,
            scopes=[],
        )
        store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Reimport should not fail on quotes
        conn = sqlite3.connect(":memory:")
        conn.executescript(dump_path.read_text())
        row = conn.execute("SELECT content FROM decisions WHERE id=1").fetchone()
        assert "Don't" in row[0]
        conn.close()


# ---------------------------------------------------------------------------
# 3. Rebuild: dump → delete DB → rebuild from dump
# ---------------------------------------------------------------------------

class TestRebuild:
    def test_sync_from_dump(self, store, project):
        for d in SAMPLE_DECISIONS:
            store.record(d)

        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Delete DB
        db_path = project / ".claude" / "decisions.db"
        db_path.unlink()
        for suffix in ("-shm", "-wal"):
            p = db_path.parent / (db_path.name + suffix)
            if p.exists():
                p.unlink()

        # Rebuild
        store2 = DecisionStore(project)
        store2.sync_from_dump()

        all_decisions = store2.list_all()
        assert len(all_decisions) == len(SAMPLE_DECISIONS)

    def test_staleness_detection(self, store, project):
        store.record(SAMPLE_DECISIONS[0])
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Append to dump — DB is now stale
        with open(dump_path, "a") as f:
            f.write("\n-- stale marker\n")

        store2 = DecisionStore(project)
        assert store2._is_stale()


# ---------------------------------------------------------------------------
# 4. Search: FTS5 keyword + vector (if available)
# ---------------------------------------------------------------------------

class TestSearch:
    def _build_engine(self, store) -> SearchEngine:
        for d in SAMPLE_DECISIONS:
            store.record(d)
        conn = store._get_connection()
        provider = EmbeddingProvider()
        engine = SearchEngine(conn, provider)
        engine.rebuild_index()
        return engine

    def test_keyword_search(self, store):
        engine = self._build_engine(store)
        results = engine.keyword_search("correction detection regex")
        assert len(results) > 0
        contents = [r.decision.content for r in results]
        assert any("correction" in c.lower() for c in contents)

    def test_keyword_no_match(self, store):
        engine = self._build_engine(store)
        results = engine.keyword_search("xyznonexistent")
        assert len(results) == 0

    def test_hybrid_search(self, store):
        engine = self._build_engine(store)
        results = engine.hybrid_search("OpenMemory write path")
        assert len(results) > 0
        # Should rank the om_write decision high
        assert any("om_write" in r.decision.content for r in results)

    def test_vector_search_graceful_without_vec(self, store):
        """Vector search returns [] if sqlite-vec isn't available."""
        for d in SAMPLE_DECISIONS:
            store.record(d)
        conn = store._get_connection()
        engine = SearchEngine(conn, EmbeddingProvider())
        # Don't rebuild index — vec table may not exist
        results = engine.vector_search("anything")
        # Should return results if vec is available, empty list if not — no crash
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 5. Rules generator: glob-based fallback
# ---------------------------------------------------------------------------

class TestRulesGenerator:
    def test_generates_markdown(self, store, project):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        out = generate_rules(str(project))
        assert Path(out).exists()
        content = Path(out).read_text()
        assert "# Project Decisions" in content
        assert "om_write" in content

    def test_scoped_sections(self, store, project):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        out = generate_rules(str(project))
        content = Path(out).read_text()
        assert "### `hooks/lib/om_write.py`" in content
        assert "### `hooks/lib/signal_processor.py`" in content

    def test_empty_store(self, project):
        """No crash on empty project."""
        out = generate_rules(str(project))
        content = Path(out).read_text()
        assert "No decisions recorded" in content

    def test_sql_only_fallback(self, store, project):
        """Works from SQL dump alone (no .db file)."""
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Delete DB, keep only SQL
        (project / ".claude" / "decisions.db").unlink()
        for suffix in ("-shm", "-wal"):
            p = project / ".claude" / (f"decisions.db{suffix}")
            if p.exists():
                p.unlink()

        out = generate_rules(str(project))
        content = Path(out).read_text()
        assert "om_write" in content


# ---------------------------------------------------------------------------
# 6. Hook simulation: edit-time injection
# ---------------------------------------------------------------------------

class TestHookInjection:
    HOOK_SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "inject-project-decisions.sh"

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "hooks" / "inject-project-decisions.sh").exists(),
        reason="Hook script not found",
    )
    def test_hook_returns_decisions_for_scoped_file(self, store, project):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Also need the DB for the hook's inline Python
        store.sync_from_dump()

        hook_input = json.dumps({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(project / "hooks" / "lib" / "om_write.py"),
                "old_string": "x",
                "new_string": "y",
            },
        })

        env = os.environ.copy()
        env["CLAUDE_SESSION_ID"] = f"test-e2e-{os.getpid()}"
        env["CLAUDE_TEMP_DIR"] = str(project / "tmp")
        (project / "tmp").mkdir(exist_ok=True)

        result = subprocess.run(
            ["bash", str(self.HOOK_SCRIPT)],
            input=hook_input,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode == 0

        if result.stdout.strip():
            output = json.loads(result.stdout)
            # Hook now blocks with decision:block format
            assert output.get("decision") == "block"
            reason = output.get("reason", "")
            assert "om_write" in reason

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "hooks" / "inject-project-decisions.sh").exists(),
        reason="Hook script not found",
    )
    def test_hook_blocks_every_time(self, store, project):
        """No dedup — second edit to same file also blocks."""
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)
        store.sync_from_dump()

        hook_input = json.dumps({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(project / "hooks" / "lib" / "om_write.py"),
                "old_string": "x",
                "new_string": "y",
            },
        })

        env = os.environ.copy()
        env["CLAUDE_SESSION_ID"] = f"test-e2e-dedup-{os.getpid()}"
        env["CLAUDE_TEMP_DIR"] = str(project / "tmp")
        (project / "tmp").mkdir(exist_ok=True)

        # First call — should block
        r1 = subprocess.run(
            ["bash", str(self.HOOK_SCRIPT)],
            input=hook_input, capture_output=True, text=True, env=env, timeout=10,
        )
        assert r1.stdout.strip()
        assert json.loads(r1.stdout)["decision"] == "block"

        # Second call — should ALSO block (no dedup)
        r2 = subprocess.run(
            ["bash", str(self.HOOK_SCRIPT)],
            input=hook_input, capture_output=True, text=True, env=env, timeout=10,
        )
        assert r2.stdout.strip()
        assert json.loads(r2.stdout)["decision"] == "block"

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "hooks" / "inject-project-decisions.sh").exists(),
        reason="Hook script not found",
    )
    def test_hook_returns_empty_for_unscoped_file(self, store, project):
        for d in SAMPLE_DECISIONS:
            store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)
        store.sync_from_dump()

        hook_input = json.dumps({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(project / "some" / "random" / "file.txt"),
                "old_string": "x",
                "new_string": "y",
            },
        })

        env = os.environ.copy()
        env["CLAUDE_SESSION_ID"] = f"test-e2e-unscoped-{os.getpid()}"
        env["CLAUDE_TEMP_DIR"] = str(project / "tmp")
        (project / "tmp").mkdir(exist_ok=True)

        result = subprocess.run(
            ["bash", str(self.HOOK_SCRIPT)],
            input=hook_input,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        assert result.returncode == 0
        # Should be empty — no decisions for unscoped file
        assert not result.stdout.strip()


# ---------------------------------------------------------------------------
# 7. Full pipeline: record → dump → nuke → rebuild → search → rules
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_full_portability_cycle(self, project):
        """Simulate: record decisions, dump SQL, copy to new machine, rebuild, verify."""
        # Phase 1: Original machine
        store1 = DecisionStore(project)
        for d in SAMPLE_DECISIONS:
            store1.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store1, dump_path)

        # Phase 2: "New machine" — only SQL dump exists
        new_root = project / "clone"
        new_root.mkdir()
        (new_root / ".git").mkdir()
        (new_root / ".claude").mkdir()
        shutil.copy2(dump_path, new_root / ".claude" / "decisions.sql")

        # Phase 3: Rebuild on new machine
        store2 = DecisionStore(new_root)
        store2.sync_from_dump()

        # Verify counts match
        all_d = store2.list_all()
        assert len(all_d) == len(SAMPLE_DECISIONS)

        # Verify scopes survived
        for d in all_d:
            orig = next(s for s in SAMPLE_DECISIONS if s.content == d.content)
            assert len(d.scopes) == len(orig.scopes)

        # Phase 4: Search works on rebuilt DB
        conn = store2._get_connection()
        engine = SearchEngine(conn, EmbeddingProvider())
        engine.rebuild_index()
        results = engine.keyword_search("persistence surfaces")
        assert len(results) > 0

        # Phase 5: Rules generator works on rebuilt DB
        out = generate_rules(str(new_root))
        content = Path(out).read_text()
        assert "om_write" in content
        assert "signal_processor" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
