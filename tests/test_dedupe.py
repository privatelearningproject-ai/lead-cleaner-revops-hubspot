"""Comprehensive pytest test suite for cleaner/dedupe.py.

Covers:
- Priority 1: Exact phone duplicate matching
- Priority 2: Exact email duplicate matching
- Priority 3: Fuzzy name + identical city matching (>90 ratio)
- Negative test: Identical name with different city must NOT match
- Negative test: Empty/null phone or email must NOT match
- Non-destructive field backfilling on primary record
- Review routing for fuzzy matches (never auto-merged)
- Running deduplication on tests/fixtures/messy_leads.csv
"""

from pathlib import Path
import pandas as pd
import pytest

from cleaner.dedupe import deduplicate_leads
from cleaner.loader import load_and_map
from cleaner.validate import validate_dataframe


# ============================================================================
# EXACT MATCHING TESTS
# ============================================================================

class TestExactMatching:
    def test_exact_phone_matching(self):
        df = pd.DataFrame(
            [
                {
                    "first_name": "Priya",
                    "last_name": "Patel",
                    "phone": "+919876543210",
                    "email": "priya.p@test.com",
                    "city": "Gurugram",
                    "state": "Haryana",
                    "quality_score": 90,
                    "route": "cleaned",
                },
                {
                    "first_name": "Priya",
                    "last_name": "Patel",
                    "phone": "+919876543210",  # Same phone
                    "email": "priyap@gmail.com",   # Different email
                    "city": "Gurugram",
                    "state": "Haryana",
                    "quality_score": 80,
                    "route": "cleaned",
                },
            ]
        )

        deduped_df, proposals_df = deduplicate_leads(df, auto_merge_exact=True)

        assert len(proposals_df) == 1
        assert proposals_df["match_type"].iloc[0] == "exact_phone"
        assert proposals_df["requires_review"].iloc[0] == False

        # Since auto_merge_exact=True, only the primary survives in deduped_df
        assert len(deduped_df) == 1
        assert deduped_df["is_duplicate_primary"].iloc[0] == True
        assert deduped_df["duplicate_match_type"].iloc[0] == "exact_phone"
        # Primary is chosen by highest score (90 vs 80)
        assert deduped_df["email"].iloc[0] == "priya.p@test.com"

    def test_exact_email_matching(self):
        df = pd.DataFrame(
            [
                {
                    "first_name": "Vikram",
                    "last_name": "Malhotra",
                    "phone": "+918123456789",
                    "email": "vikram@ventures.com",
                    "city": "Bengaluru",
                    "quality_score": 85,
                    "route": "cleaned",
                },
                {
                    "first_name": "Vikram",
                    "last_name": "Malhotra",
                    "phone": "+919999999999",  # Different phone
                    "email": "vikram@ventures.com",  # Same email
                    "city": "Bengaluru",
                    "quality_score": 75,
                    "route": "cleaned",
                },
            ]
        )

        deduped_df, proposals_df = deduplicate_leads(df, auto_merge_exact=True)

        assert len(proposals_df) == 1
        assert proposals_df["match_type"].iloc[0] == "exact_email"
        assert len(deduped_df) == 1
        assert deduped_df["is_duplicate_primary"].iloc[0] == True


    def test_empty_phone_or_email_never_matches(self):
        # Two completely different people with no email and no phone
        df = pd.DataFrame(
            [
                {
                    "first_name": "PersonA",
                    "last_name": "One",
                    "phone": "",
                    "email": "",
                    "city": "Delhi",
                    "quality_score": 30,
                },
                {
                    "first_name": "PersonB",
                    "last_name": "Two",
                    "phone": "",
                    "email": "",
                    "city": "Mumbai",
                    "quality_score": 30,
                },
            ]
        )

        deduped_df, proposals_df = deduplicate_leads(df)
        assert len(proposals_df) == 0
        assert len(deduped_df) == 2


# ============================================================================
# FUZZY MATCHING & REVIEW ROUTING TESTS
# ============================================================================

