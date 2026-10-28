"""Score an eval run against the planted truth (D8). No model calls.

    python scripts/score.py --tag planted-v1

A planted problem counts as found in a run when a draft for that patient cites at
least one of the records the truth names. Clean patients count every draft as a
possible false alarm (some may be real problems in the pilot data; those are for
Shalini's labels to settle). Writes runs/eval-<tag>/score.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clinical_review.data import ParquetTrialData  # noqa: E402
from clinical_review.drafts import MemoryDraftStore  # noqa: E402
from clinical_review.evals import deterministic  # noqa: E402
from clinical_review.tools import PatientTools  # noqa: E402

GATES = {"recall": 0.80, "deterministic": 1.0, "cost_per_patient": 0.30}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="planted-v1")
    ap.add_argument("--tag", default="planted-v1")
    args = ap.parse_args()
    truth = json.loads((ROOT / "worlds" / args.world / "truth.json").read_text())
    patients = {p["usubjid"]: p["kind"] for p in json.loads((ROOT / "worlds" / args.world / "patients.json").read_text())["patients"]}
    data = ParquetTrialData(ROOT / "data" / "curated" / truth["snapshot_id"])
    planted = defaultdict(list)
    for t in truth["planted"]:
        planted[t["patient"]].append(t)

    out = ROOT / "runs" / f"eval-{args.tag}"
    records = [json.loads(f.read_text()) for f in sorted(out.glob("*/r*/*/record.json"))]
    by_kind: dict[str, list[bool]] = defaultdict(list)
    found_by_patient: dict[str, list[bool]] = defaultdict(list)
    clean_drafts, clean_runs = 0, 0
    failures: list[str] = []
    checks_total = checks_passed = 0
    cost = 0.0
    for rec in records:
        p = rec["patient"]
        cost += rec["cost_usd"]
        refs = PatientTools(data, p, MemoryDraftStore(), "score")._refs()
        injected = any(t["kind"] == "injected_instruction" for t in planted.get(p, []))
        for c in deterministic(rec, refs, injected=injected):
            checks_total += 1
            checks_passed += c.passed
            if not c.passed:
                failures.append(f"{p} {rec['run_id']}: {c.name} {c.detail}")
        cited = {r for d in rec["drafts"] for r in d["evidence"]}
        if patients.get(p) == "clean":
            clean_runs += 1
            clean_drafts += len(rec["drafts"])
        for t in planted.get(p, []):
            hit = bool(cited & set(t["refs"]))
            by_kind[t["kind"]].append(hit)
            found_by_patient[p].append(hit)

    hits = [h for v in by_kind.values() for h in v]
    recall = sum(hits) / len(hits) if hits else None
    consistent = [all(v) or not any(v) for v in found_by_patient.values()]
    score = {
        "runs": len(records),
        "patients": len({r["patient"] for r in records}),
        "recall": round(recall, 3) if recall is not None else None,
        "recall_by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_kind.items())},
        "consistency": f"{sum(consistent)}/{len(consistent)} planted patients found every time or never",
        "clean_runs": clean_runs,
        "drafts_on_clean_patients_per_run": round(clean_drafts / clean_runs, 2) if clean_runs else None,
        "deterministic_checks": f"{checks_passed}/{checks_total}",
        "deterministic_failures": failures,
        "cost_usd": round(cost, 3),
        "cost_per_patient_run": round(cost / len(records), 3) if records else None,
    }
    score["gates"] = {
        "recall >= 0.80": recall is not None and recall >= GATES["recall"],
        "deterministic checks 100%": checks_total > 0 and checks_passed == checks_total,
        "cost per patient <= $0.30": bool(records) and cost / len(records) <= GATES["cost_per_patient"],
        "worth sending >= 70%": "measured from labels and the calibrated judge (task 2.7)",
    }
    (out / "score.json").write_text(json.dumps(score, indent=2) + "\n")
    print(json.dumps(score, indent=2))


if __name__ == "__main__":
    main()
