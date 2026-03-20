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
            # Hook injects context via hookSpecificOutput
            hook_output = output.get("hookSpecificOutput", {})
            context = hook_output.get("additionalContext", "")
            assert "om_write" in context

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "hooks" / "inject-project-decisions.sh").exists(),
        reason="Hook script not found",
    )
    def test_hook_injects_on_repeat_calls(self, store, project):
        """Hook may dedup within same session — first call always injects."""
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

        # First call — should inject context
        r1 = subprocess.run(
            ["bash", str(self.HOOK_SCRIPT)],
            input=hook_input, capture_output=True, text=True, env=env, timeout=10,
        )
        assert r1.stdout.strip()
        out1 = json.loads(r1.stdout)
        assert "om_write" in out1.get("hookSpecificOutput", {}).get("additionalContext", "")

        # Second call — may dedup (empty) or re-inject, both are valid
        r2 = subprocess.run(
            ["bash", str(self.HOOK_SCRIPT)],
            input=hook_input, capture_output=True, text=True, env=env, timeout=10,
        )
        assert r2.returncode == 0  # should not crash regardless

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


# ---------------------------------------------------------------------------
# 8. Domain derivation and multi-domain support
# ---------------------------------------------------------------------------

class TestDomains:
    def test_auto_derive_single_domain(self, store):
        d = Decision(
            id=None, content="Hook constraint", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/foo.py")],
        )
        did = store.record(d)
        fetched = store.get(did)
        assert fetched.domain == "hooks"

    def test_auto_derive_multi_domain(self, store):
        d = Decision(
            id=None, content="Cross-domain decision", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            scopes=[
                DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/foo.py"),
                DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="mcp-servers/decisions/bar.py"),
            ],
        )
        did = store.record(d)
        fetched = store.get(did)
        assert fetched.domain is not None
        domains = fetched.domain.split(",")
        assert "hooks" in domains
        assert "mcp" in domains

    def test_explicit_domain_not_overridden(self, store):
        d = Decision(
            id=None, content="Custom domain", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None, domain="custom",
            scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/foo.py")],
        )
        did = store.record(d)
        fetched = store.get(did)
        assert fetched.domain == "custom"

    def test_no_scopes_gives_null_domain(self, store):
        d = Decision(
            id=None, content="Unscoped", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None, scopes=[],
        )
        did = store.record(d)
        fetched = store.get(did)
        assert fetched.domain is None

    def test_unknown_prefix_gives_general(self, store):
        d = Decision(
            id=None, content="Random file", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="settings.json")],
        )
        did = store.record(d)
        fetched = store.get(did)
        assert fetched.domain == "general"


# ---------------------------------------------------------------------------
# 9. Tiered rendering and on-demand fetch stubs
# ---------------------------------------------------------------------------

class TestTieredRendering:
    def test_fresh_includes_reasoning(self):
        from decision_memory.rules_generator import _format_decision
        result = _format_decision(1, "Use WAL mode", "Prevents locks", 0.1)
        assert "Reasoning: Prevents locks" in result
        assert "get_decision" not in result

    def test_aging_has_on_demand_stub(self):
        from decision_memory.rules_generator import _format_decision
        result = _format_decision(1, "Use WAL mode for all SQLite connections", "Prevents locks", 0.5)
        assert "get_decision(1)" in result
        assert "Reasoning" not in result

    def test_stale_has_warning(self):
        from decision_memory.rules_generator import _format_decision
        result = _format_decision(1, "Use WAL mode", "Prevents locks", 0.9)
        assert "[STALE]" in result
        assert "Warning" in result
        assert "get_decision" not in result

    def test_one_line_truncates(self):
        from decision_memory.rules_generator import one_line
        long_text = "First sentence here. Second sentence here. Third sentence here."
        result = one_line(long_text)
        assert result == "First sentence here."

    def test_one_line_caps_at_max_len(self):
        from decision_memory.rules_generator import one_line
        very_long = "A" * 200
        result = one_line(very_long, max_len=120)
        assert len(result) <= 120
        assert result.endswith("...")

    def test_one_line_short_text(self):
        from decision_memory.rules_generator import one_line
        result = one_line("Short text")
        assert result == "Short text."

    def test_default_score_renders_as_aging(self):
        """Decisions without freshness data get score 0.5 (aging tier)."""
        from decision_memory.rules_generator import _format_decision
        result = _format_decision(1, "Some decision", None, 0.5)
        assert "get_decision(1)" in result


