"""Tests for app.py Streamlit application components and in-memory workflows."""

from pathlib import Path
import pandas as pd
import pytest

import app
from app import run_in_memory_pipeline, to_csv_bytes


class TestAppComponents:
    def test_import_and_helpers(self):
        # Verify app module loads without import errors
        assert hasattr(app, "main")
        assert hasattr(app, "run_in_memory_pipeline")
        assert hasattr(app, "render_sidebar")

    def test_to_csv_bytes(self):
        df = pd.DataFrame(
            [
                {
                    "first_name": "Aarav",
                    "last_name": "Sharma",
                    "issues": ["phone_invalid", "consent_missing"],
                }
            ]
        )
        csv_bytes = to_csv_bytes(df)
        assert isinstance(csv_bytes, bytes)
        csv_text = csv_bytes.decode("utf-8")
        assert "Aarav" in csv_text
        assert "phone_invalid, consent_missing" in csv_text

    def test_to_csv_bytes_formula_injection_sanitization(self):
        df = pd.DataFrame(
            [
                {
                    "first_name": "=cmd|' /C calc'!A0",
                    "last_name": "@SUM(1+1)",
                    "company": "+cmd",
                    "notes": "-secret",
                }
            ]
        )
        csv_bytes = to_csv_bytes(df)
        csv_text = csv_bytes.decode("utf-8")
        assert "'=cmd" in csv_text
        assert "'@SUM" in csv_text
        assert "'+cmd" in csv_text
        assert "'-secret" in csv_text

    def test_to_csv_bytes_formula_injection_whitespace_and_negative_numbers(self):
        df = pd.DataFrame(
            [
                {
                    "first_name": "  =SUM(A1:A10)",
                    "last_name": "\t+cmd",
                    "safe_negative": "-42",
                    "safe_decimal": "-12.50",
                    "unsafe_dash": "-cmd",
                }
            ]
        )
        csv_bytes = to_csv_bytes(df)
        csv_text = csv_bytes.decode("utf-8")
        assert "'  =SUM" in csv_text
        assert "'\t+cmd" in csv_text
        assert "'-cmd" in csv_text
        assert "-42" in csv_text
        assert "'-42" not in csv_text
        assert "-12.50" in csv_text

    def test_run_in_memory_pipeline(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        assert fixture_path.exists()
        file_bytes = fixture_path.read_bytes()

        results = run_in_memory_pipeline(
            file_bytes=file_bytes,
            file_name="messy_leads.csv",
            fuzzy_thresh=90,
            quality_cutoff=70,
            dry_run=True,
        )

        assert results["file_name"] == "messy_leads.csv"
        assert len(results["raw_df"]) == 50
        assert len(results["cleaned_df"]) > 0
        assert len(results["review_df"]) > 0
        assert len(results["cleaned_df"]) + len(results["review_df"]) == len(results["deduped_df"])
        assert len(results["proposals_df"]) >= 3

        # Verify stats and report
        assert results["stats"]["total_rows"] == len(results["deduped_df"])
        assert "# Lead Hygiene & Data Quality Report" in results["report_md"]

