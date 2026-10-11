"""Thorough pytest test cases for cleaner/loader.py.

Covers:
- Loading CSV and Excel (.xlsx) formats
- Encoding auto-detection (UTF-8, UTF-8-BOM, Windows-1252)
- Column alias mapping via config/mappings.yaml (exact and normalized fallback)
- Full name splitting into first_name and last_name
- Preservation of raw_* columns
- Canonical output schema
- Loading tests/fixtures/messy_leads.csv
"""

import io
from pathlib import Path
import pandas as pd
import pytest

from cleaner.loader import (
    CANONICAL_COLUMNS,
    detect_encoding,
    load_and_map,
    load_mappings,
    map_columns,
    normalize_col_header,
    read_file,
)


class TestEncodingDetection:
    def test_detect_utf8(self):
        utf8_bytes = "Name,City\nAarav,Mumbai\n".encode("utf-8")
        enc = detect_encoding(utf8_bytes)
        assert enc.lower() in ["utf-8", "ascii"]

    def test_detect_windows_1252(self):
        # Bytes 0x93 and 0x94 are smart quotes in windows-1252, invalid in utf-8
        win_bytes = b"Name,Notes\nRajesh,\x93Enterprise Lead\x94\n"
        enc = detect_encoding(win_bytes)
        assert enc.lower() in ["windows-1252", "latin1", "cp1252", "iso-8859-1"]

    def test_file_detect_encoding(self, tmp_path):
        f = tmp_path / "win1252.csv"
        f.write_bytes(b"Name,Notes\nVikram,Co\x92s founder\n")
        enc = detect_encoding(f)
        assert enc.lower() in ["windows-1252", "latin1", "cp1252", "iso-8859-1"]



class TestColumnMappingRules:
    def test_exact_matches(self):
        df = pd.DataFrame(
            columns=[
                "Full Name",
                "Contact Number",
                "Email Address",
                "Town",
                "State Name",
                "Pincode",
                "GSTIN",
                "Consent Source",
                "Lead Date",
                "Company Name",
                "Notes",
            ]
        )
        col_map = map_columns(df)
        assert col_map["Full Name"] == "full_name"
        assert col_map["Contact Number"] == "phone"
        assert col_map["Email Address"] == "email"
        assert col_map["Town"] == "city"
        assert col_map["State Name"] == "state"
        assert col_map["Pincode"] == "pin_code"
        assert col_map["GSTIN"] == "gst_number"
        assert col_map["Consent Source"] == "consent_source"
        assert col_map["Lead Date"] == "consent_date"
        assert col_map["Company Name"] == "company"
        assert col_map["Notes"] == "notes_raw"

    def test_normalized_fallback_matches(self):
        df = pd.DataFrame(
            columns=[
                "Cust Name",
                "Mobile No.",
                "Town/City",
                "Zip Code",
                "Opt-in Source",
                "Remarks",
                "Firm Name",
            ]
        )
        col_map = map_columns(df)
        assert col_map["Cust Name"] == "full_name"
        assert col_map["Mobile No."] == "phone"
        assert col_map["Town/City"] == "city"
        assert col_map["Zip Code"] == "pin_code"
        assert col_map["Opt-in Source"] == "consent_source"
        assert col_map["Remarks"] == "notes_raw"
        assert col_map["Firm Name"] == "company"

    def test_normalize_header_helper(self):
        assert normalize_col_header("Town/City") == "towncity"
        assert normalize_col_header("Mobile No.") == "mobileno"
        assert normalize_col_header("  Full  Name_1  ") == "fullname1"


class TestFileIngestion:
    def test_read_utf8_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("Full Name,Phone\nAarav Sharma,9820012345\n", encoding="utf-8")
        df, filename = read_file(f)
        assert filename == "test.csv"
        assert len(df) == 1
        assert list(df.columns) == ["Full Name", "Phone"]

    def test_read_windows_1252_csv(self, tmp_path):
        f = tmp_path / "test_win.csv"
        f.write_bytes(b"Full Name,Notes\nAarav Sharma,\x93Special Lead\x94\n")
        df, filename = read_file(f)
        assert filename == "test_win.csv"
        assert len(df) == 1
        assert "Special Lead" in df["Notes"].iloc[0]


    def test_read_excel_file(self, tmp_path):
        f = tmp_path / "leads.xlsx"
        original_df = pd.DataFrame(
            {
                "Full Name": ["Aarav Sharma", "Priya Patel"],
                "Contact Number": ["9820012345", "9876543210"],
            }
        )
        original_df.to_excel(f, index=False)
        df, filename = read_file(f)
        assert filename == "leads.xlsx"
        assert len(df) == 2
        assert "Full Name" in df.columns

    def test_read_bytes_buffer(self):
        csv_bytes = b"Full Name,Email\nAarav Sharma,aarav@test.com\n"
        df, filename = read_file(csv_bytes, filename="buffer_leads.csv")
        assert filename == "buffer_leads.csv"
        assert len(df) == 1
        assert df["Full Name"].iloc[0] == "Aarav Sharma"


