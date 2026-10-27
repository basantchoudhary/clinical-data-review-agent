"""Table-driven tests for the tools' four rules, on the local snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinical_review import rules
from clinical_review.data import BlindingBreach, ParquetTrialData
from clinical_review.drafts import MemoryDraftStore
from clinical_review.tools import SPECS, PatientTools

CURATED = Path(__file__).resolve().parents[1] / "data" / "curated"
pytestmark = pytest.mark.skipif(not (CURATED / "LATEST").exists(), reason="run scripts/build_local_snapshot.py first")

LIVER_PATIENT = "01-705-1186"
CLEAN_PATIENT = "01-701-1015"


@pytest.fixture(scope="module")
def data() -> ParquetTrialData:
    return ParquetTrialData.latest(CURATED)


def tools_for(data: ParquetTrialData, patient: str) -> PatientTools:
    return PatientTools(data, patient, MemoryDraftStore(), run_id="test-run")


READ_CALLS = [
    ("patient_summary", {}),
    ("lab_trend", {"test": "ALT"}),
    ("adverse_events", {}),
    ("medications", {}),
    ("medical_history", {}),
    ("vital_signs", {}),
    ("vital_signs", {"test": "SYSBP"}),
    ("disposition", {}),
    ("rule_hits", {}),
    ("prior_queries", {}),
    ("protocol_section", {"topic": "laboratory bilirubin"}),
]


@pytest.mark.parametrize("patient", [LIVER_PATIENT, CLEAN_PATIENT])
@pytest.mark.parametrize(("name", "args"), READ_CALLS)
def test_every_read_tool_is_blinded_and_traceable(data, patient, name, args):
    text, is_error = tools_for(data, patient).call(name, args)
    assert not is_error, text
    for forbidden in ("ARM", "ACTARM", "Xanomeline High", "Xanomeline Low", "Placebo"):
        assert forbidden not in text, f"{name} leaked {forbidden}"
    payload = json.loads(text) if not text.endswith("narrower view]") else None
    has_rows = payload is not None and any(isinstance(v, list) and v for v in payload.values())
    if has_rows and name not in ("rule_hits", "prior_queries", "vital_signs"):
        assert "src_ref" in text


@pytest.mark.parametrize(
    ("name", "args", "error_contains"),
    [
        ("lab_trend", {"test": "NOPE"}, "no results for test"),
        ("lab_trend", {"test": "ALT", "patient": "01-701-1015"}, "unexpected argument"),
        ("patient_summary", {"usubjid": "01-701-1015"}, "unexpected argument"),
        ("no_such_tool", {}, "unknown tool"),
        ("propose_query", {"form": "AE", "category": "other", "issue": "x", "query_text": "x", "evidence": ["LB:01-701-1015:1"]}, "not found in this patient's snapshot"),
        ("propose_query", {"form": "AE", "category": "guess", "issue": "x", "query_text": "x", "evidence": ["DM:01-705-1186"]}, "category must be"),
        ("propose_query", {"form": "AE", "category": "other", "issue": "x", "query_text": "x", "evidence": []}, "at least one evidence"),
    ],
)
def test_errors_come_back_as_errors(data, name, args, error_contains):
    text, is_error = tools_for(data, LIVER_PATIENT).call(name, args)
    assert is_error
    assert error_contains in text


@pytest.mark.parametrize(
    ("value", "uln", "expected"),
    [(104.0, 32.0, 3.25), (32.0, 32.0, 1.0), (None, 32.0, None), (50.0, 0.0, None), (float("nan"), 10.0, None)],
)
def test_x_uln_is_computed_in_code(value, uln, expected):
    assert rules.x_uln(value if value is not None else float("nan"), uln) == expected


@pytest.mark.parametrize(
    ("patient", "rule", "present"),
    [
        (LIVER_PATIENT, "LIVER_3X_ULN", True),
        (LIVER_PATIENT, "BILI_2X_ULN", True),
        (LIVER_PATIENT, "SCREENING_LAB_ABOVE_RANGE", True),
        (CLEAN_PATIENT, "LIVER_3X_ULN", False),
    ],
)
def test_edit_checks(data, patient, rule, present):
    assert (rule in {h.rule for h in rules.check(data, patient)}) is present


def test_a_draft_is_saved_once_and_never_sent(data):
    t = tools_for(data, LIVER_PATIENT)
    args = {"form": "Adverse Events", "category": "missing_event", "issue": "ALT over 3x ULN, no AE",
            "query_text": "Please confirm...", "evidence": ["LB:01-705-1186:" + str(int(data.patient_rows("lb", LIVER_PATIENT).query("LBTESTCD=='ALT'").iloc[1]["LBSEQ"]))]}
    first, err1 = t.call("propose_query", args)
    second, err2 = t.call("propose_query", args)
    assert not err1 and not err2
    assert json.loads(first)["created"] is True
    assert json.loads(second)["created"] is False
    assert len(t.drafts.for_patient(LIVER_PATIENT)) == 1


def test_the_exposure_domain_cannot_be_read(data):
    with pytest.raises(BlindingBreach):
        data.patient_rows("ex", LIVER_PATIENT)


def test_no_tool_takes_a_patient_id():
    for spec in SPECS:
        props = spec.input_schema.get("properties", {})
        assert not ({"usubjid", "patient", "patient_id", "subject"} & set(props)), spec.name
