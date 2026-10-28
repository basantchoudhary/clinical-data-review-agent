"""Table-driven tests for saving a label."""

from __future__ import annotations

import json

import pytest

from clinical_review import labeling

DRAFT = {"key": "drf-1", "usubjid": "01-705-1186", "run_id": "r1", "category": "eligibility",
         "query_text": "Please confirm the screening values.", "evidence": ["TI:EXCL27"], "form": "Eligibility", "issue": "x"}


@pytest.fixture
def stores(tmp_path, monkeypatch):
    drafts, labels = tmp_path / "drafts.jsonl", tmp_path / "labels.jsonl"
    drafts.write_text(json.dumps(DRAFT) + "\n")
    monkeypatch.setattr(labeling, "DRAFTS", drafts)
    monkeypatch.setattr(labeling, "LABELS", labels)
    return labels


@pytest.mark.parametrize(
    ("payload", "worth", "edited"),
    [
        ({"draft": "drf-1", "reason": "worth", "sent_text": DRAFT["query_text"]}, True, False),
        ({"draft": "drf-1", "reason": "worth_edited", "sent_text": "Please confirm EXCL27 was met."}, True, True),
        ({"draft": "drf-1", "reason": "explained", "sent_text": DRAFT["query_text"]}, False, False),
    ],
)
def test_a_label_records_judgement_and_edit(stores, payload, worth, edited):
    labeling.save_label(payload)
    saved = json.loads(stores.read_text().splitlines()[-1])
    assert (saved["worth_sending"], saved["edited"]) == (worth, edited)


@pytest.mark.parametrize(
    ("payload", "error"),
    [({"draft": "nope", "reason": "worth"}, "unknown draft"), ({"draft": "drf-1", "reason": "maybe"}, "unknown reason")],
)
def test_bad_labels_are_refused(stores, payload, error):
    with pytest.raises(ValueError, match=error):
        labeling.save_label(payload)
