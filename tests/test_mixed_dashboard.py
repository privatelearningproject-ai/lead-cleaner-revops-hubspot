"""Unit tests for components.mixed_dashboard and baseline verification."""

import json
from pathlib import Path
import pandas as pd
import pytest

from app import run_in_memory_pipeline
from components.mixed_dashboard import (
    count_fixed_phones,
    render_contact_hygiene_card,
    render_duplicate_review_queue,
    render_kpi_row,
    render_mixed_dashboard,
    render_top_header,
)


def test_count_fixed_phones():
    assert count_fixed_phones(pd.DataFrame()) == 0
    assert count_fixed_phones(pd.DataFrame({"phone": [None, "", "invalid"]})) == 0

    df = pd.DataFrame(
        {
            "phone": [
                "+919876543210",
                "+918876543210",
                "9876543210",
                "+14155552671",
                "+91987654321",  # only 9 digits
            ]
        }
    )
    # Exactly the two with +91 and 10 digits
    assert count_fixed_phones(df) == 2


def test_mixed_dashboard_callables():
    assert callable(render_mixed_dashboard)
    assert callable(render_top_header)
    assert callable(render_kpi_row)
    assert callable(render_duplicate_review_queue)
    assert callable(render_contact_hygiene_card)


def test_baseline_metrics_match():
    baseline_path = Path(__file__).resolve().parent.parent / "baseline_output.json"
    assert baseline_path.exists(), "baseline_output.json must exist"

    baseline = json.loads(baseline_path.read_text())

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "test_500_leads.csv"
    assert fixture_path.exists()

    results = run_in_memory_pipeline(
        file_bytes=fixture_path.read_bytes(),
        file_name=fixture_path.name,
        fuzzy_thresh=90,
        quality_cutoff=70,
        dry_run=True,
    )

    assert len(results["raw_df"]) == baseline["total_rows_raw"]
    assert len(results["deduped_df"]) == baseline["total_rows_deduped"]
    assert len(results["cleaned_df"]) == baseline["cleaned_rows"]
    assert len(results["review_df"]) == baseline["flagged_review_rows"]
    assert len(results["proposals_df"]) == baseline["duplicate_clusters"]
    assert results["stats"]["avg_quality_score"] == baseline["avg_quality_score"]
    assert count_fixed_phones(results["deduped_df"]) == 432
