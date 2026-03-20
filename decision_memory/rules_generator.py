from __future__ import annotations

import logging
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

_MINIMAL_CONTENT = "# Project Decisions\n\nNo decisions recorded yet.\n"

_TIER_FRESH = 0.3
_TIER_AGING = 0.7


def one_line(text: str, max_len: int = 120) -> str:
    first = text.split(". ")[0].strip()
    if len(first) > max_len - 3:
        first = first[: max_len - 3] + "..."
    elif not first.endswith("."):
        first += "."
    return first


def generate_rules(
    project_root: str,
    decisions_db_path: str | None = None,
    decisions_sql_path: str | None = None,
    output_path: str | None = None,
    run_state_db_path: str | None = None,
) -> str:
    root = Path(project_root)
    db_path = Path(decisions_db_path) if decisions_db_path else root / ".claude" / "decisions.db"
    sql_path = Path(decisions_sql_path) if decisions_sql_path else root / ".claude" / "decisions.sql"
    out_path = Path(output_path) if output_path else root / ".claude" / "rules" / "decisions.md"
    rs_path = Path(run_state_db_path) if run_state_db_path else Path(os.path.expanduser("~/.claude/.claude/run-state.db"))

    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = _open_db(db_path, sql_path)
    except Exception:
        log.warning("Could not open decision store; writing minimal rules file")
        out_path.write_text(_MINIMAL_CONTENT, encoding="utf-8")
        return str(out_path)

    if conn is None:
        out_path.write_text(_MINIMAL_CONTENT, encoding="utf-8")
        return str(out_path)

    try:
        rows = conn.execute(
            "SELECT d.id, d.content, d.reasoning, ds.scope_type, ds.scope_value, "
            "d.domain, d.updated_at "
            "FROM decisions d "
            "LEFT JOIN decision_scopes ds ON d.id = ds.decision_id "
            "WHERE d.status = 'active' "
            "ORDER BY d.id"
        ).fetchall()
    except sqlite3.OperationalError:
        log.warning("Failed to query decisions; writing minimal rules file")
        conn.close()
        out_path.write_text(_MINIMAL_CONTENT, encoding="utf-8")
        return str(out_path)

    conn.close()

    if not rows:
        out_path.write_text(_MINIMAL_CONTENT, encoding="utf-8")
        return str(out_path)

    freshness = _load_freshness_scores(rs_path)
    md = _render_markdown(rows, project_root, freshness)
    out_path.write_text(md, encoding="utf-8")
    return str(out_path)


def _open_db(db_path: Path, sql_path: Path) -> sqlite3.Connection | None:
    if db_path.exists():
        conn = sqlite3.connect(str(db_path), timeout=2)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    if sql_path.exists():
        content = sql_path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        conn = sqlite3.connect(":memory:")
        conn.executescript(content)
        return conn

    return None


def _load_freshness_scores(run_state_db_path: Path) -> dict[int, float]:
    if not run_state_db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{run_state_db_path}?mode=ro", uri=True)
        rows = conn.execute("SELECT decision_id, staleness_score FROM decision_freshness").fetchall()
        conn.close()
        return {int(row[0]): float(row[1]) for row in rows}
    except sqlite3.OperationalError:
        return {}


def _format_decision(did: int, content: str, reasoning: str | None, score: float) -> str:
    if score < _TIER_FRESH:
        line = f"- [decision-{did}] {content}"
        if reasoning:
            line += f"\n  Reasoning: {reasoning}"
        return line
    if score > _TIER_AGING:
        return (
            f"- [STALE] [decision-{did}] {content}\n"
            f"  > Warning: this decision has not been validated against recent code changes"
        )
    return f"- [decision-{did}] {one_line(content)} (Use get_decision({did}) for full details)"


def _tier_label(score: float) -> str:
    if score < _TIER_FRESH:
        return "fresh"
    if score > _TIER_AGING:
        return "stale"
    return "aging"


def _render_domain_summary(domain_ids: dict[str, set[int]], freshness: dict[int, float]) -> list[str]:
    if not domain_ids:
        return []

    lines = ["## Domain summary", ""]
    for domain in sorted(domain_ids):
        ids = domain_ids[domain]
        total = len(ids)
        tier_counts: dict[str, int] = defaultdict(int)
        for did in ids:
            tier_counts[_tier_label(freshness.get(did, 0.5))] += 1

        parts = []
        for label in ("fresh", "aging", "stale"):
            count = tier_counts.get(label, 0)
            if count:
                parts.append(f"{count} {label}")

        breakdown = f" ({', '.join(parts)})" if parts else ""
        lines.append(f"- {domain}: {total} decision{'s' if total != 1 else ''}{breakdown}")

    lines.append("")
    return lines


def _render_markdown(rows: list[tuple], project_root: str, freshness: dict[int, float]) -> str:
    global_decisions: list[tuple[int, str, str | None]] = []
    scoped: dict[str, list[tuple[int, str, str | None]]] = defaultdict(list)
    seen_global: set[int] = set()
    domain_ids: dict[str, set[int]] = defaultdict(set)

    for did, content, reasoning, scope_type, scope_value, domain, _updated_at in rows:
        if domain:
            for d in domain.split(","):
                domain_ids[d.strip()].add(did)

        if scope_type is None and scope_value is None:
            if did not in seen_global:
                global_decisions.append((did, content, reasoning))
                seen_global.add(did)
        else:
            scoped[scope_value].append((did, content, reasoning))

    lines = [
        "# Project Decisions",
        "",
        "> Auto-generated by decision_memory. Do not edit manually.",
        f"> Regenerate: python3 -m decision_memory.rules_generator {project_root}",
        "",
    ]

    lines.extend(_render_domain_summary(domain_ids, freshness))

    if global_decisions:
        lines.append("## Global decisions")
        lines.append("")
        for did, content, reasoning in global_decisions:
            lines.append(_format_decision(did, content, reasoning, freshness.get(did, 0.5)))
        lines.append("")

    if scoped:
        lines.append("## File-scoped decisions")
        lines.append("")
        for scope_value in sorted(scoped):
            lines.append(f"### `{scope_value}`")
            for did, content, reasoning in scoped[scope_value]:
                lines.append(_format_decision(did, content, reasoning, freshness.get(did, 0.5)))
            lines.append("")

    if not global_decisions and not scoped:
        lines.append("No decisions recorded yet.")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python3 -m decision_memory.rules_generator <project_root> [--run-state-db PATH]", file=sys.stderr)
        sys.exit(1)

    rs_db = None
    args = sys.argv[1:]
    project = args[0]
    if "--run-state-db" in args:
        idx = args.index("--run-state-db")
        rs_db = args[idx + 1]

    result = generate_rules(project, run_state_db_path=rs_db)
    print(result)
