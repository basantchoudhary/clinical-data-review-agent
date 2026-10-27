"""Edit checks: the deterministic layer (D1).

These run as code, give the same answer every time, and flag what a rule can
see. They also rank patients for review. The agent decides what the flags
*mean*; it never re-does this arithmetic (D4 rule 3). In production these live
in the Databricks pipeline as data-quality rules; here they run over a snapshot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from clinical_review.data import TrialData

LIVER = ("ALT", "AST")
SCREENING_LAB_EXCLUSION = ("CREAT", "BILI", "AST", "ALT")
"""EXCL27: lab values above the reference range at screening for these analytes."""


@dataclass(frozen=True)
class RuleHit:
    rule: str
    message: str
    src_refs: tuple[str, ...]
    weight: int

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["src_refs"] = list(self.src_refs)
        return d


def x_uln(value: float, uln: float) -> float | None:
    if pd.isna(value) or pd.isna(uln) or uln <= 0:
        return None
    return round(float(value) / float(uln), 2)


def check(data: TrialData, usubjid: str) -> list[RuleHit]:
    lb = data.patient_rows("lb", usubjid)
    ae = data.patient_rows("ae", usubjid)
    hits: list[RuleHit] = []

    lb = lb.assign(xuln=[x_uln(v, u) for v, u in zip(lb["LBSTRESN"], pd.to_numeric(lb["LBSTNRHI"], errors="coerce"), strict=True)])

    liver = lb[lb["LBTESTCD"].isin(LIVER) & (lb["xuln"].fillna(0) >= 3)]
    if not liver.empty:
        hits.append(RuleHit("LIVER_3X_ULN", f"ALT or AST at or above 3x ULN on {len(liver)} result(s)",
                            tuple(liver["src_ref"]), 3))

    bili = lb[(lb["LBTESTCD"] == "BILI") & (lb["xuln"].fillna(0) >= 2)]
    if not bili.empty:
        hits.append(RuleHit("BILI_2X_ULN", f"Total bilirubin at or above 2x ULN on {len(bili)} result(s)",
                            tuple(bili["src_ref"]), 3))

    screening = lb[lb["VISIT"].str.upper().str.startswith("SCREENING")
                   & lb["LBTESTCD"].isin(SCREENING_LAB_EXCLUSION) & (lb["LBNRIND"] == "HIGH")]
    if not screening.empty:
        tests = ", ".join(sorted(screening["LBTESTCD"].unique()))
        hits.append(RuleHit("SCREENING_LAB_ABOVE_RANGE", f"Above reference range at screening: {tests} (see EXCL27)",
                            tuple(screening["src_ref"]), 2))

    starts = pd.to_datetime(ae["AESTDTC"], errors="coerce")
    ends = pd.to_datetime(ae["AEENDTC"], errors="coerce")
    backwards = ae[(ends < starts).fillna(False)]
    if not backwards.empty:
        hits.append(RuleHit("AE_END_BEFORE_START", f"{len(backwards)} adverse event(s) end before they start",
                            tuple(backwards["src_ref"]), 2))

    return hits


def priority(data: TrialData, usubjid: str) -> int:
    return sum(h.weight for h in check(data, usubjid))
