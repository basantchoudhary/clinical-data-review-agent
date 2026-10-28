"""The trial-data port and its local adapter (D3, D9).

The agent never reads raw tables. It reads one snapshot through `TrialData`,
which has two adapters: local parquet (development and tests) and, later, the
curated tables in Databricks. The same contract tests run against both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pandas as pd

BLINDING_COLUMNS = frozenset({"ARM", "ARMCD", "ACTARM", "ACTARMCD"})
FORBIDDEN_DOMAINS = frozenset({"ex"})
"""Exposure records the dose, which reveals the treatment arm."""

DOMAINS = ("dm", "sv", "ae", "lb", "vs", "cm", "mh", "ds", "ti")


class BlindingBreach(RuntimeError):
    """A treatment-arm column or the exposure domain reached the agent's side."""


class TrialData(Protocol):
    snapshot_id: str

    def patient_rows(self, domain: str, usubjid: str) -> pd.DataFrame: ...

    def study_rows(self, domain: str) -> pd.DataFrame:
        """Study-level tables only (`ti`): no patient data."""
        ...

    def patients(self) -> list[str]: ...


class ParquetTrialData:
    """Reads one local snapshot written by scripts/build_local_snapshot.py."""

    def __init__(self, snapshot_dir: Path) -> None:
        self.dir = snapshot_dir
        self.snapshot_id = snapshot_dir.name
        self._cache: dict[str, pd.DataFrame] = {}

    @classmethod
    def latest(cls, curated: Path) -> ParquetTrialData:
        return cls(curated / (curated / "LATEST").read_text().strip())

    def _table(self, domain: str) -> pd.DataFrame:
        if domain in FORBIDDEN_DOMAINS or domain not in DOMAINS:
            raise BlindingBreach(f"domain {domain!r} may not be read")
        if domain not in self._cache:
            df = pd.read_parquet(self.dir / f"{domain}.parquet")
            leaked = BLINDING_COLUMNS & set(df.columns)
            if leaked:
                raise BlindingBreach(f"{domain}: blinding columns present: {sorted(leaked)}")
            self._cache[domain] = df
        return self._cache[domain]

    def patient_rows(self, domain: str, usubjid: str) -> pd.DataFrame:
        if domain == "ti":
            raise ValueError("ti is study-level; use study_rows")
        df = self._table(domain)
        return df[df["USUBJID"] == usubjid].copy()

    def study_rows(self, domain: str) -> pd.DataFrame:
        if domain != "ti":
            raise ValueError("only ti is study-level")
        return self._table(domain).copy()

    def patients(self) -> list[str]:
        return sorted(self._table("dm")["USUBJID"].unique().tolist())

    def study_wide_dm(self) -> pd.DataFrame:
        """Demographics for every patient, for study-level checks only. Never handed to the agent."""
        return self._table("dm").copy()

    def study_wide(self, domain: str) -> pd.DataFrame:
        """A whole table, for building test worlds and study-level checks. Never handed to the agent."""
        return self._table(domain).copy()
