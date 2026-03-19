from __future__ import annotations

from dataclasses import dataclass, field

_VALID_STATUSES = frozenset({"active", "deprecated", "superseded", "violated"})
_VALID_SOURCES = frozenset({"human", "ai-discovered", "ai-proposed"})


@dataclass
class DecisionScope:
    id: int | None
    decision_id: int
    scope_type: str  # 'file' | 'pattern' | 'tech'
    scope_value: str


@dataclass
class Decision:
    id: int | None
    content: str
    reasoning: str | None
    status: str  # 'active' | 'deprecated' | 'superseded' | 'violated'
    source: str  # 'human' | 'ai-discovered' | 'ai-proposed'
    superseded_by: int | None
    created_at: str | None
    updated_at: str | None
    domain: str | None = None
    scopes: list[DecisionScope] = field(default_factory=list)

    def __post_init__(self):
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status {self.status!r}, must be one of {sorted(_VALID_STATUSES)}"
            )
        if self.source not in _VALID_SOURCES:
            raise ValueError(
                f"Invalid source {self.source!r}, must be one of {sorted(_VALID_SOURCES)}"
            )


@dataclass
class SearchResult:
    decision: Decision
    score: float
    match_type: str  # 'vector' | 'keyword' | 'hybrid'