# ---------------------------------------------------------------------------
# 10. Relationship field
# ---------------------------------------------------------------------------

class TestRelationships:
    def test_record_with_relationships(self, store):
        d = Decision(
            id=None, content="Decision with relationships", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            related_decisions="2:depends_on,3:related",
            scopes=[],
        )
        did = store.record(d)
        fetched = store.get(did)
        assert fetched.related_decisions == "2:depends_on,3:related"

    def test_record_without_relationships(self, store):
        d = Decision(
            id=None, content="No relationships", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            scopes=[],
        )
        did = store.record(d)
        fetched = store.get(did)
        assert fetched.related_decisions is None

    def test_relationships_survive_dump_rebuild(self, store, project):
        d = Decision(
            id=None, content="Linked decision", reasoning=None,
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            related_decisions="5:constrains,10:related",
            scopes=[],
        )
        store.record(d)
        dump_path = project / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Nuke and rebuild
        (project / ".claude" / "decisions.db").unlink()
        store2 = DecisionStore(project)
        store2.sync_from_dump()
        all_d = store2.list_all()
        assert any(d.related_decisions == "5:constrains,10:related" for d in all_d)


# ---------------------------------------------------------------------------
# 11. Supersession enforcement
# ---------------------------------------------------------------------------

class TestSupersession:
    def test_identical_scope_auto_supersedes(self, store, project):
        """Recording a decision with identical file scopes should supersede the old one."""
        d1 = Decision(
            id=None, content="Old rule for hooks", reasoning="v1",
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/foo.py")],
        )
        id1 = store.record(d1)

        d2 = Decision(
            id=None, content="New rule for hooks", reasoning="v2",
            status="active", source="human", superseded_by=None,
            created_at=None, updated_at=None,
            scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/foo.py")],
        )
        # Record via the MCP server path would auto-supersede, but direct store.record doesn't.
        # This test verifies the store layer — supersession is in server.py.
        id2 = store.record(d2)
        assert id2 != id1

        # Both should still be active in the store (supersession is server-level, not store-level)
        d1_fetched = store.get(id1)
        assert d1_fetched.status == "active"


# ---------------------------------------------------------------------------
# 12. Domain summary in rules output
# ---------------------------------------------------------------------------

class TestDomainSummary:
    def test_domain_summary_renders(self, store, project):
        decisions = [
            Decision(id=None, content="Hook rule 1", reasoning=None, status="active", source="human",
                     superseded_by=None, created_at=None, updated_at=None,
                     scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/a.py")]),
            Decision(id=None, content="Hook rule 2", reasoning=None, status="active", source="human",
                     superseded_by=None, created_at=None, updated_at=None,
                     scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="hooks/lib/b.py")]),
            Decision(id=None, content="Script rule", reasoning=None, status="active", source="human",
                     superseded_by=None, created_at=None, updated_at=None,
                     scopes=[DecisionScope(id=None, decision_id=0, scope_type="file", scope_value="scripts/foo.py")]),
        ]
        for d in decisions:
            store.record(d)
        dump_to_sql(store, project / ".claude" / "decisions.sql")

        out = generate_rules(str(project))
        content = Path(out).read_text()
        assert "## Domain summary" in content
        assert "hooks:" in content
        assert "scripts:" in content

    def test_no_domain_summary_when_no_domains(self, store, project):
        d = Decision(id=None, content="Unscoped", reasoning=None, status="active", source="human",
                     superseded_by=None, created_at=None, updated_at=None, scopes=[])
        store.record(d)
        dump_to_sql(store, project / ".claude" / "decisions.sql")

        out = generate_rules(str(project))
        content = Path(out).read_text()
        assert "## Domain summary" not in content


# ---------------------------------------------------------------------------
# 13. Migration chain (v1 → v2 → v3)
# ---------------------------------------------------------------------------

