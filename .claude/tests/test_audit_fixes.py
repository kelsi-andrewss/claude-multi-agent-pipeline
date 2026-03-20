"""Tests for audit findings fixes (epic-215).

Validates the fixes for BUG-1 through BUG-6, CQ-1 through CQ-9.
Focuses on regressions that can be caught statically or with unit tests.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_file(rel_path: str) -> str:
    """Read a file relative to repo root."""
    return (REPO_ROOT / rel_path).read_text()


def find_python_c_with_variable_interpolation(content: str) -> list[str]:
    """Find python3 -c blocks that interpolate shell variables inside strings.

    Matches patterns like: with open('$VAR')  or  float('$VAR')
    These are shell injection vectors when $VAR is attacker-influenced.
    """
    # Match python3 -c "..." blocks that contain '$VAR' inside quotes
    matches = []
    for m in re.finditer(r"python3\s+-c\s+\"(.*?)\"", content, re.DOTALL):
        block = m.group(1)
        # Look for shell variable inside Python string literals
        if re.search(r"['\"]?\$\w+['\"]?", block):
            matches.append(block[:80])
    return matches


# ---------------------------------------------------------------------------
# BUG-1 & BUG-2: Shell injection regression tests
# ---------------------------------------------------------------------------

class TestShellInjectionRegression:
    """Ensure no hook script uses python3 -c with shell variable interpolation."""

    HOOK_DIR = REPO_ROOT / "hooks"

    def _scan_file(self, path: Path) -> list[str]:
        content = path.read_text()
        return find_python_c_with_variable_interpolation(content)

    def test_no_shell_injection_in_cost_alert(self):
        """BUG-2: cost-alert.sh must not interpolate variables in python3 -c."""
        matches = self._scan_file(self.HOOK_DIR / "cost-alert.sh")
        assert matches == [], f"Shell injection pattern found: {matches}"

    def test_no_shell_injection_in_track_skill_changes(self):
        """BUG-1: track-skill-changes.sh must not interpolate variables in python3 -c."""
        matches = self._scan_file(self.HOOK_DIR / "track-skill-changes.sh")
        assert matches == [], f"Shell injection pattern found: {matches}"

    def test_cost_alert_uses_heredoc_pattern(self):
        """Verify cost-alert.sh uses safe heredoc + sys.argv pattern."""
        content = read_file("hooks/cost-alert.sh")
        assert "<<'PYEOF'" in content or "<<'EOF'" in content, \
            "cost-alert.sh should use single-quoted heredoc delimiter"
        assert "sys.argv[1]" in content, \
            "cost-alert.sh should pass variables via sys.argv"

    def test_track_skill_changes_uses_heredoc_pattern(self):
        """Verify track-skill-changes.sh uses safe heredoc + sys.argv pattern."""
        content = read_file("hooks/track-skill-changes.sh")
        assert "sys.argv[1]" in content, \
            "track-skill-changes.sh should pass FILE_PATH via sys.argv"

    def test_no_shell_injection_in_any_hook(self):
        """Scan ALL hook scripts for the vulnerable pattern."""
        violations = []
        for sh_file in self.HOOK_DIR.glob("*.sh"):
            matches = self._scan_file(sh_file)
            if matches:
                violations.append((sh_file.name, matches))
        assert violations == [], \
            f"Shell injection patterns found: {violations}"

    def test_cost_alert_no_tracker_dir(self):
        """CQ-6: TRACKER_DIR constant should not exist."""
        content = read_file("hooks/cost-alert.sh")
        assert "TRACKER_DIR=" not in content, \
            "Dead TRACKER_DIR constant should be removed"


# ---------------------------------------------------------------------------
# BUG-3: SQLite timeout in signal_processor.py
# ---------------------------------------------------------------------------

class TestSignalProcessorFixes:
    """Verify signal_processor.py audit fixes."""

    def test_all_sqlite_connects_have_timeout(self):
        """BUG-3: Every sqlite3.connect() call must have a timeout parameter."""
        content = read_file("hooks/lib/signal_processor.py")
        # Find all sqlite3.connect calls
        connects = re.findall(r"sqlite3\.connect\([^)]+\)", content)
        for call in connects:
            assert "timeout" in call, \
                f"sqlite3.connect without timeout: {call}"

    def test_no_prev_assistant_had_tool_use(self):
        """CQ-3: Dead variable prev_assistant_had_tool_use should be removed."""
        content = read_file("hooks/lib/signal_processor.py")
        assert "prev_assistant_had_tool_use" not in content, \
            "Dead variable prev_assistant_had_tool_use should be removed"

    def test_no_check_promoted_function(self):
        """CQ-4: Dead function _check_promoted should be removed."""
        content = read_file("hooks/lib/signal_processor.py")
        assert "def _check_promoted" not in content, \
            "Dead function _check_promoted should be removed"

    def test_constant_renamed_to_per_phase(self):
        """CQ-9: MAX_EMBEDDING_CALLS_PER_SESSION renamed to PER_PHASE."""
        content = read_file("hooks/lib/signal_processor.py")
        assert "MAX_EMBEDDING_CALLS_PER_SESSION" not in content, \
            "Old constant name should not exist"
        assert "MAX_EMBEDDING_CALLS_PER_PHASE" in content, \
            "New constant name should exist"


# ---------------------------------------------------------------------------
# BUG-4: Scope matching in inject-project-decisions.sh
# ---------------------------------------------------------------------------

class TestScopeMatching:
    """Verify the SQL scope matching logic doesn't produce false positives."""

    def test_no_like_substring_pattern(self):
        """BUG-4: SQL must not use LIKE '%' || scope_value || '%' (substring match)."""
        content = read_file("hooks/inject-project-decisions.sh")
        assert "'%' || ds.scope_value || '%'" not in content, \
            "Substring LIKE pattern produces false positives"

    def test_uses_prefix_or_basename_matching(self):
        """Verify the fix uses path-prefix or basename matching."""
        content = read_file("hooks/inject-project-decisions.sh")
        # Should have one of these patterns
        has_prefix = "LIKE ds.scope_value || '%'" in content
        has_basename = "LIKE '%/' || ds.scope_value" in content
        assert has_prefix or has_basename, \
            "Should use path-prefix or basename matching"

    def test_scope_matching_logic(self):
        """Test the actual SQL scope matching against an in-memory DB."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY, content TEXT, status TEXT)")
        conn.execute("CREATE TABLE decision_scopes (decision_id INTEGER, scope_value TEXT)")

        # Insert test decisions with different scope values
        conn.execute("INSERT INTO decisions VALUES (1, 'test decision for hooks/lib/', 'active')")
        conn.execute("INSERT INTO decision_scopes VALUES (1, 'hooks/lib/')")

        conn.execute("INSERT INTO decisions VALUES (2, 'test decision for py files', 'active')")
        conn.execute("INSERT INTO decision_scopes VALUES (2, 'py')")

        conn.execute("INSERT INTO decisions VALUES (3, 'test for signal_processor.py', 'active')")
        conn.execute("INSERT INTO decision_scopes VALUES (3, 'signal_processor.py')")

        # The fixed query
        query = """
            SELECT DISTINCT d.id, d.content
            FROM decisions d
            LEFT JOIN decision_scopes ds ON d.id = ds.decision_id
            WHERE d.status = 'active'
              AND (ds.scope_value IS NULL
                   OR ? LIKE ds.scope_value || '%'
                   OR ? LIKE '%/' || ds.scope_value
                   OR ds.scope_value = ?)
            LIMIT 5
        """

        # Test: hooks/lib/signal_processor.py should match decision 1 (prefix) and 3 (basename)
        file_path = "hooks/lib/signal_processor.py"
        basename = os.path.basename(file_path)
        rows = conn.execute(query, (file_path, file_path, basename)).fetchall()
        ids = {r[0] for r in rows}
        assert 1 in ids, "Should match hooks/lib/ prefix"
        assert 3 in ids, "Should match signal_processor.py basename"
        assert 2 not in ids, "Should NOT match 'py' (too short/broad)"

        # Test: src/apply.tsx should NOT match scope 'py'
        file_path2 = "src/apply.tsx"
        basename2 = os.path.basename(file_path2)
        rows2 = conn.execute(query, (file_path2, file_path2, basename2)).fetchall()
        ids2 = {r[0] for r in rows2}
        assert 2 not in ids2, "Scope 'py' must NOT match apply.tsx"

        conn.close()


# ---------------------------------------------------------------------------
# BUG-5: om_write.py warning suppression
# ---------------------------------------------------------------------------

class TestOmWriteWarning:
    """Verify om_write.py suppresses repeated Ollama fallback warnings."""

    def test_has_warning_flag(self):
        """BUG-5: Module should have _ollama_fallback_warned flag."""
        content = read_file("hooks/lib/om_write.py")
        assert "_ollama_fallback_warned" in content, \
            "Should have _ollama_fallback_warned flag"

    def test_warning_guarded_by_flag(self):
        """The stderr print should be inside an if-not-warned check."""
        content = read_file("hooks/lib/om_write.py")
        # Look for the pattern: if not _ollama_fallback_warned
        assert "if not _ollama_fallback_warned" in content, \
            "Warning should be guarded by the flag check"


# ---------------------------------------------------------------------------
# BUG-6: stop_processor.py migration guard
# ---------------------------------------------------------------------------

class TestStopProcessorMigration:
    """Verify stop_processor.py uses safe migration pattern."""

    def test_no_executescript_for_migration(self):
        """BUG-6: Should not use executescript for schema migration."""
        content = read_file("hooks/lib/stop_processor.py")
        # The migration section should not use executescript
        # (executescript has implicit commit that prevents rollback)
        migration_section = content[content.find("dismissed"):][:500] if "dismissed" in content else ""
        assert "executescript" not in migration_section, \
            "Migration should use individual execute() calls, not executescript"

    def test_uses_case_insensitive_check(self):
        """Migration guard should be case-insensitive."""
        content = read_file("hooks/lib/stop_processor.py")
        # Should use .lower() for the dismissed check
        has_lower = ".lower()" in content
        has_case_insensitive = "PRAGMA table_info" in content
        assert has_lower or has_case_insensitive, \
            "Migration guard should be case-insensitive or use PRAGMA check"


# ---------------------------------------------------------------------------
# CQ-1: Stale corrections.md reference
# ---------------------------------------------------------------------------

class TestTier2Context:
    """Verify inject-tier2-context.sh has correct pipeline description."""

    def test_no_corrections_md_as_active_surface(self):
        """CQ-1: Should not reference corrections.md as an active logging target."""
        content = read_file("hooks/inject-tier2-context.sh")
        # Find the infra_corrections fragment
        match = re.search(r"infra_corrections\)(.*?);;", content, re.DOTALL)
        if match:
            fragment = match.group(1)
            # "No corrections.md — that surface is dead" is acceptable (documenting it's dead)
            # "logged to corrections.md" is not (implying it's active)
            assert "logged to corrections.md" not in fragment, \
                "infra_corrections should not reference corrections.md as active"
            assert "correction_groups" in fragment, \
                "Should reference correction_groups table"


# ---------------------------------------------------------------------------
# CQ-2: guard-direct-edit.sh column name
# ---------------------------------------------------------------------------

class TestGuardDirectEdit:
    """Verify guard-direct-edit.sh uses correct column name."""

    def test_uses_write_files_not_write_targets(self):
        """CQ-2: SQL should query write_files, not write_targets."""
        content = read_file("hooks/guard-direct-edit.sh")
        assert "write_targets" not in content, \
            "Should use write_files, not write_targets"
        assert "write_files" in content, \
            "Should query the write_files column"


# ---------------------------------------------------------------------------
# CQ-5: Duplicate spawn in load-session-context.sh
# ---------------------------------------------------------------------------

class TestLoadSessionContext:
    """Verify load-session-context.sh has no duplicate spawns."""

    def test_single_decision_freshness_spawn(self):
        """CQ-5: decision-freshness.py should be spawned exactly once."""
        content = read_file("hooks/load-session-context.sh")
        spawn_count = content.count("decision-freshness.py")
        # Should appear in at most 2 lines: one spawn + one comment (if any)
        # But the actual nohup spawn pattern should appear only once
        nohup_count = len(re.findall(r"nohup.*decision-freshness\.py", content))
        assert nohup_count == 1, \
            f"Expected exactly 1 nohup spawn of decision-freshness.py, found {nohup_count}"


# ---------------------------------------------------------------------------
# CQ-7: DecisionStore.get_connection()
# ---------------------------------------------------------------------------

class TestDecisionStorePublicMethod:
    """Verify DecisionStore has public get_connection method."""

    def test_get_connection_exists(self):
        """CQ-7: DecisionStore should have a public get_connection method."""
        content = read_file("decision_memory/store.py")
        assert "def get_connection(self)" in content, \
            "DecisionStore should have public get_connection method"

    def test_server_uses_public_method(self):
        """CQ-7: server.py should not call _get_connection directly."""
        content = read_file("mcp-servers/decisions/server.py")
        assert "._get_connection()" not in content, \
            "server.py should use .get_connection(), not ._get_connection()"
        assert ".get_connection()" in content, \
            "server.py should call the public get_connection method"

    def test_get_connection_returns_working_connection(self):
        """Verify get_connection actually returns a usable SQLite connection."""
        sys.path.insert(0, str(REPO_ROOT))
        from decision_memory.store import DecisionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".claude").mkdir()
            store = DecisionStore(project_root)
            conn = store.get_connection()
            try:
                # Should be able to execute queries
                result = conn.execute("SELECT 1").fetchone()
                assert result == (1,)
                # Should have WAL mode
                journal = conn.execute("PRAGMA journal_mode").fetchone()
                assert journal[0] == "wal"
            finally:
                conn.close()


# ---------------------------------------------------------------------------
# CQ-8: Threshold coupling comment
# ---------------------------------------------------------------------------

class TestThresholdCoupling:
    """Verify log-correction.sh documents the threshold coupling."""

    def test_has_coupling_comment(self):
        """CQ-8: The hardcoded 3 should have a comment about PROMOTION_THRESHOLD."""
        content = read_file("scripts/log-correction.sh")
        # Find the line with >= 3
        lines = [l for l in content.splitlines() if ">= 3" in l or ">=3" in l]
        assert len(lines) > 0, "Should have a line with >= 3 threshold"
        # At least one of those lines should reference signal_processor
        has_comment = any("signal_processor" in l or "PROMOTION_THRESHOLD" in l for l in lines)
        assert has_comment, \
            "Threshold line should reference PROMOTION_THRESHOLD or signal_processor.py"
