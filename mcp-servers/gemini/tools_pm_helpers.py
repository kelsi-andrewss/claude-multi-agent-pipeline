"""PM database helpers: connection, ID generation, state validation, row converters, shared utilities."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from constants import EPICS_DB, PLAN_SYSTEM_INSTRUCTION


def _get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the epics SQLite database with WAL mode and row factory."""
    path = db_path or EPICS_DB
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db_op(db_path: Path | None = None, readonly: bool = False):
    """Context manager that opens DB, yields conn, commits on success (unless readonly), and closes."""
    conn = _get_db(db_path)
    try:
        yield conn
        if not readonly:
            conn.commit()
    except sqlite3.Error as e:
        raise sqlite3.Error(f"[db error]: {e}") from e
    finally:
        conn.close()


def startup_migrate(db_path: Path | None = None) -> None:
    """Run all schema migrations once at server startup."""
    conn = _get_db(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now'))
            )
        """)
        _ensure_knowledge_tables(conn)
        _ensure_epic_columns(conn)
        _ensure_order_idx_column(conn)
        conn.execute("DELETE FROM pending_proposals WHERE created_at < datetime('now', '-24 hours')")
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] or 0
        if current < 1:
            conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")

        if current < 2:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS story_dependencies (
                    story_id TEXT NOT NULL,
                    depends_on TEXT NOT NULL,
                    PRIMARY KEY (story_id, depends_on),
                    FOREIGN KEY (story_id) REFERENCES stories(id),
                    FOREIGN KEY (depends_on) REFERENCES stories(id)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_story_deps_depends ON story_dependencies(depends_on)"
            )
            # Migrate existing JSON depends_on data
            rows = conn.execute(
                "SELECT id, depends_on FROM stories WHERE depends_on IS NOT NULL AND depends_on != '[]'"
            ).fetchall()
            for r in rows:
                try:
                    deps = json.loads(r["depends_on"])
                    for dep_id in deps:
                        conn.execute(
                            "INSERT OR IGNORE INTO story_dependencies (story_id, depends_on) VALUES (?, ?)",
                            (r["id"], dep_id),
                        )
                except (json.JSONDecodeError, TypeError):
                    pass
            conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (2)")

        conn.commit()
    finally:
        conn.close()


def _validate_dependencies(conn: sqlite3.Connection, story_ids: list[str]) -> list[str]:
    """Check a list of story IDs against the stories table. Returns list of invalid IDs."""
    if not story_ids:
        return []
    placeholders = ",".join("?" for _ in story_ids)
    rows = conn.execute(
        f"SELECT id FROM stories WHERE id IN ({placeholders})", story_ids
    ).fetchall()
    found = {r["id"] for r in rows}
    return [sid for sid in story_ids if sid not in found]


def _next_id(conn: sqlite3.Connection, table: str, prefix: str) -> str:
    """Generate the next sequential ID for a table (e.g., 'story-186')."""
    prefix_len = len(prefix)
    row = conn.execute(
        f"SELECT MAX(CAST(SUBSTR(id, {prefix_len + 1}) AS INTEGER)) FROM {table}"
    ).fetchone()
    next_num = (row[0] or 0) + 1
    return f"{prefix}{next_num}"


def _validate_transition(
    current: str, target: str, valid_map: dict[str, set[str]], force: bool = False
) -> str | None:
    """Return error message if transition is invalid, None if ok."""
    if force:
        return None
    # "any -> blocked" and "any -> draft" are always valid for stories
    if target in ("blocked", "draft"):
        return None
    allowed = valid_map.get(current, set())
    if target not in allowed:
        return f"Invalid transition: '{current}' -> '{target}'. Allowed from '{current}': {sorted(allowed)}"
    return None


def _story_to_dict(row: sqlite3.Row) -> dict:
    """Convert a story Row to a dict, parsing JSON fields."""
    d = dict(row)
    for field in ("write_files",):
        val = d.get(field)
        if val and isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except json.JSONDecodeError:
                d[field] = []
    # depends_on now comes from the junction table; default to empty list
    d["depends_on"] = d.get("depends_on", []) if isinstance(d.get("depends_on"), list) else []
    # Convert integer booleans to bool
    for field in ("needs_testing", "needs_review", "auto_merge", "archived"):
        if field in d:
            d[field] = bool(d[field])
    return d


def _epic_to_dict(row: sqlite3.Row) -> dict:
    """Convert an epic Row to a dict, including milestone/roadmap fields."""
    d = dict(row)
    if "persistent" in d:
        d["persistent"] = bool(d["persistent"])
    for field in ("milestone_order", "target_date", "description"):
        if field not in d:
            d[field] = None
    return d


def _fetch_story_deps(conn: sqlite3.Connection, story_id: str) -> list[str]:
    """Fetch forward dependencies for a story from the junction table."""
    rows = conn.execute(
        "SELECT depends_on FROM story_dependencies WHERE story_id = ?", (story_id,)
    ).fetchall()
    return [r["depends_on"] for r in rows]


def _set_story_deps(conn: sqlite3.Connection, story_id: str, depends_on: list[str]) -> None:
    """Replace all dependencies for a story in the junction table."""
    conn.execute("DELETE FROM story_dependencies WHERE story_id = ?", (story_id,))
    for dep_id in depends_on:
        conn.execute(
            "INSERT OR IGNORE INTO story_dependencies (story_id, depends_on) VALUES (?, ?)",
            (story_id, dep_id),
        )


def _ensure_order_idx_column(conn: sqlite3.Connection) -> None:
    """Lazily add order_idx to stories table if it doesn't exist yet."""
    try:
        conn.execute("ALTER TABLE stories ADD COLUMN order_idx INTEGER")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            pass
        else:
            raise