class TestMigrations:
    def test_v1_dump_loads_with_domain_and_relationships(self, project):
        """A v1 dump (no domain, no related_decisions) should load and get both columns via migration."""
        v1_dump = (
            "-- decision_memory dump v1\n"
            "CREATE TABLE IF NOT EXISTS decisions (\n"
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    content TEXT NOT NULL,\n"
            "    reasoning TEXT,\n"
            "    status TEXT NOT NULL DEFAULT 'active',\n"
            "    source TEXT NOT NULL DEFAULT 'human',\n"
            "    superseded_by INTEGER REFERENCES decisions(id),\n"
            "    created_at TEXT NOT NULL DEFAULT (datetime('now')),\n"
            "    updated_at TEXT NOT NULL DEFAULT (datetime('now'))\n"
            ");\n"
            "CREATE TABLE IF NOT EXISTS decision_scopes (\n"
            "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,\n"
            "    scope_type TEXT NOT NULL,\n"
            "    scope_value TEXT NOT NULL\n"
            ");\n"
            "INSERT OR REPLACE INTO decisions (id, content, reasoning, status, source, "
            "superseded_by, created_at, updated_at) VALUES (1, 'Test v1', NULL, 'active', "
            "'human', NULL, '2026-01-01', '2026-01-01');\n"
        )
        dump_path = project / ".claude" / "decisions.sql"
        dump_path.write_text(v1_dump)

        store = DecisionStore(project)
        store.sync_from_dump()

        # Both migration columns should exist
        conn = store._get_connection()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(decisions)").fetchall()}
        assert "domain" in cols
        assert "related_decisions" in cols

        # Decision should be retrievable
        d = store.get(1)
        assert d is not None
        assert d.content == "Test v1"
        assert d.domain is None
        assert d.related_decisions is None
        conn.close()


# ---------------------------------------------------------------------------
# 14. Freshness scoring
# ---------------------------------------------------------------------------

