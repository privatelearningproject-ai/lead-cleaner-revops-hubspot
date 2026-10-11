"""Comprehensive pytest test suite for cleaner/validate.py and cleaner/report.py.

Covers:
- Validation flags for each issue type
- Quality score computation (100, 0, and exact deductions)
- Classification logic (cleaned.csv vs review.csv)
- Full fixture processing on tests/fixtures/messy_leads.csv
- Summary statistics and score distribution calculations
- Markdown report generation and CSV export
"""

from pathlib import Path
import pandas as pd
import pytest

from cleaner.loader import load_and_map
from cleaner.report import (
    generate_markdown_report,
    generate_summary_stats,
    write_csv_outputs,
)
from cleaner.validate import (
    FATAL_ISSUES,
    calculate_quality_score,
    validate_dataframe,
    validate_row,
)


# ============================================================================
# VALIDATION FLAG TESTS
# ============================================================================

class TestValidationFlags:
    def test_missing_name_flag(self):
        row = {
            "first_name": "",
            "last_name": "",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "missing_name" in validated["issues"]
        assert validated["route"] == "review"

    def test_missing_contact_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "",
            "email": "",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "missing_contact" in validated["issues"]
        assert validated["route"] == "review"

    def test_phone_invalid_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "raw_Phone": "12345",  # Too short
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "phone_invalid" in validated["issues"]
        assert validated["route"] == "review"

    def test_email_invalid_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "raw_Email": "bad-email",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "email_invalid" in validated["issues"]
        assert validated["route"] == "review"

    def test_city_unknown_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "raw_Town": "Atlantis",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "city_unknown" in validated["issues"]
        assert validated["route"] == "review"

    def test_state_unknown_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Mumbai",
            "raw_State": "California",
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "state_unknown" in validated["issues"]
        assert validated["route"] == "review"

    def test_pin_invalid_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "raw_Pincode": "012345",  # Starts with 0
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "pin_invalid" in validated["issues"]

    def test_gst_invalid_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "raw_GSTIN": "27ABCDE1234F1A5",  # Missing Z at 14th pos
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "gst_invalid" in validated["issues"]

    def test_gst_state_mismatch_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Delhi",
            "state": "Delhi",
            "pin_code": "110001",
            "raw_GSTIN": "27ABCDE1234F1Z5",  # 27 is Maharashtra, state is Delhi
            "consent_source": "Web",
        }
        validated = validate_row(row)
        assert "gst_state_mismatch" in validated["issues"]
        assert validated["route"] == "review"

    def test_consent_missing_flag(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "",  # Missing consent
        }
        validated = validate_row(row)
        assert "consent_missing" in validated["issues"]
        # Missing consent alone should NOT block if score >= 70 and no fatal issues
        assert validated["quality_score"] == 90
        assert validated["route"] == "cleaned"


# ============================================================================
# QUALITY SCORING ENGINE TESTS
# ============================================================================

class TestQualityScoringEngine:
    def test_perfect_lead_scores_100(self):
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav.sharma@example.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "gst_number": "27ABCDE1234F1Z5",
            "consent_source": "Website Form",
            "issues": [],
        }
        assert calculate_quality_score(row) == 100

    def test_empty_lead_clamped_to_0(self):
        row = {
            "first_name": "",
            "last_name": "",
            "phone": "",
            "email": "",
            "city": "",
            "state": "",
            "pin_code": "",
            "gst_number": "",
            "consent_source": "",
            "issues": ["missing_name", "missing_contact", "phone_invalid", "email_invalid"],
        }
        score = calculate_quality_score(row)
        assert score == 0

    def test_exact_deduction_missing_first_name(self):
        # Base 100 - 15 = 85
        row = {
            "first_name": "",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
            "issues": [],
        }
        assert calculate_quality_score(row) == 85

    def test_exact_deduction_no_valid_contact(self):
        # Base 100 - 40 = 60
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "",
            "email": "",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
            "issues": ["missing_contact"],
        }
        assert calculate_quality_score(row) == 60

    def test_exact_deduction_invalid_phone_with_valid_email(self):
        # Valid email present, but phone invalid: Base 100 - 20 = 80
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": None,
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "400001",
            "consent_source": "Web",
            "issues": ["phone_invalid"],
        }
        assert calculate_quality_score(row) == 80

    def test_exact_deduction_missing_city_and_state(self):
        # City missing (-10), state missing (-10) -> 80
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "",
            "state": "",
            "pin_code": "400001",
            "consent_source": "Web",
            "issues": [],
        }
        assert calculate_quality_score(row) == 80

    def test_exact_deduction_missing_pin(self):
        # PIN missing (-5) -> 95
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Mumbai",
            "state": "Maharashtra",
            "pin_code": "",
            "consent_source": "Web",
            "issues": [],
        }
        assert calculate_quality_score(row) == 95

    def test_exact_deduction_gst_mismatch(self):
        # GST state mismatch (-10) -> 90
        row = {
            "first_name": "Aarav",
            "last_name": "Sharma",
            "phone": "+919820012345",
            "email": "aarav@test.com",
            "city": "Delhi",
            "state": "Delhi",
            "pin_code": "110001",
            "consent_source": "Web",
            "issues": ["gst_state_mismatch"],
        }
        assert calculate_quality_score(row) == 90