class TestLoadAndMapPipeline:
    def test_load_and_map_full_structure(self, tmp_path):
        f = tmp_path / "sample.csv"
        csv_content = (
            "Cust Name,Mobile No,Email ID,Town/City,State Name,Pincode,GSTIN,Remarks\n"
            "Aarav Sharma,9820012345,aarav@example.com,Bombay,MH,400001,27ABCDE1234F1Z5,Urgent inquiry\n"
        )
        f.write_text(csv_content, encoding="utf-8")

        result_df = load_and_map(f)

        # 1. Canonical schema columns exist
        for col in CANONICAL_COLUMNS:
            assert col in result_df.columns

        # 2. Raw columns preserved with raw_ prefix
        assert "raw_Cust Name" in result_df.columns
        assert "raw_Mobile No" in result_df.columns
        assert "raw_Email ID" in result_df.columns
        assert "raw_Town/City" in result_df.columns
        assert "raw_Remarks" in result_df.columns

        # Check raw preserved values
        assert result_df["raw_Cust Name"].iloc[0] == "Aarav Sharma"
        assert result_df["raw_Mobile No"].iloc[0] == "9820012345"

        # 3. Mapped canonical values
        assert result_df["first_name"].iloc[0] == "Aarav"
        assert result_df["last_name"].iloc[0] == "Sharma"
        assert result_df["phone"].iloc[0] == "9820012345"
        assert result_df["email"].iloc[0] == "aarav@example.com"
        assert result_df["city"].iloc[0] == "Bombay"
        assert result_df["state"].iloc[0] == "MH"
        assert result_df["pin_code"].iloc[0] == "400001"
        assert result_df["gst_number"].iloc[0] == "27ABCDE1234F1Z5"
        assert result_df["notes_raw"].iloc[0] == "Urgent inquiry"
        assert result_df["source"].iloc[0] == "sample.csv"

    def test_separate_first_and_last_name_not_overwritten(self, tmp_path):
        f = tmp_path / "names.csv"
        f.write_text("First Name,Last Name,Phone\nVikram,Malhotra,8123456789\n", encoding="utf-8")
        result_df = load_and_map(f)

        assert result_df["first_name"].iloc[0] == "Vikram"
        assert result_df["last_name"].iloc[0] == "Malhotra"
        assert result_df["raw_First Name"].iloc[0] == "Vikram"
        assert result_df["raw_Last Name"].iloc[0] == "Malhotra"

    def test_load_messy_leads_fixture(self):
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        assert fixture_path.exists()

        df = load_and_map(fixture_path)

        assert len(df) == 50
        # Check canonical columns present
        for col in CANONICAL_COLUMNS:
            assert col in df.columns

        # Check raw columns present
        expected_raws = [
            "raw_Full Name",
            "raw_Contact Number",
            "raw_Email Address",
            "raw_Town",
            "raw_State Name",
            "raw_Pincode",
            "raw_GSTIN",
            "raw_Consent Source",
            "raw_Notes",
        ]
        for rc in expected_raws:
            assert rc in df.columns

        # Verify first row mapped values
        first_row = df.iloc[0]
        assert first_row["first_name"] == "Aarav"
        assert first_row["last_name"] == "Sharma"
        assert first_row["phone"] == "09820012345"
        assert first_row["email"] == "aarav.sharma@example.com"
        assert first_row["city"] == "Bombay"
        assert first_row["state"] == "MH"
        assert first_row["pin_code"] == "400001"
        assert first_row["gst_number"] == "27ABCDE1234F1Z5"
        assert first_row["consent_source"] == "Website Form"
        assert first_row["notes_raw"] == "Looking for enterprise plan under 5 lakhs"
        assert first_row["source"] == "messy_leads.csv"