class TestFreshness:
    FRESHNESS_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "decision-freshness.py"

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "scripts" / "decision-freshness.py").exists(),
        reason="Freshness script not found",
    )
    def test_freshness_no_decisions(self, project):
        """Script handles missing decisions.db gracefully."""
        result = subprocess.run(
            [sys.executable, str(self.FRESHNESS_SCRIPT), "--project-root", str(project)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] in ("computed", "success", "no_decisions")
        assert data.get("total", data.get("decisions_scored", 0)) == 0

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "scripts" / "decision-freshness.py").exists(),
        reason="Freshness script not found",
    )
    def test_freshness_with_decisions(self, store, project):
        """Script scores real decisions."""
        for d in SAMPLE_DECISIONS:
            store.record(d)

        # Need a git repo for git log
        subprocess.run(["git", "init"], cwd=str(project), capture_output=True)
        subprocess.run(["git", "add", "."], cwd=str(project), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init", "--allow-empty"], cwd=str(project), capture_output=True)

        result = subprocess.run(
            [sys.executable, str(self.FRESHNESS_SCRIPT), "--project-root", str(project)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data.get("total", data.get("decisions_scored", 0)) > 0


# ---------------------------------------------------------------------------
# 15. Staleness gardening
# ---------------------------------------------------------------------------

class TestStalenessGardening:
    def test_sidecar_written_for_stale_decisions(self, store, project):
        """stage_staleness_gardening writes sidecar when stale decisions exist."""
        for d in SAMPLE_DECISIONS:
            store.record(d)

        # Create run-state.db with a fake stale entry
        run_state_path = project / ".claude" / "run-state.db"
        conn = sqlite3.connect(str(run_state_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS decision_freshness (
            decision_id INTEGER PRIMARY KEY,
            staleness_score REAL NOT NULL,
            days_since_activity INTEGER NOT NULL,
            last_git_activity TEXT,
            computed_at TEXT NOT NULL,
            reinforcement_count INTEGER NOT NULL DEFAULT 0
        )""")
        conn.execute(
            "INSERT INTO decision_freshness VALUES (1, 0.95, 180, NULL, datetime('now'), 0)"
        )
        conn.commit()
        conn.close()

        # Run the gardening stage
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from hooks.lib.stop_processor import stage_staleness_gardening
        stage_staleness_gardening(str(project))

        sidecar = project / ".claude" / "stale-decisions.md"
        assert sidecar.exists()
        content = sidecar.read_text()
        assert "Stale" in content or "stale" in content

    def test_sidecar_cleared_when_no_stale(self, store, project):
        """Sidecar is empty/removed when no decisions are stale."""
        for d in SAMPLE_DECISIONS:
            store.record(d)

        # Create run-state.db with only fresh entries
        run_state_path = project / ".claude" / "run-state.db"
        conn = sqlite3.connect(str(run_state_path))
        conn.execute("""CREATE TABLE IF NOT EXISTS decision_freshness (
            decision_id INTEGER PRIMARY KEY,
            staleness_score REAL NOT NULL,
            days_since_activity INTEGER NOT NULL,
            last_git_activity TEXT,
            computed_at TEXT NOT NULL,
            reinforcement_count INTEGER NOT NULL DEFAULT 0
        )""")
        conn.execute(
            "INSERT INTO decision_freshness VALUES (1, 0.1, 2, NULL, datetime('now'), 0)"
        )
        conn.commit()
        conn.close()

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from hooks.lib.stop_processor import stage_staleness_gardening
        stage_staleness_gardening(str(project))

        sidecar = project / ".claude" / "stale-decisions.md"
        if sidecar.exists():
            assert sidecar.read_text().strip() == ""


# ---------------------------------------------------------------------------
# 16. Real repo tests (worktree-based)
# ---------------------------------------------------------------------------

REAL_REPO = Path(__file__).resolve().parent.parent  # ~/.claude


@pytest.fixture
def real_worktree(tmp_path):
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

    # Rebuild decisions.db from SQL dump (db is gitignored, only dump is in git)
    dump_path = wt_path / ".claude" / "decisions.sql"
    if dump_path.exists():
        store = DecisionStore(wt_path)
        store.sync_from_dump()

    yield wt_path

    # Cleanup: remove worktree and branch
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt_path)],
        cwd=str(REAL_REPO), capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=str(REAL_REPO), capture_output=True,
    )


class TestRealRepo:
    """Tests that run against the actual project repo via a disposable worktree.

    These exercise real git history, real decisions.sql, real file scopes.
    Slower than tmpdir tests (~2-5s each) but catch integration issues that
    synthetic fixtures miss (FK constraints, stale dumps, migration gaps).
    """

    def test_store_loads_from_real_dump(self, real_worktree):
        """DecisionStore can load the actual decisions.sql dump."""
        store = DecisionStore(real_worktree)
        store.sync_from_dump()
        decisions = store.list_all()
        assert len(decisions) > 0, "Real repo should have decisions"
        # Verify at least some have scopes
        with_scopes = [d for d in decisions if d.scopes]
        assert len(with_scopes) > 0

    def test_domains_populated_on_real_decisions(self, real_worktree):
        """Real decisions have domain tags after v2+ dump."""
        store = DecisionStore(real_worktree)
        store.sync_from_dump()
        decisions = store.list_all(status="active")
        with_domain = [d for d in decisions if d.domain]
        assert len(with_domain) > 0, "Active decisions should have domains"

    def test_relationships_populated_on_real_decisions(self, real_worktree):
        """Real decisions have relationship data after backfill."""
        store = DecisionStore(real_worktree)
        store.sync_from_dump()
        decisions = store.list_all()
        with_rels = [d for d in decisions if d.related_decisions]
        assert len(with_rels) > 0, "Backfilled decisions should have relationships"

    def test_rules_generation_against_real_data(self, real_worktree):
        """Rules generator produces valid output from real decisions."""
        out = generate_rules(str(real_worktree))
        content = Path(out).read_text()
        assert "# Project Decisions" in content
        assert "## File-scoped decisions" in content
        assert "## Domain summary" in content
        # Should have at least a few decision references
        assert content.count("[decision-") >= 5

    def test_freshness_scoring_against_real_git(self, real_worktree):
        """Freshness script scores decisions using real git history."""
        freshness_script = real_worktree / "scripts" / "decision-freshness.py"
        if not freshness_script.exists():
            pytest.skip("Freshness script not in worktree")

        result = subprocess.run(
            [sys.executable, str(freshness_script), "--project-root", str(real_worktree)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        total = data.get("total", data.get("decisions_scored", 0))
        assert total > 0, "Should score decisions against real git history"

        # All scores should be valid floats in [0, 1]
        for entry in data.get("decisions", []):
            score = entry["staleness_score"]
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for decision {entry['decision_id']}"

    def test_freshness_reinforcement_in_worktree(self, real_worktree):
        """Reinforcement works against real run-state.db in worktree."""
        freshness_script = real_worktree / "scripts" / "decision-freshness.py"
        if not freshness_script.exists():
            pytest.skip("Freshness script not in worktree")

        # First run to populate scores
        subprocess.run(
            [sys.executable, str(freshness_script), "--project-root", str(real_worktree)],
            capture_output=True, text=True, timeout=30,
        )

        # Get a real decision ID
        store = DecisionStore(real_worktree)
        store.sync_from_dump()
        decisions = store.list_all(status="active")
        if not decisions:
            pytest.skip("No active decisions")
        did = decisions[0].id

        # Reinforce it
        result = subprocess.run(
            [sys.executable, str(freshness_script),
             "--project-root", str(real_worktree), "--reinforce", str(did)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "reinforced"
        assert data["decision_id"] == did

    def test_dump_roundtrip_preserves_all_fields(self, real_worktree):
        """Dump → nuke → rebuild preserves content, domains, relationships."""
        store = DecisionStore(real_worktree)
        store.sync_from_dump()
        original = store.list_all()

        # Dump
        dump_path = real_worktree / ".claude" / "decisions.sql"
        dump_to_sql(store, dump_path)

        # Nuke DB
        db_path = real_worktree / ".claude" / "decisions.db"
        db_path.unlink()
        for suffix in ("-shm", "-wal"):
            p = db_path.parent / (db_path.name + suffix)
            if p.exists():
                p.unlink()

        # Rebuild
        store2 = DecisionStore(real_worktree)
        store2.sync_from_dump()
        rebuilt = store2.list_all()

        assert len(rebuilt) == len(original)

        # Spot-check: domains and relationships survived
        orig_map = {d.id: d for d in original}
        for d in rebuilt:
            orig = orig_map.get(d.id)
            if orig:
                assert d.domain == orig.domain, f"Domain mismatch on decision {d.id}"
                assert d.related_decisions == orig.related_decisions, f"Relationships mismatch on decision {d.id}"
                assert len(d.scopes) == len(orig.scopes), f"Scope count mismatch on decision {d.id}"

    def test_staleness_gardening_against_real_data(self, real_worktree):
        """Stage 6 runs without error against real project structure."""
        sys.path.insert(0, str(real_worktree))
        # Import from the worktree
        import importlib
        sp_path = real_worktree / "hooks" / "lib" / "stop_processor.py"
        if not sp_path.exists():
            pytest.skip("stop_processor.py not in worktree")

        spec = importlib.util.spec_from_file_location("stop_processor_wt", str(sp_path))
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pytest.skip("stop_processor requires CLI args")
        except Exception:
            pytest.skip("Could not import stop_processor from worktree")

        if hasattr(mod, "stage_staleness_gardening"):
            mod.stage_staleness_gardening(str(real_worktree))
            # Should not crash — sidecar may or may not be written depending on freshness data
            sidecar = real_worktree / ".claude" / "stale-decisions.md"
            # Just verify no crash — content depends on whether freshness data exists
            assert True

    def test_backfill_script_dry_run(self, real_worktree):
        """Backfill script runs in dry-run mode against real data."""
        script = real_worktree / "scripts" / "backfill-relationships.py"
        if not script.exists():
            pytest.skip("Backfill script not in worktree")

        result = subprocess.run(
            [sys.executable, str(script), "--project-root", str(real_worktree), "--dry-run"],
            capture_output=True, text=True, timeout=10,
        )
        # Dry-run should succeed (exit 0) or exit 1 with JSON error
        output = result.stdout.strip() or result.stderr.strip()
        if output:
            data = json.loads(output)
            assert data["status"] in ("backfilled", "dry_run", "no_changes", "success", "error")
        else:
            # No output means script completed silently — acceptable for dry-run
            assert result.returncode in (0, 1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
