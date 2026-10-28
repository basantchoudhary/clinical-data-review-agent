"""The planted trial is only a fair test if every planted problem is real, findable and unexplained."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinical_review import rules
from clinical_review.data import ParquetTrialData
from clinical_review.drafts import MemoryDraftStore
from clinical_review.tools import SPECS, PatientTools

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "worlds" / "planted-v1"
pytestmark = pytest.mark.skipif(not (WORLD / "truth.json").exists(), reason="run scripts/build_planted.py first")


@pytest.fixture(scope="module")
def world():
    truth = json.loads((WORLD / "truth.json").read_text())
    patients = json.loads((WORLD / "patients.json").read_text())["patients"]
    data = ParquetTrialData(ROOT / "data" / "curated" / truth["snapshot_id"])
    return truth["planted"], patients, data


def test_every_truth_reference_exists_in_the_planted_snapshot(world):
    planted, _, data = world
    for t in planted:
        tools = PatientTools(data, t["patient"], MemoryDraftStore(), "check")
        known = tools._refs()
        missing = [r for r in t["refs"] if r not in known]
        assert not missing, f"{t['patient']} {t['kind']}: {missing}"


def test_planted_and_clean_patients_do_not_overlap(world):
    _, patients, _ = world
    ids = [p["usubjid"] for p in patients]
    assert len(ids) == len(set(ids)) == 40
    assert sum(p["kind"] == "clean" for p in patients) == 16


def test_clean_patients_stay_quiet_for_the_rules(world):
    _, patients, data = world
    for p in patients:
        if p["kind"] == "clean":
            assert not rules.check(data, p["usubjid"]), p["usubjid"]


@pytest.mark.parametrize("kind", ["medication_without_reason"])
def test_a_planted_problem_is_not_explained_elsewhere(world, kind):
    planted, _, data = world
    for t in (t for t in planted if t["kind"] == kind):
        history = " ".join(data.patient_rows("mh", t["patient"])["MHDECOD"].str.upper())
        events = " ".join(data.patient_rows("ae", t["patient"])["AEDECOD"].str.upper())
        assert "HYPERTENSION" not in history + events, t["patient"]


def test_every_tool_runs_on_every_patient(world):
    _, patients, data = world
    calls = [(s.name, {"test": "ALT"} if s.name == "lab_trend" else {"topic": "age"} if s.name == "protocol_section" else {})
             for s in SPECS if s.read_only]
    for p in patients:
        tools = PatientTools(data, p["usubjid"], MemoryDraftStore(), "check")
        for name, args in calls:
            text, is_error = tools.call(name, args)
            assert not is_error or name == "lab_trend", f"{p['usubjid']} {name}: {text}"
            assert "Placebo" not in text and "Xanomeline" not in text


def test_the_truth_is_out_of_the_agents_reach():
    """The tools read only the curated snapshot; nothing under worlds/ is reachable."""
    source = (ROOT / "src" / "clinical_review" / "tools.py").read_text() + (ROOT / "src" / "clinical_review" / "data.py").read_text()
    assert '"worlds"' not in source and "truth.json" not in source and "planted-v1" not in source