class TestFuzzyMatching:
    def test_fuzzy_name_and_matching_city(self):
        # "Vikram Malhotra" and "Vikram K Malhotra" in same city (Bengaluru)
        # Similarity ratio is ~93 (> 90 threshold)
        df = pd.DataFrame(
            [
                {
                    "first_name": "Vikram",
                    "last_name": "Malhotra",
                    "phone": "+918123456789",
                    "email": "vikram@work.com",
                    "city": "Bengaluru",
                    "quality_score": 90,
                    "route": "cleaned",
                    "issues": [],
                },
                {
                    "first_name": "Vikram K",
                    "last_name": "Malhotra",
                    "phone": "+917890123456",  # Different phone
                    "email": "vkm@personal.com", # Different email
                    "city": "Bengaluru",         # Identical city
                    "quality_score": 85,
                    "route": "cleaned",
                    "issues": [],
                },
            ]
        )

        deduped_df, proposals_df = deduplicate_leads(df, fuzzy_threshold=90)

        # 1. Proposal flagged as fuzzy and requires review
        assert len(proposals_df) == 1
        assert proposals_df["match_type"].iloc[0] == "fuzzy_name_city"
        assert bool(proposals_df["requires_review"].iloc[0]) is True

        # 2. Crucial Rule: Fuzzy matches must NEVER be automatically merged.

        # Both records must be retained in deduped_df
        assert len(deduped_df) == 2

        # 3. Both records must be tagged with duplicate_fuzzy_review and routed to review.csv
        for _, row in deduped_df.iterrows():
            assert "duplicate_fuzzy_review" in row["issues"]
            assert row["route"] == "review"
            assert row["needs_review"] is True
            assert row["duplicate_match_type"] == "fuzzy_name_city"

    def test_identical_name_with_different_city_not_matched(self):
        # "Vikram Malhotra" in Bengaluru vs "Vikram Malhotra" in Delhi
        # Must NEVER match on name alone without matching city!
        df = pd.DataFrame(
            [
                {
                    "first_name": "Vikram",
                    "last_name": "Malhotra",
                    "phone": "+918123456789",
                    "email": "vikram.blr@work.com",
                    "city": "Bengaluru",
                    "quality_score": 90,
                },
                {
                    "first_name": "Vikram",
                    "last_name": "Malhotra",
                    "phone": "+919811122233",
                    "email": "vikram.delhi@work.com",
                    "city": "Delhi",
                    "quality_score": 90,
                },
            ]
        )

        deduped_df, proposals_df = deduplicate_leads(df, fuzzy_threshold=90)

        assert len(proposals_df) == 0
        assert len(deduped_df) == 2
        assert (deduped_df["duplicate_match_type"] == "none").all()

    def test_name_similarity_below_threshold_not_matched(self):
        # Completely different names in same city
        df = pd.DataFrame(
            [
                {
                    "first_name": "Aarav",
                    "last_name": "Sharma",
                    "phone": "+919820012345",
                    "email": "aarav@test.com",
                    "city": "Mumbai",
                },
                {
                    "first_name": "Rajesh",
                    "last_name": "Kumar",
                    "phone": "+919820099999",
                    "email": "rajesh@test.com",
                    "city": "Mumbai",
                },
            ]
        )

        deduped_df, proposals_df = deduplicate_leads(df, fuzzy_threshold=90)
        assert len(proposals_df) == 0
        assert len(deduped_df) == 2


# ============================================================================
# FIELD BACKFILLING TESTS
# ============================================================================

class TestFieldBackfilling:
    def test_backfill_missing_fields_from_secondary(self):
        # Record A has phone, email, but missing GST and notes
        # Record B has same phone, valid GST and notes
        df = pd.DataFrame(
            [
                {
                    "first_name": "Aarav",
                    "last_name": "Sharma",
                    "phone": "+919820012345",
                    "email": "aarav@work.com",
                    "company": "Aarav Tech",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pin_code": "400001",
                    "gst_number": "",  # Missing
                    "consent_source": "Web",
                    "notes_raw": "",   # Missing
                    "quality_score": 90,
                },
                {
                    "first_name": "Aarav",
                    "last_name": "Sharma",
                    "phone": "+919820012345",  # Same phone
                    "email": "",
                    "company": "",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pin_code": "400001",
                    "gst_number": "27ABCDE1234F1Z5",  # Has GST
                    "consent_source": "",
                    "notes_raw": "Inquired at conference", # Has notes
                    "quality_score": 70,
                },
            ]
        )

        deduped_df, proposals_df = deduplicate_leads(df, auto_merge_exact=True)

        assert len(deduped_df) == 1
        surviving = deduped_df.iloc[0]

        # Field backfilling check
        assert surviving["gst_number"] == "27ABCDE1234F1Z5"
        assert surviving["notes_raw"] == "Inquired at conference"
        assert surviving["email"] == "aarav@work.com"
        assert surviving["company"] == "Aarav Tech"

        # Audit proposal record check
        proposal = proposals_df.iloc[0]
        assert "gst_number" in proposal["backfilled_fields"]
        assert "notes_raw" in proposal["backfilled_fields"]


# ============================================================================
# FIXTURE VERIFICATION TESTS
# ============================================================================

class TestFixtureDeduplication:
    def test_deduplicate_messy_leads_fixture(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        raw_df = load_and_map(fixture_path)
        val_df = validate_dataframe(raw_df)

        deduped_df, proposals_df = deduplicate_leads(val_df, fuzzy_threshold=90, auto_merge_exact=True)

        # In messy_leads.csv (50 leads):
        # 1. Aarav Sharma duplicates (rows 0 and 1) have same phone +919820012345
        # 2. Priya Patel duplicates (rows 2 and 3) have same phone +919876543210
        # 3. Vikram Malhotra duplicates (rows 4 and 5) have same phone +918123456789
        assert len(proposals_df) >= 3

        phone_proposals = proposals_df[proposals_df["match_type"] == "exact_phone"]
        assert len(phone_proposals) >= 3

        # Count total secondary records merged across exact phone proposals
        total_merged = sum(len(indices) for indices in phone_proposals["secondary_indices"])
        assert total_merged >= 3
        assert len(deduped_df) == len(val_df) - total_merged

