"""The drafts store: the only place the agent writes (D5).

A draft is not a query. It waits here for a data manager to approve, edit or
reject it; a separate writer posts approved ones to OpenClinica. The agent has
no other write path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

CATEGORIES = ("missing_event", "date_inconsistency", "eligibility", "disposition", "coding", "other")


@dataclass(frozen=True)
class Draft:
    run_id: str
    snapshot_id: str
    usubjid: str
    form: str
    category: str
    issue: str
    query_text: str
    evidence: tuple[str, ...]
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    status: str = "pending_review"

    @property
    def key(self) -> str:
        """Idempotency key: the same finding on the same evidence is one draft (D5)."""
        basis = "|".join([self.snapshot_id, self.usubjid, self.category, *sorted(self.evidence)])
        return "drf-" + hashlib.sha256(basis.encode()).hexdigest()[:16]


class DraftStore(Protocol):
    def add(self, draft: Draft) -> tuple[str, bool]:
        """Returns (key, created). A repeat of an existing key is not added again."""
        ...

    def for_patient(self, usubjid: str) -> list[dict[str, object]]: ...


class JsonlDraftStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def add(self, draft: Draft) -> tuple[str, bool]:
        key = draft.key
        if any(d["key"] == key for d in self._all()):
            return key, False
        record = {"key": key, **asdict(draft), "evidence": list(draft.evidence)}
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        return key, True

    def for_patient(self, usubjid: str) -> list[dict[str, object]]:
        return [d for d in self._all() if d["usubjid"] == usubjid]


class MemoryDraftStore:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def add(self, draft: Draft) -> tuple[str, bool]:
        key = draft.key
        if any(d["key"] == key for d in self.records):
            return key, False
        self.records.append({"key": key, **asdict(draft), "evidence": list(draft.evidence)})
        return key, True

    def for_patient(self, usubjid: str) -> list[dict[str, object]]:
        return [d for d in self.records if d["usubjid"] == usubjid]
