"""The agent's tools (D4), bound to one patient by the run.

Four rules hold for every tool here:
1. No tool takes a patient id. `PatientTools` is built for one patient; the
   agent cannot reach anyone else.
2. The agent stays blinded. Outputs are checked for treatment-arm fields
   before they leave (the data port already refuses them; this is the second line).
3. Code does the arithmetic. Multiples of the normal limit, study days and
   flags are computed here and handed over as facts.
4. Every fact carries its `src_ref`, so query evidence points at an exact record.

Site-entered free text comes back wrapped as {"untrusted_text": ...}: evidence
to review, never an instruction (D7).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from clinical_review import rules
from clinical_review.data import BLINDING_COLUMNS, BlindingBreach, TrialData
from clinical_review.drafts import CATEGORIES, Draft, DraftStore

MAX_RESULT_CHARS = 16_000
"""About 4,000 tokens (D10, G6). Larger results are cut with a note, never silently."""

FREE_TEXT = {"AETERM", "CMTRT", "CMINDC", "DSTERM", "MHTERM"}


class ToolError(Exception):
    """Returned to the agent as an error result, never as empty data (D10, G6)."""


def _untrusted(value: object) -> object:
    return {"untrusted_text": value} if isinstance(value, str) and value else value


def _records(df: pd.DataFrame, columns: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for _, row in df.iterrows():
        rec: dict[str, Any] = {}
        for src, name in columns.items():
            if src not in row.index:  # a column this study does not collect
                continue
            v = row[src]
            if isinstance(v, float) and pd.isna(v):
                v = None
            rec[name] = _untrusted(v) if src in FREE_TEXT else v
        rec["src_ref"] = row["src_ref"]
        out.append(rec)
    return out


def _guard(payload: object) -> str:
    text = json.dumps(payload, default=str)
    for column in BLINDING_COLUMNS:
        if f'"{column}"' in text:
            raise BlindingBreach(f"tool output contains {column}")
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + '... [cut: result over the size limit; ask for a narrower view]'
    return text


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True


class PatientTools:
    def __init__(self, data: TrialData, usubjid: str, drafts: DraftStore, run_id: str) -> None:
        self.data = data
        self.usubjid = usubjid
        self.drafts = drafts
        self.run_id = run_id
        self._known_refs: set[str] | None = None

    # ---- read tools ------------------------------------------------------

    def patient_summary(self) -> dict[str, Any]:
        dm = self.data.patient_rows("dm", self.usubjid).iloc[0]
        sv = self.data.patient_rows("sv", self.usubjid).sort_values("VISITNUM")
        ae = self.data.patient_rows("ae", self.usubjid)
        lb = self.data.patient_rows("lb", self.usubjid)
        ds = self.data.patient_rows("ds", self.usubjid)
        abnormal = lb[lb["LBNRIND"].isin(["HIGH", "LOW"])].groupby("LBTESTCD").size().sort_values(ascending=False)
        return {
            "patient": self.usubjid,
            "site": dm["SITEID"], "age": dm["AGE"], "sex": dm["SEX"], "race": dm["RACE"],
            "dates": {"informed_consent": dm["RFICDTC"] or None, "first_dose": dm["RFXSTDTC"] or None,
                      "last_dose": dm["RFXENDTC"] or None, "study_end": dm["RFPENDTC"] or None},
            "visits": [{"visit": r.VISIT, "date": r.SVSTDTC, "src_ref": r.src_ref} for r in sv.itertuples()],
            "adverse_events": [{"term": _untrusted(r.AETERM), "start": r.AESTDTC, "serious": r.AESER, "src_ref": r.src_ref}
                               for r in ae.itertuples()],
            "abnormal_lab_counts": {k: int(v) for k, v in abnormal.head(15).items()},
            "disposition": [{"decision": r.DSDECOD, "term": _untrusted(r.DSTERM), "date": r.DSSTDTC, "src_ref": r.src_ref}
                            for r in ds.itertuples()],
            "rule_hits": [h.as_dict() for h in rules.check(self.data, self.usubjid)],
            "note": "Treatment arm is withheld: the review is blinded.",
            "study_notes": self._study_notes(),
        }

    def _study_notes(self) -> list[str]:
        """Known, study-wide gaps that are not this patient's fault, so they are not queried 306 times."""
        notes = []
        dm_all = self.data.study_wide_dm() if hasattr(self.data, "study_wide_dm") else None
        if dm_all is not None and (dm_all["RFICDTC"] == "").all():
            notes.append("Informed consent dates are not recorded anywhere in this study's data: do not raise a query for a missing consent date.")
        return notes

    def lab_trend(self, test: str) -> dict[str, Any]:
        lb = self.data.patient_rows("lb", self.usubjid)
        rows = lb[lb["LBTESTCD"] == test.upper()].sort_values("LBDTC")
        if rows.empty:
            known = sorted(lb["LBTESTCD"].unique())
            raise ToolError(f"no results for test {test!r}; this patient has: {', '.join(known)}")
        uln = pd.to_numeric(rows["LBSTNRHI"], errors="coerce")
        out = []
        for (_, r), u in zip(rows.iterrows(), uln, strict=True):
            out.append({"visit": r["VISIT"], "date": r["LBDTC"], "value": None if pd.isna(r["LBSTRESN"]) else r["LBSTRESN"],
                        "unit": r["LBSTRESU"], "low": r["LBSTNRLO"], "high": r["LBSTNRHI"],
                        "x_uln": rules.x_uln(r["LBSTRESN"], u), "flag": r["LBNRIND"] or None,
                        "baseline": r["LBBLFL"] == "Y", "src_ref": r["src_ref"]})
        return {"test": test.upper(), "name": rows.iloc[0]["LBTEST"], "results": out}

    def adverse_events(self) -> dict[str, Any]:
        ae = self.data.patient_rows("ae", self.usubjid).sort_values("AESTDTC")
        cols = {"AETERM": "verbatim_term", "AEDECOD": "coded_term", "AESOC": "body_system", "AESTDTC": "start",
                "AEENDTC": "end", "AESEV": "severity", "AESER": "serious", "AEREL": "relationship",
                "AEOUT": "outcome", "AEACN": "action_taken",
                # Seriousness criteria: why an event is serious. 'Y' on any of these
                # with serious = 'N' is itself an inconsistency (tools-v2).
                "AESHOSP": "hospitalisation", "AESLIFE": "life_threatening", "AESDTH": "death",
                "AESDISAB": "disability", "AESCONG": "congenital_anomaly", "AESMIE": "other_medically_important"}
        return {"adverse_events": _records(ae, cols)}

    def medications(self) -> dict[str, Any]:
        cm = self.data.patient_rows("cm", self.usubjid).sort_values("CMSTDTC")
        cols = {"CMTRT": "medication", "CMDECOD": "coded", "CMINDC": "indication", "CMDOSE": "dose",
                "CMDOSU": "unit", "CMSTDTC": "start", "CMENDTC": "end"}
        return {"medications": _records(cm, cols)}

    def medical_history(self) -> dict[str, Any]:
        mh = self.data.patient_rows("mh", self.usubjid)
        cols = {"MHTERM": "verbatim_term", "MHDECOD": "coded_term", "MHCAT": "category", "MHBODSYS": "body_system"}
        return {"medical_history": _records(mh, cols)}

    def vital_signs(self, test: str | None = None) -> dict[str, Any]:
        vs = self.data.patient_rows("vs", self.usubjid)
        if test is None:
            summary = (vs.groupby("VSTESTCD")["VSSTRESN"].agg(["min", "max", "count"]).round(1)
                       .reset_index().to_dict(orient="records"))
            return {"summary": summary, "hint": "call again with a test code for every reading"}
        rows = vs[vs["VSTESTCD"] == test.upper()].sort_values("VSDTC")
        if rows.empty:
            raise ToolError(f"no vital sign {test!r}; available: {', '.join(sorted(vs['VSTESTCD'].unique()))}")
        cols = {"VISIT": "visit", "VSDTC": "date", "VSPOS": "position", "VSSTRESN": "value", "VSSTRESU": "unit"}
        return {"test": test.upper(), "readings": _records(rows, cols)}

    def disposition(self) -> dict[str, Any]:
        ds = self.data.patient_rows("ds", self.usubjid).sort_values("DSSTDTC")
        cols = {"DSCAT": "category", "DSDECOD": "decision", "DSTERM": "reported_term", "VISIT": "visit", "DSSTDTC": "date"}
        return {"disposition": _records(ds, cols)}

    def rule_hits(self) -> dict[str, Any]:
        return {"rule_hits": [h.as_dict() for h in rules.check(self.data, self.usubjid)]}

    def prior_queries(self) -> dict[str, Any]:
        return {"prior_queries": [{k: d[k] for k in ("key", "category", "issue", "status", "evidence")}
                                  for d in self.drafts.for_patient(self.usubjid)]}

    def protocol_section(self, topic: str) -> dict[str, Any]:
        ti = self.data.study_rows("ti")
        words = [w for w in topic.lower().split() if len(w) > 2]
        hit = ti[ti["IETEST"].str.lower().apply(lambda t: any(w in t for w in words))] if words else ti.iloc[0:0]
        rows = hit if not hit.empty else ti
        return {"topic": topic, "matched": not hit.empty,
                "criteria": [{"code": r.IETESTCD, "category": r.IECAT, "text": r.IETEST, "src_ref": r.src_ref}
                             for r in rows.itertuples()]}

    # ---- the one write ---------------------------------------------------

    def _refs(self) -> set[str]:
        if self._known_refs is None:
            refs: set[str] = set()
            for domain in ("dm", "sv", "ae", "lb", "vs", "cm", "mh", "ds"):
                refs |= set(self.data.patient_rows(domain, self.usubjid)["src_ref"])
            refs |= set(self.data.study_rows("ti")["src_ref"])
            self._known_refs = refs
        return self._known_refs

    def propose_query(self, form: str, category: str, issue: str, query_text: str, evidence: list[str]) -> dict[str, Any]:
        if category not in CATEGORIES:
            raise ToolError(f"category must be one of {', '.join(CATEGORIES)}")
        if not evidence:
            raise ToolError("a query needs at least one evidence src_ref")
        unknown = [e for e in evidence if e not in self._refs()]
        if unknown:
            raise ToolError(f"evidence not found in this patient's snapshot: {', '.join(unknown)}")
        draft = Draft(run_id=self.run_id, snapshot_id=self.data.snapshot_id, usubjid=self.usubjid, form=form,
                      category=category, issue=issue, query_text=query_text, evidence=tuple(evidence))
        key, created = self.drafts.add(draft)
        return {"draft": key, "created": created,
                "note": "Saved as a draft for a data manager. Nothing is sent." if created else "Already drafted."}

    # ---- dispatch --------------------------------------------------------

    def handlers(self) -> dict[str, Callable[..., dict[str, Any]]]:
        return {s.name: getattr(self, s.name) for s in SPECS}

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Returns (result text, is_error). Errors go back to the agent as errors."""
        spec = next((s for s in SPECS if s.name == name), None)
        if spec is None:
            return f"unknown tool {name!r}", True
        allowed = set(spec.input_schema.get("properties", {}))
        extra = set(arguments) - allowed
        if extra:
            return f"unexpected argument(s) {', '.join(sorted(extra))}; this tool takes {', '.join(sorted(allowed)) or 'none'}", True
        try:
            return _guard(getattr(self, name)(**arguments)), False
        except (ToolError, TypeError) as e:
            return str(e), True


def _obj(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("patient_summary", "One-page overview of this patient: demographics, key dates, visits, adverse events, abnormal lab counts, disposition and the edit-check rule hits. Start here.", _obj()),
    ToolSpec("lab_trend", "Every result for one lab test over time, with the normal range, the multiple of the upper limit of normal (x_uln, computed), the flag and src_ref.", _obj({"test": {"type": "string", "description": "Lab test code, e.g. ALT, AST, BILI, ALP, CREAT"}}, ["test"])),
    ToolSpec("adverse_events", "All adverse events with verbatim and coded terms, dates, severity, seriousness, relationship, outcome and src_ref.", _obj()),
    ToolSpec("medications", "Concomitant medications with indication, dose and dates.", _obj()),
    ToolSpec("medical_history", "Medical history recorded at entry.", _obj()),
    ToolSpec("vital_signs", "Vital signs: with no test, a summary per test; with a test code (e.g. SYSBP, DIABP, PULSE, WEIGHT) every reading.", _obj({"test": {"type": "string"}})),
    ToolSpec("disposition", "How and why the patient left the study, with dates.", _obj()),
    ToolSpec("rule_hits", "The deterministic edit-check findings for this patient.", _obj()),
    ToolSpec("prior_queries", "Queries already drafted or raised for this patient, to avoid repeating one.", _obj()),
    ToolSpec("protocol_section", "Search the protocol's inclusion and exclusion criteria by topic words, e.g. 'laboratory bilirubin'.", _obj({"topic": {"type": "string"}}, ["topic"])),
    ToolSpec("propose_query", "Save a DRAFT query for a data manager to review. It is never sent by you. Cite every record you rely on by src_ref.",
             _obj({"form": {"type": "string", "description": "The form the query is raised on, e.g. Adverse Events, Laboratory, Disposition, Eligibility"},
                   "category": {"type": "string", "enum": list(CATEGORIES)},
                   "issue": {"type": "string", "description": "One sentence: the inconsistency, for the reviewer"},
                   "query_text": {"type": "string", "description": "The polite question to the site, citing values and dates"},
                   "evidence": {"type": "array", "items": {"type": "string"}, "description": "src_ref values of the records relied on"}},
                  ["form", "category", "issue", "query_text", "evidence"]), read_only=False),
)
