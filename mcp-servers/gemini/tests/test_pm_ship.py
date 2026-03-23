"""Tests for pm_ship: single-epic backward compat, multi-epic creation, proposal round-trip."""

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _create_schema(conn):
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

        CREATE TABLE id_sequences (
          prefix  TEXT PRIMARY KEY,
          last_id INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE pending_proposals (
          id         TEXT PRIMARY KEY,
          data       TEXT NOT NULL,
          created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.execute("INSERT INTO id_sequences (prefix, last_id) VALUES ('epic-', 0)")
    conn.execute("INSERT INTO id_sequences (prefix, last_id) VALUES ('story-', 0)")
    conn.commit()


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test_epics.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    yield conn
    conn.close()


@contextmanager
def _patched_db_op(conn):
    @contextmanager
    def fake_db_op(**kwargs):
        yield conn
    with patch("tools_pm_ship._db_op", fake_db_op):
        yield


def _import_pm_ship():
    from tools_pm_ship import register

    class FakeMCP:
        def __init__(self):
            self.tools = {}
        def tool(self):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorator

    mcp = FakeMCP()
    result = register(mcp)
    return result["pm_ship"]


pm_ship = _import_pm_ship()


class TestSingleEpicUnchanged:
    def test_creates_one_epic_and_stories(self, db_conn):
        with _patched_db_op(db_conn):
            result = pm_ship(items=["login page", "signup page"], title="Auth")

        assert "Created epic-1" in result
        epic = db_conn.execute("SELECT * FROM epics WHERE id = 'epic-1'").fetchone()
        assert epic is not None
        assert epic["title"] == "Auth"

        stories = db_conn.execute("SELECT * FROM stories WHERE epic_id = 'epic-1'").fetchall()
        assert len(stories) >= 1
        titles = {s["title"] for s in stories}
        assert "login page" in titles or "signup page" in titles

    def test_single_epic_response_has_epic_id_not_epic_ids(self, db_conn):
        with _patched_db_op(db_conn):
            result = pm_ship(items=["task a", "task b"], title="Single")

        assert "epic_ids" not in result
        assert "Created epic-1" in result


class TestMultiEpicCreation:
    def test_creates_two_epics_with_correct_stories(self, db_conn):
        with _patched_db_op(db_conn):
            result = pm_ship(
                items=[],
                epics=[
                    {"title": "Auth", "items": ["login page"]},
                    {"title": "Dashboard", "items": ["charts", "filters"]},
                ],
            )

        assert "Created 2 epics" in result

        epics = db_conn.execute("SELECT * FROM epics ORDER BY id").fetchall()
        assert len(epics) == 2
        assert epics[0]["title"] == "Auth"
        assert epics[1]["title"] == "Dashboard"

        auth_stories = db_conn.execute(
            "SELECT title FROM stories WHERE epic_id = ?", (epics[0]["id"],)
        ).fetchall()
        dash_stories = db_conn.execute(
            "SELECT title FROM stories WHERE epic_id = ?", (epics[1]["id"],)
        ).fetchall()

        auth_titles = {s["title"] for s in auth_stories}
        dash_titles = {s["title"] for s in dash_stories}
        assert "login page" in auth_titles
        assert "charts" in dash_titles or "filters" in dash_titles

    def test_multi_epic_response_has_epic_ids(self, db_conn):
        with _patched_db_op(db_conn):
            result = pm_ship(
                items=[],
                epics=[
                    {"title": "E1", "items": ["a"]},
                    {"title": "E2", "items": ["b"]},
                ],
            )

        assert "Created 2 epics" in result


class TestMultiEpicProposalCycle:
    def test_proposal_and_resume(self, db_conn):
        with _patched_db_op(db_conn):
            proposal_result = pm_ship(
                items=[],
                auto_commit=False,
                epics=[
                    {"title": "Auth", "items": ["login"]},
                    {"title": "Dash", "items": ["charts"]},
                ],
            )

        assert "Proposal" in proposal_result
        assert "2 epics" in proposal_result

        row = db_conn.execute("SELECT id, data FROM pending_proposals").fetchone()
        assert row is not None
        pid = row["id"]
        stored = json.loads(row["data"])
        assert stored["multi"] is True
        assert len(stored["proposals"]) == 2

        with _patched_db_op(db_conn):
            commit_result = pm_ship(items=[], proposal_id=pid, auto_commit=True)

        assert "Created 2 epics" in commit_result
        stories = db_conn.execute("SELECT * FROM stories").fetchall()
        assert len(stories) >= 2


class TestEpicsWithEpicIdRejected:
    def test_mutual_exclusion(self, db_conn):
        db_conn.execute(
            "INSERT INTO epics (id, title, persistent, state) VALUES ('epic-99', 'Existing', 0, 'active')"
        )
        db_conn.commit()

        with _patched_db_op(db_conn):
            result = pm_ship(
                items=[],
                epic_id="epic-99",
                epics=[{"title": "New", "items": ["stuff"]}],
            )

        assert "Error" in result
        assert "Cannot use 'epics' with 'epic_id'" in result


class TestMultiEpicItemsGroupedPerEpic:
    def test_group_items_called_per_epic(self, db_conn):
        calls = []
        original_group = None

        import tools_pm_helpers
        original_group = tools_pm_helpers._group_items

        def tracking_group(items, existing):
            calls.append(list(items))
            return original_group(items, existing)

        with _patched_db_op(db_conn), patch("tools_pm_ship._group_items", tracking_group):
            pm_ship(
                items=[],
                epics=[
                    {"title": "E1", "items": ["alpha", "beta"]},
                    {"title": "E2", "items": ["gamma"]},
                ],
            )

        assert len(calls) == 2
        assert calls[0] == ["alpha", "beta"]
        assert calls[1] == ["gamma"]


class TestValidation:
    def test_missing_title_in_entry(self, db_conn):
        with _patched_db_op(db_conn):
            result = pm_ship(items=[], epics=[{"items": ["a"]}])
        assert "Error" in result
        assert "title" in result.lower()

    def test_empty_items_in_entry(self, db_conn):
        with _patched_db_op(db_conn):
            result = pm_ship(items=[], epics=[{"title": "E1", "items": []}])
        assert "Error" in result
        assert "items" in result.lower()