# ============================================================================
# DATAFRAME VALIDATION & FIXTURE VERIFICATION
# ============================================================================

class TestDataFrameValidationAndFixture:
    def test_validate_messy_leads_fixture(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        assert fixture_path.exists()

        raw_df = load_and_map(fixture_path)
        val_df = validate_dataframe(raw_df)

        assert len(val_df) == 50
        assert "quality_score" in val_df.columns
        assert "issues" in val_df.columns
        assert "route" in val_df.columns

        # Verify score bounds
        assert val_df["quality_score"].min() >= 0
        assert val_df["quality_score"].max() <= 100

        # Verified routes
        cleaned_leads = val_df[val_df["route"] == "cleaned"]
        review_leads = val_df[val_df["route"] == "review"]

        # Ensure no lead in cleaned has fatal issues
        for _, row in cleaned_leads.iterrows():
            issues = row["issues"]
            assert not any(f in issues for f in FATAL_ISSUES)
            assert row["quality_score"] >= 70

        # Verify representative leads from fixture:
        # 1. Aarav Sharma (row 0) -> Cleaned
        assert val_df.iloc[0]["first_name"] == "Aarav"
        assert val_df.iloc[0]["route"] == "cleaned"
        assert val_df.iloc[0]["quality_score"] == 100

        # 2. Rajesh Kumar (row 7) -> Review (phone & email invalid)
        rajesh = val_df[val_df["first_name"] == "Rajesh"].iloc[0]
        assert rajesh["route"] == "review"
        assert "phone_invalid" in rajesh["issues"]
        assert "email_invalid" in rajesh["issues"]

        # 3. Nitin Gadgil (Atlantis unmapped town) -> Review
        nitin = val_df[val_df["first_name"] == "Nitin"].iloc[0]
        assert nitin["route"] == "review"
        assert "city_unknown" in nitin["issues"]

        # 4. Nandan Nilekani (GST state mismatch) -> Review
        nandan = val_df[val_df["first_name"] == "Nandan"].iloc[0]
        assert nandan["route"] == "review"
        assert "gst_state_mismatch" in nandan["issues"]


# ============================================================================
# REPORT GENERATION & EXPORT TESTS
# ============================================================================

class TestReportingAndExport:
    def test_generate_summary_stats(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        df = load_and_map(fixture_path)
        val_df = validate_dataframe(df)

        stats = generate_summary_stats(val_df)

        assert stats["total_rows"] == 50
        assert stats["cleaned_count"] + stats["review_count"] == 50
        assert round(stats["cleaned_pct"] + stats["review_pct"], 1) == 100.0
        assert stats["min_quality_score"] <= stats["avg_quality_score"] <= stats["max_quality_score"]

        # Score buckets sum to 50
        buckets = stats["score_buckets"]
        assert sum(buckets.values()) == 50

        # Top issues exist
        assert "phone_invalid" in stats["issue_counts"]
        assert "email_invalid" in stats["issue_counts"]
        assert stats["missing_consent_count"] > 0

    def test_write_csv_outputs(self, tmp_path):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        df = load_and_map(fixture_path)
        val_df = validate_dataframe(df)

        clean_file = tmp_path / "cleaned.csv"
        review_file = tmp_path / "review.csv"

        clean_out, review_out = write_csv_outputs(val_df, clean_file, review_file)

        assert clean_out.exists()
        assert review_out.exists()

        clean_df = pd.read_csv(clean_out)
        rev_df = pd.read_csv(review_out)

        assert len(clean_df) + len(rev_df) == 50
        # Ensure raw_* columns preserved in exported CSVs
        assert "raw_Full Name" in clean_df.columns
        assert "raw_Contact Number" in rev_df.columns

    def test_generate_markdown_report(self, tmp_path):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        df = load_and_map(fixture_path)
        val_df = validate_dataframe(df)
        stats = generate_summary_stats(val_df)

        report_file = tmp_path / "report.md"
        report_md = generate_markdown_report(stats, output_path=report_file)

        assert report_file.exists()
        assert "# Lead Hygiene & Data Quality Report" in report_md
        assert "## 1. Executive Summary" in report_md
        assert "## 2. Lead Quality Score Distribution" in report_md
        assert "## 3. Issue Breakdown Frequency" in report_md
        assert "## 4. Compliance & Consent Status" in report_md
        assert "cleaned.csv" in report_md
        assert "review.csv" in report_md
