"""Local deterministic investigation sessions for PR11."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kulshan.reckoner.contracts import QuerySpec


@dataclass(frozen=True)
class SessionEntry:
    query: QuerySpec
    timestamp: str
    breadcrumb: tuple[str, ...] = ()
    note: str | None = None


@dataclass
class InvestigationSession:
    session_id: str
    entries: list[SessionEntry] = field(default_factory=list)
    closed: bool = False

    def add(
        self, query: QuerySpec, *, breadcrumb: tuple[str, ...] = (), note: str | None = None
    ) -> None:
        if self.closed:
            raise ValueError("session is closed")
        self.entries.append(
            SessionEntry(query, datetime.now(timezone.utc).isoformat(), breadcrumb, note)
        )

    def close(self) -> None:
        self.closed = True

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "closed": self.closed,
            "entries": [
                {
                    "query": e.query.to_dict(),
                    "timestamp": e.timestamp,
                    "breadcrumb": list(e.breadcrumb),
                    "note": e.note,
                }
                for e in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> InvestigationSession:
        entries = [
            SessionEntry(
                QuerySpec.from_dict(item["query"]),
                str(item["timestamp"]),
                tuple(item.get("breadcrumb", [])),
                item.get("note"),
            )
            for item in data.get("entries", [])
        ]
        return cls(str(data["session_id"]), entries, bool(data.get("closed", False)))


def save_session(session: InvestigationSession, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(session.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_session(path: str | Path) -> InvestigationSession:
    return InvestigationSession.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def start_session(session_id: str) -> InvestigationSession:
    if not session_id or any(ch.isspace() for ch in session_id):
        raise ValueError("session_id must be a non-empty token")
    return InvestigationSession(session_id)


def append_note(session: InvestigationSession, note: str) -> None:
    if session.closed:
        raise ValueError("session is closed")
    if not note.strip():
        raise ValueError("note must not be empty")
    if not session.entries:
        raise ValueError("a note requires a preceding query entry")
    last = session.entries[-1]
    session.entries[-1] = SessionEntry(last.query, last.timestamp, last.breadcrumb, note)
