"""Tests for _apply_plan_to_story in tools_pm_helpers."""

import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure the gemini server package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools_pm_helpers import _apply_plan_to_story


def _create_test_db(tmp_path):
    """Create a file-based SQLite DB with full schema including read_files and story_dependencies."""
    db_path = tmp_path / "test_epics.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE epics (
          id              TEXT PRIMARY KEY,
          title           TEXT NOT NULL,
          branch          TEXT,
          pr_number       INTEGER,
          persistent      INTEGER DEFAULT 0,
          state           TEXT DEFAULT 'active' CHECK(state IN ('active','done','shipped')),
          milestone_order INTEGER,
          target_date     TEXT,
          description     TEXT
        );

        CREATE TABLE stories (
          id              TEXT PRIMARY KEY,
          epic_id         TEXT NOT NULL REFERENCES epics(id),
          title           TEXT NOT NULL,
          state           TEXT DEFAULT 'draft',
          branch          TEXT,
          write_files     TEXT,
          read_files      TEXT DEFAULT '[]',
          test_files      TEXT DEFAULT '[]',
          needs_testing   INTEGER DEFAULT 0,
          needs_review    INTEGER DEFAULT 0,
          agent           TEXT,
          model           TEXT,
          depends_on      TEXT,
          auto_merge      INTEGER DEFAULT 0,
          started_at      TEXT,
          completed_at    TEXT,
          archived        INTEGER DEFAULT 0,
          order_idx       INTEGER,
          plan_file       TEXT,
          worktree_path   TEXT,
          worktree_active INTEGER DEFAULT 0
        );

        CREATE TABLE tasks (
          id         TEXT NOT NULL,
          story_id   TEXT NOT NULL REFERENCES stories(id),
          title      TEXT NOT NULL,
          state      TEXT DEFAULT 'todo' CHECK(state IN ('todo','in-progress','done','blocked','skipped')),
          blocked_by TEXT,
          PRIMARY KEY (story_id, id)
        );

        CREATE TABLE story_dependencies (
          story_id   TEXT NOT NULL REFERENCES stories(id),
          depends_on TEXT NOT NULL REFERENCES stories(id),
          PRIMARY KEY (story_id, depends_on)
        );
        CREATE INDEX idx_story_deps_depends ON story_dependencies(depends_on);
    """)

    # Fixture data: one epic, one story in draft, two pre-existing tasks
    conn.execute(
        "INSERT INTO epics (id, title, branch, pr_number, persistent, state) "
        "VALUES ('epic-001', 'Test Epic', 'epic/001', NULL, 0, 'active')"
    )
    conn.execute("""
        INSERT INTO stories (id, epic_id, title, state, branch, write_files, read_files,
          needs_testing, needs_review, agent, model, depends_on, auto_merge,
          started_at, completed_at, archived, order_idx)
        VALUES ('story-001', 'epic-001', 'Test story', 'draft', NULL,
         '[]', '[]', 0, 0, NULL, NULL, NULL, 0,
         NULL, NULL, 0, NULL)
    """)
    conn.execute("INSERT INTO tasks VALUES ('t1', 'story-001', 'Old task one', 'todo', NULL)")
    conn.execute("INSERT INTO tasks VALUES ('t2', 'story-001', 'Old task two', 'done', NULL)")
    conn.commit()
    return db_path, conn


@pytest.fixture
def test_db(tmp_path):
    """Create a test DB and return (db_path, conn)."""
    db_path, conn = _create_test_db(tmp_path)
    yield db_path, conn
    conn.close()


PLAN_DATA = {
    "agent": "quick-fixer",
    "tasks": ["Setup environment", "Write implementation", "Add tests"],
    "write_files": ["src/feature.py", "tests/test_feature.py"],
    "read_files": ["src/config.py"],
    "depends_on": [],
}


class TestApplyPlanToStory:
    def test_deletes_old_tasks_before_inserting_new(self, test_db):
        _, conn = test_db
        # Confirm pre-existing tasks
        old_tasks = conn.execute("SELECT id, title FROM tasks WHERE story_id = 'story-001'").fetchall()
        assert len(old_tasks) == 2
        assert {r["title"] for r in old_tasks} == {"Old task one", "Old task two"}

        _apply_plan_to_story(conn, "story-001", PLAN_DATA)
        conn.commit()

        tasks = conn.execute("SELECT id, title FROM tasks WHERE story_id = 'story-001'").fetchall()
        assert len(tasks) == 3
        titles = {r["title"] for r in tasks}
        assert titles == {"Setup environment", "Write implementation", "Add tests"}
        assert "Old task one" not in titles
        assert "Old task two" not in titles

    def test_double_apply_no_duplicate_tasks(self, test_db):
        _, conn = test_db
        _apply_plan_to_story(conn, "story-001", PLAN_DATA)
        conn.commit()
        _apply_plan_to_story(conn, "story-001", PLAN_DATA)
        conn.commit()

        tasks = conn.execute("SELECT id, title FROM tasks WHERE story_id = 'story-001'").fetchall()
        assert len(tasks) == len(PLAN_DATA["tasks"])

    def test_sets_state_to_ready(self, test_db):
        _, conn = test_db
        # Confirm story starts as draft
        row = conn.execute("SELECT state FROM stories WHERE id = 'story-001'").fetchone()
        assert row["state"] == "draft"

        _apply_plan_to_story(conn, "story-001", PLAN_DATA)
        conn.commit()

        row = conn.execute("SELECT state FROM stories WHERE id = 'story-001'").fetchone()
        assert row["state"] == "ready"

    def test_idempotent_on_already_ready_story(self, test_db):
        _, conn = test_db
        # Set story to ready first
        conn.execute("UPDATE stories SET state = 'ready' WHERE id = 'story-001'")
        conn.commit()

        updated_plan = {**PLAN_DATA, "agent": "architect", "write_files": ["new_file.py"]}
        _apply_plan_to_story(conn, "story-001", updated_plan)
        conn.commit()

        row = conn.execute("SELECT state, agent, write_files, read_files FROM stories WHERE id = 'story-001'").fetchone()
        assert row["state"] == "ready"
        assert row["agent"] == "architect"
        assert row["write_files"] == '["new_file.py"]'
        assert row["read_files"] == '["src/config.py"]'

        tasks = conn.execute("SELECT title FROM tasks WHERE story_id = 'story-001'").fetchall()
        assert len(tasks) == len(updated_plan["tasks"])
