"""End-to-End Pipeline and CLI Integration Tests.

Covers:
- run_pipeline() execution on tests/fixtures/messy_leads.csv
- Verification of output artifacts (cleaned.csv, review.csv, report.md)
- Verification of SQLite audit logging (runs, record_audit, merge_audit tables)
- Verification of CLI execution via python -m cleaner.pipeline
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest

from cleaner.db import get_connection, get_merge_audits, get_record_audits, get_run
from cleaner.pipeline import run_pipeline


class TestPipelineOrchestrator:
    def test_run_pipeline_end_to_end(self, tmp_path):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        assert fixture_path.exists()

        output_dir = tmp_path / "output"
        db_path = tmp_path / "test_audit.db"

        summary = run_pipeline(
            input_file_path=fixture_path,
            output_dir=output_dir,
            dry_run=True,
            db_path=db_path,
        )

        # 1. Verify summary dictionary
        assert summary["status"] == "completed"
        assert summary["total_rows"] == 50
        assert summary["dry_run"] is True
        assert summary["cleaned_count"] > 0
        assert summary["review_count"] > 0
        assert summary["cleaned_count"] + summary["review_count"] == summary["deduped_total"]

        # 2. Verify file artifacts created
        cleaned_file = Path(summary["cleaned_file"])
        review_file = Path(summary["review_file"])
        report_file = Path(summary["report_file"])

        assert cleaned_file.exists()
        assert review_file.exists()
        assert report_file.exists()

        cleaned_df = pd.read_csv(cleaned_file)
        review_df = pd.read_csv(review_file)

        assert len(cleaned_df) == summary["cleaned_count"]
        assert len(review_df) == summary["review_count"]

        # Ensure raw_* columns preserved in exported CSVs
        assert "raw_Full Name" in cleaned_df.columns
        assert "raw_Contact Number" in review_df.columns

        # Verify report.md content
        report_content = report_file.read_text(encoding="utf-8")
        assert "# Lead Hygiene & Data Quality Report" in report_content
        assert "cleaned.csv" in report_content
        assert "review.csv" in report_content

        # 3. Verify SQLite audit tables populated
        run_id = summary["run_id"]
        run_record = get_run(run_id, db_path=db_path)
        assert run_record is not None
        assert run_record["file_name"] == "messy_leads.csv"
        assert run_record["total_rows"] == 50
        assert run_record["cleaned_rows"] == summary["cleaned_count"]
        assert run_record["review_rows"] == summary["review_count"]
        assert run_record["dry_run"] == 1
        assert run_record["status"] == "completed"

        # Record audit table
        records = get_record_audits(run_id, db_path=db_path)
        assert len(records) == summary["deduped_total"]
        assert any(r["first_name"] == "Aarav" for r in records)
        assert any(r["first_name"] == "Rajesh" and r["status"] == "review" for r in records)

        # Merge audit table
        merge_records = get_merge_audits(run_id, db_path=db_path)
        assert len(merge_records) == summary["merged_clusters_count"]
        assert any(m["match_type"] == "exact_phone" for m in merge_records)

    def test_pipeline_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            run_pipeline("non_existent_file.csv", output_dir=tmp_path)


class TestPipelineCLI:
    def test_cli_execution_subprocess(self, tmp_path):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        output_dir = tmp_path / "cli_output"
        db_path = tmp_path / "cli_audit.db"

        cmd = [
            sys.executable,
            "-m",
            "cleaner.pipeline",
            str(fixture_path),
            "--output-dir",
            str(output_dir),
            "--db-path",
            str(db_path),
            "--dry-run",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "LEAD CLEANER PIPELINE COMPLETED SUCCESSFULLY" in result.stdout
        assert "Total Rows Ingest: 50" in result.stdout
        assert (output_dir / "cleaned.csv").exists()
        assert (output_dir / "review.csv").exists()
        assert (output_dir / "report.md").exists()
        assert db_path.exists()

    def test_pipeline_with_enrich_flag(self, tmp_path):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        output_dir = tmp_path / "enrich_output"
        db_path = tmp_path / "enrich_audit.db"

        # Mock Ollama call to verify enrich integration
        with patch("cleaner.enrich.extract_lead_notes") as mock_extract:
            mock_extract.return_value = {
                "budget": "5 Lakhs",
                "product_interest": "CRM",
                "city": "Mumbai",
                "status": "success",
                "error": None,
            }

            summary = run_pipeline(
                input_file_path=fixture_path,
                output_dir=output_dir,
                dry_run=True,
                db_path=db_path,
                enrich=True,
            )

            assert summary["status"] == "completed"
            cleaned_df = pd.read_csv(summary["cleaned_file"])
            assert "notes_structured" in cleaned_df.columns
            assert mock_extract.called

