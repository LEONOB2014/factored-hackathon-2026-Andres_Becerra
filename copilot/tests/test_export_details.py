"""The per-item intent export (eval/export_details.py) used by the evaluation report."""

import importlib.util
from pathlib import Path

from copilot.intent import IntentModel, test_set

SPEC = importlib.util.spec_from_file_location(
    "export_details", Path(__file__).resolve().parents[1] / "eval" / "export_details.py"
)
export_details = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_details)


def test_held_out_rows_cover_every_phrasing_with_a_confidence_and_a_runner_up():
    rows = export_details.held_out(IntentModel())
    assert len(rows) == len(test_set())
    for r in rows:
        assert 0 < r["runner_up_confidence"] <= r["confidence"] <= 1
        assert r["learned"] != r["runner_up"]


def test_summary_counts_base_phrasings_before_augmentation():
    s = export_details.summary()
    assert s["augmented_phrasings"] > s["base_phrasings"]
    assert sum(s["base_by_language"].values()) == s["base_phrasings"]