def _ensure_epic_columns(conn: sqlite3.Connection) -> None:
    """Lazily add milestone_order, target_date, description to epics table."""
    for col, col_type in [
        ("milestone_order", "INTEGER"),
        ("target_date", "TEXT"),
        ("description", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE epics ADD COLUMN {col} {col_type}")
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                pass
            else:
                raise


def _ensure_knowledge_tables(conn: sqlite3.Connection) -> None:
    """Create decisions, decision_scopes, and patterns tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            chose TEXT NOT NULL,
            rejected TEXT,
            reasoning TEXT,
            status TEXT DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'reversed')),
            decided_at TEXT DEFAULT (date('now')),
            superseded_by TEXT,
            story_id TEXT,
            FOREIGN KEY (story_id) REFERENCES stories(id)
        );

        CREATE TABLE IF NOT EXISTS decision_scopes (
            decision_id TEXT NOT NULL,
            scope_type TEXT NOT NULL CHECK (scope_type IN ('file', 'pattern', 'tech')),
            scope_value TEXT NOT NULL,
            PRIMARY KEY (decision_id, scope_type, scope_value),
            FOREIGN KEY (decision_id) REFERENCES decisions(id)
        );

        CREATE TABLE IF NOT EXISTS patterns (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN ('react', 'firebase', 'css', 'konva', 'architecture', 'general')),
            severity TEXT DEFAULT 'must' CHECK (severity IN ('must', 'should', 'prefer')),
            source TEXT,
            status TEXT DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
            created_at TEXT DEFAULT (date('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
        CREATE INDEX IF NOT EXISTS idx_decisions_story ON decisions(story_id);
        CREATE INDEX IF NOT EXISTS idx_patterns_category ON patterns(category);
        CREATE INDEX IF NOT EXISTS idx_patterns_status ON patterns(status) WHERE status = 'active';

        CREATE TABLE IF NOT EXISTS pending_proposals (
            id    TEXT PRIMARY KEY,
            data  TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)


def _add_task_to_story(conn: sqlite3.Connection, story_id: str, title: str, blocked_by: str | None = None) -> dict:
    """Insert a task into a story and return the task dict."""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM tasks WHERE story_id = ?",
        (story_id,)
    ).fetchone()
    next_num = (row[0] or 0) + 1
    task_id = f"t{next_num}"
    conn.execute(
        "INSERT INTO tasks (id, story_id, title, state, blocked_by) VALUES (?, ?, ?, 'todo', ?)",
        (task_id, story_id, title, blocked_by)
    )
    return {"id": task_id, "story_id": story_id, "title": title, "state": "todo", "blocked_by": blocked_by}


def _ensure_backlog_epic(conn: sqlite3.Connection) -> None:
    """Ensure the epic-backlog epic exists, creating it if needed."""
    existing = conn.execute("SELECT id FROM epics WHERE id = 'epic-backlog'").fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO epics (id, title, persistent, state) VALUES ('epic-backlog', 'Backlog', 1, 'active')"
        )


# ---------------------------------------------------------------------------
# Shared planning utilities (used by plan, ship tools)
# ---------------------------------------------------------------------------

def _build_plan_prompt(subject: str, context_block: str, code_block: str, user_context: str | None = None) -> str:
    """Build a Gemini prompt for planning epics/stories. Returns valid-JSON-only prompt."""
    parts = [f"[System: {PLAN_SYSTEM_INSTRUCTION}]"]
    if user_context:
        parts.append(f"## User Context\n\n{user_context}")
    if context_block:
        parts.append(f"## Project Context\n\n{context_block}")
    if code_block:
        parts.append(f"## Codebase\n\n{code_block}")
    parts.append(f"## Planning Subject\n\n{subject}")
    return "\n\n".join(parts)


def _apply_plan_to_story(conn, sid: str, plan_data: dict) -> dict:
    """Write tasks, dependencies, and update story agent/write_files from plan data. Returns summary."""
    for task_title in plan_data.get("tasks", []):
        _add_task_to_story(conn, sid, task_title)
    conn.execute(
        "UPDATE stories SET agent = ?, write_files = ? WHERE id = ?",
        (
            plan_data.get("agent"),
            json.dumps(plan_data.get("write_files", [])),
            sid,
        )
    )
    depends_on = plan_data.get("depends_on", [])
    if depends_on:
        _set_story_deps(conn, sid, depends_on)
    return {
        "story_id": sid,
        "agent": plan_data.get("agent"),
        "tasks_created": len(plan_data.get("tasks", [])),
        "parallel_group": plan_data.get("parallel_group", 1),
        "depends_on": depends_on,
    }


# ---------------------------------------------------------------------------
# Shared text-similarity utilities (used by write, organize, plan tools)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase keyword set, stripping punctuation."""
    return set(re.sub(r"[^\w\s]", "", text.lower()).split())


def _jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _score_stories_by_similarity(
    query: str,
    stories: list,
    threshold: float = 0.3,
    title_col: str = "title",
) -> list[tuple[float, str, str]]:
    """Score stories against a query string using Jaccard similarity.

    Returns sorted list of (score, story_id, story_title) tuples where score > threshold,
    sorted descending by score.
    """
    query_kw = _tokenize(query)
    matches: list[tuple[float, str, str]] = []
    for row in stories:
        if isinstance(row, dict):
            title = row.get(title_col, "")
            sid = row.get("id", "")
        else:
            title = row[title_col]
            sid = row["id"]
        score = _jaccard(query_kw, _tokenize(title))
        if score > threshold:
            matches.append((score, sid, title))
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches


def _group_items(items: list[str], existing_stories: list[dict]) -> dict:
    """Group raw todo items into story clusters using Jaccard similarity + union-find."""
    tokens = [_tokenize(item) for item in items]

    parent = list(range(len(items)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _jaccard(tokens[i], tokens[j]) > 0.3:
                union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(items)):
        clusters[find(idx)].append(idx)

    proposed_stories = []
    warnings = []
    existing_titles_kw = [(_tokenize(s["title"]), s["id"]) for s in existing_stories]

    for root, indices in clusters.items():
        cluster_items = [items[i] for i in indices]
        if len(cluster_items) == 1:
            story_title = cluster_items[0]
            tasks: list[str] = []
        else:
            story_title = max(cluster_items, key=len)
            tasks = [item for item in cluster_items if item != story_title]

        story_kw = _tokenize(story_title)
        for ex_kw, ex_id in existing_titles_kw:
            if story_kw & ex_kw and _jaccard(story_kw, ex_kw) > 0.3:
                warnings.append(
                    f"'{story_title}' may duplicate existing story {ex_id} — review before committing."
                )

        proposed_stories.append({
            "title": story_title,
            "tasks": tasks,
            "write_files": [],
            "epic_id": None,
        })

    all_tokens = [_tokenize(s["title"]) for s in proposed_stories]
    questions: list[str] = []
    if len(proposed_stories) > 2:
        has_overlap = any(
            _jaccard(all_tokens[i], all_tokens[j]) > 0.0
            for i in range(len(all_tokens))
            for j in range(i + 1, len(all_tokens))
        )
        if not has_overlap:
            questions.append(
                "The items span multiple unrelated themes. Should they be grouped into separate epics? "
                "If yes, reply with epic names and which stories belong to each."
            )

    return {
        "proposed_epics": [],
        "proposed_stories": proposed_stories,
        "questions": questions,
        "warnings": warnings,
    }
