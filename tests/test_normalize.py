"""Thorough pytest test cases for cleaner/normalize.py.

Covers valid, malformed, edge-case, and type variations for:
- Phone normalizer
- Email normalizer
- City and State normalizers
- PIN Code normalizer & State inference
- GST normalizer & State match
- Name normalizer & split_full_name
- Full record normalization & audit preservation
"""

import math
import pytest

from cleaner.normalize import (
    NormalizationResult,
    load_rules,
    normalize_city,
    normalize_email,
    normalize_gst,
    normalize_name,
    normalize_phone,
    normalize_pin_code,
    normalize_record,
    normalize_state,
    split_full_name,
)


# ============================================================================
# PHONE NORMALIZER TESTS
# ============================================================================

class TestPhoneNormalizer:
    @pytest.mark.parametrize(
        "raw_phone, expected",
        [
            # Clean 10 digits starting with 6, 7, 8, 9
            ("9820012345", "+919820012345"),
            ("8123456789", "+918123456789"),
            ("7890123456", "+917890123456"),
            ("6123456789", "+916123456789"),
            # Leading 0 (trunk code)
            ("09820012345", "+919820012345"),
            ("08123456789", "+918123456789"),
            # Leading +91 or 91
            ("+91 98200 12345", "+919820012345"),
            ("+91-98200-12345", "+919820012345"),
            ("+919820012345", "+919820012345"),
            ("919820012345", "+919820012345"),
            # With country code + trunk 0: +91 09820012345
            ("+91 09820012345", "+919820012345"),
            # With 0091 international dialing prefix
            ("00919820012345", "+919820012345"),
            # Messy formatting: hyphens, brackets, dots, extra whitespace
            ("98765-43210", "+919876543210"),
            ("+91 (982) 001-2345", "+919820012345"),
            ("98200.12345", "+919820012345"),
            ("  +91  98200 12345  ", "+919820012345"),
            # 12 digits starting with 91 where mobile itself starts with 9 (e.g. sample fixture)
            ("919123456780", "+919123456780"),
            # Numeric inputs from Excel/pandas (int, float, float string)
            (9820012345, "+919820012345"),
            (9820012345.0, "+919820012345"),
            ("9820012345.0", "+919820012345"),
        ],
    )
    def test_valid_phone_numbers(self, raw_phone, expected):
        result = normalize_phone(raw_phone)
        assert result.is_valid is True
        assert result.value == expected
        assert result.issue is None
        # Unpacking support
        val, is_valid, issue = result
        assert val == expected
        assert is_valid is True
        assert issue is None

    @pytest.mark.parametrize(
        "invalid_phone",
        [
            "12345",              # Too short
            "5551234567",         # 10 digits but starts with 5 (invalid Indian mobile)
            "1234567890",         # 10 digits but starts with 1
            "0123456789",         # Strip 0 -> 9 digits
            "+1 202 555 0123",    # US number
            "+44 7911 123456",    # UK number
            "98765432101234",     # Too long (14 digits)
            "abcdefghij",         # Letters
            "982001234X",         # Mixed alphanumeric
        ],
    )
    def test_invalid_phone_numbers(self, invalid_phone):
        result = normalize_phone(invalid_phone)
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "phone_invalid"

    @pytest.mark.parametrize(
        "empty_val",
        [
            None,
            "",
            "   ",
            float("nan"),
        ],
    )
    def test_missing_phone(self, empty_val):
        result = normalize_phone(empty_val)
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "phone_missing"


# ============================================================================
# EMAIL NORMALIZER TESTS
# ============================================================================

class TestEmailNormalizer:
    @pytest.mark.parametrize(
        "raw_email, expected",
        [
            ("aarav.sharma@example.com", "aarav.sharma@example.com"),
            ("VIKRAM@VENTURES.COM", "vikram@ventures.com"),
            ("  priya.patel@test.co.in  ", "priya.patel@test.co.in"),
            ("user+tag@example.org", "user+tag@example.org"),
            ("firstname.lastname@company.co", "firstname.lastname@company.co"),
            ("deepak_123-test@sub.domain.in", "deepak_123-test@sub.domain.in"),
        ],
    )
    def test_valid_emails(self, raw_email, expected):
        result = normalize_email(raw_email)
        assert result.is_valid is True
        assert result.value == expected
        assert result.issue is None

    @pytest.mark.parametrize(
        "invalid_email",
        [
            "bad-email",
            "user@",
            "@domain.com",
            "user@domain",           # Missing TLD
            "user@domain..com",       # Consecutive dots
            "user space@domain.com",  # Space inside
            "user@.com",              # Missing domain name
            "user@domain.c",          # Single-char TLD
        ],
    )
    def test_invalid_emails(self, invalid_email):
        result = normalize_email(invalid_email)
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "email_invalid"

    @pytest.mark.parametrize(
        "empty_val",
        [
            None,
            "",
            "   ",
            float("nan"),
        ],
    )
    def test_missing_emails(self, empty_val):
        result = normalize_email(empty_val)
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "email_missing"


# ============================================================================
# NAME NORMALIZER TESTS
# ============================================================================

class TestNameNormalizer:
    @pytest.mark.parametrize(
        "raw_name, expected",
        [
            ("aarav sharma", "Aarav Sharma"),
            ("  PRIYA   PATEL  ", "Priya Patel"),
            ("vikram malhotra", "Vikram Malhotra"),
            ("ananya gupta", "Ananya Gupta"),
            # Preserving exact spelling (no autocorrect / no dropping repeated letters)
            ("deeeeeepak verma", "Deeeeeepak Verma"),
            ("suniita rao", "Suniita Rao"),
            # Hyphenated and apostrophe names
            ("mary-jane watson", "Mary-Jane Watson"),
            ("o'connor smith", "O'Connor Smith"),
        ],
    )
    def test_valid_names(self, raw_name, expected):
        result = normalize_name(raw_name)
        assert result.is_valid is True
        assert result.value == expected
        assert result.issue is None

    @pytest.mark.parametrize(
        "empty_val",
        [
            None,
            "",
            "   ",
            float("nan"),
        ],
    )
    def test_missing_names(self, empty_val):
        result = normalize_name(empty_val)
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "name_missing"

    def test_split_full_name(self):
        # Two words
        fn, ln = split_full_name("Aarav Sharma")
        assert fn.value == "Aarav"
        assert ln.value == "Sharma"

        # Three words: first gets tokens up to last; last gets surname
        fn, ln = split_full_name("Vikram Kumar Malhotra")
        assert fn.value == "Vikram Kumar"
        assert ln.value == "Malhotra"

        # Single word: first gets word; last is empty string
        fn, ln = split_full_name("Deepak")
        assert fn.value == "Deepak"
        assert ln.value == ""

        # Empty / missing
        fn, ln = split_full_name("")
        assert fn.is_valid is False
        assert fn.issue == "first_name_missing"
        assert ln.is_valid is False
        assert ln.issue == "last_name_missing"


# ============================================================================
# CITY & STATE NORMALIZER TESTS
# ============================================================================

class TestCityAndStateNormalizer:
    @pytest.mark.parametrize(
        "raw_city, expected",
        [
            ("bombay", "Mumbai"),
            ("BOMBAY", "Mumbai"),
            ("Mumbai", "Mumbai"),
            ("ggn", "Gurugram"),
            ("GGN", "Gurugram"),
            ("gurgaon", "Gurugram"),
            ("Gurugram", "Gurugram"),
            ("bangalore", "Bengaluru"),
            ("bengaluru", "Bengaluru"),
            ("calcutta", "Kolkata"),
            ("Kolkata", "Kolkata"),
            ("madras", "Chennai"),
            ("Chennai", "Chennai"),
            ("secunderabad", "Hyderabad"),
            ("hyderabad", "Hyderabad"),
            ("noida", "Noida"),
            ("patna", "Patna"),
        ],
    )
    def test_city_aliases(self, raw_city, expected):
        result = normalize_city(raw_city)
        assert result.is_valid is True
        assert result.value == expected
        assert result.issue is None

    def test_unknown_city_routes_to_review(self):
        # Unmapped city must NOT be guessed; route to review with city_unknown
        result = normalize_city("Atlantis")
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "city_unknown"

    def test_missing_city(self):
        result = normalize_city("")
        assert result.is_valid is False
        assert result.issue == "city_missing"

    @pytest.mark.parametrize(
        "raw_state, expected",
        [
            ("mh", "Maharashtra"),
            ("MH", "Maharashtra"),
            ("maharashtra", "Maharashtra"),
            ("Maharashtra", "Maharashtra"),
            ("up", "Uttar Pradesh"),
            ("UP", "Uttar Pradesh"),
            ("ka", "Karnataka"),
            ("Karnataka", "Karnataka"),
            ("wb", "West Bengal"),
            ("West Bengal", "West Bengal"),
            ("dl", "Delhi"),
            ("Delhi", "Delhi"),
            ("hr", "Haryana"),
            ("Haryana", "Haryana"),
            ("ts", "Telangana"),
            ("Telangana", "Telangana"),
            ("bihar", "Bihar"),
            ("Bihar", "Bihar"),
        ],
    )
    def test_state_aliases(self, raw_state, expected):
        result = normalize_state(raw_state)
        assert result.is_valid is True
        assert result.value == expected
        assert result.issue is None

    def test_unknown_state_routes_to_review(self):
        result = normalize_state("California")
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "state_unknown"

    def test_missing_state(self):
        result = normalize_state(None)
        assert result.is_valid is False
        assert result.issue == "state_missing"


# ============================================================================
# PIN CODE NORMALIZER TESTS
# ============================================================================

class TestPinCodeNormalizer:
    @pytest.mark.parametrize(
        "pin, expected_val, expected_state",
        [
            ("400001", "400001", "Maharashtra"),
            ("122002", "122002", "Haryana"),
            ("560001", "560001", "Karnataka"),
            ("700001", "700001", "West Bengal"),
            ("201301", "201301", "Uttar Pradesh"),
            ("500003", "500003", "Telangana"),
            ("800001", "800001", "Bihar"),
            ("110001", "110001", "Delhi"),
            # Excel numeric types
            (400001, "400001", "Maharashtra"),
            (400001.0, "400001", "Maharashtra"),
            # Internal spaces/hyphens
            ("122 002", "122002", "Haryana"),
            ("122-002", "122002", "Haryana"),
        ],
    )
    def test_valid_pin_and_state_inference(self, pin, expected_val, expected_state):
        # When state is blank, infer state from pin prefix
        result = normalize_pin_code(pin, state=None)
        assert result.is_valid is True
        assert result.value == expected_val
        assert result.inferred_state == expected_state
        assert result.issue is None

    def test_valid_pin_with_existing_state(self):
        # When state is already provided, inferred_state is still available but caller retains state
        result = normalize_pin_code("400001", state="Maharashtra")
        assert result.is_valid is True
        assert result.value == "400001"
        assert result.inferred_state == "Maharashtra"

    @pytest.mark.parametrize(
        "invalid_pin",
        [
            "012345",   # Starts with 0 (Indian PIN codes must start 1-9)
            "12345",    # 5 digits
            "1234567",  # 7 digits
            "ABCDEF",   # Alphabetic
            "12345A",   # Alphanumeric
        ],
    )
    def test_invalid_pin(self, invalid_pin):
        result = normalize_pin_code(invalid_pin)
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "pin_invalid"

    @pytest.mark.parametrize("empty_val", [None, "", "   ", float("nan")])
    def test_missing_pin(self, empty_val):
        result = normalize_pin_code(empty_val)
        assert result.is_valid is False
        assert result.value is None
        assert result.issue == "pin_missing"


# ============================================================================
# GST NORMALIZER TESTS
# ============================================================================

class TestGSTNormalizer:
    @pytest.mark.parametrize(
        "gst_num, state_input, expected_inferred_state",
        [
            ("27ABCDE1234F1Z5", "MH", "Maharashtra"),
            ("27ABCDE1234F1Z5", "Maharashtra", "Maharashtra"),
            ("06AAAAA0000A1Z5", "Haryana", "Haryana"),
            ("09AAAAA9999A1Z5", "UP", "Uttar Pradesh"),
            ("29ABCDE1234F1Z5", "Karnataka", "Karnataka"),
            ("19AAAAA1111A1Z5", "West Bengal", "West Bengal"),
            ("36AAAAA1234A1Z5", "Telangana", "Telangana"),
            # Lowercase input should be uppercased cleanly
            ("27abcde1234f1z5", "Maharashtra", "Maharashtra"),
            # Whitespace stripped
            ("  27ABCDE1234F1Z5  ", "Maharashtra", "Maharashtra"),
            # State blank: should validate and provide inferred_state
            ("27ABCDE1234F1Z5", None, "Maharashtra"),
        ],
    )
    def test_valid_gst(self, gst_num, state_input, expected_inferred_state):
        result = normalize_gst(gst_num, state=state_input)
        assert result.is_valid is True
        assert result.value == gst_num.strip().upper()
        assert result.issue is None
        assert result.inferred_state == expected_inferred_state

    def test_gst_state_mismatch(self):
        # 27 is Maharashtra, but state is Delhi
        result = normalize_gst("27ABCDE1234F1Z5", state="Delhi")
        assert result.is_valid is False
        assert result.issue == "gst_state_mismatch"
        assert result.inferred_state == "Maharashtra"

        # 06 is Haryana, but state is Karnataka
        result = normalize_gst("06AAAAA0000A1Z5", state="Karnataka")
        assert result.is_valid is False
        assert result.issue == "gst_state_mismatch"

    @pytest.mark.parametrize(
        "malformed_gst",
        [
            "12345",                    # Too short
            "27ABCDE1234F1Z",           # 14 chars (missing 1)
            "27ABCDE1234F1Z50",         # 16 chars (too long)
            "27ABCDE1234F1A5",          # Missing 'Z' at 14th character
            "27123451234F1Z5",          # Invalid PAN structure (digits where letters required)
        ],
    )
    def test_malformed_gst(self, malformed_gst):
        result = normalize_gst(malformed_gst)
        assert result.is_valid is False
        assert result.issue == "gst_invalid"

    def test_unknown_gst_state_code(self):
        # 99 is not a mapped state code in rules.yaml
        result = normalize_gst("99ABCDE1234F1Z5")
        assert result.is_valid is False
        assert result.issue == "gst_state_code_unknown"

    @pytest.mark.parametrize("empty_val", [None, "", "   ", float("nan")])
    def test_missing_gst(self, empty_val):
        result = normalize_gst(empty_val)
        assert result.is_valid is False
        assert result.issue == "gst_missing"


# ============================================================================
# FULL RECORD NORMALIZATION & AUDIT PRESERVATION TESTS
# ============================================================================

class TestRecordNormalization:
    def test_normalize_complete_valid_record(self):
        raw_record = {
            "Full Name": "Aarav Sharma",
            "Contact Number": "09820012345",
            "Email Address": "aarav.sharma@example.com",
            "Town": "Bombay",
            "State Name": "MH",
            "Pincode": "400001",
            "GSTIN": "27ABCDE1234F1Z5",
            "Consent Source": "Website Form",
        }
        normalized = normalize_record(raw_record)

        # Audit preservation: raw_* keys must exist untouched
        assert normalized["raw_Full Name"] == "Aarav Sharma"
        assert normalized["raw_Contact Number"] == "09820012345"
        assert normalized["raw_Email Address"] == "aarav.sharma@example.com"
        assert normalized["raw_Town"] == "Bombay"
        assert normalized["raw_State Name"] == "MH"
        assert normalized["raw_Pincode"] == "400001"
        assert normalized["raw_GSTIN"] == "27ABCDE1234F1Z5"

        # Canonical output columns
        assert normalized["first_name"] == "Aarav"
        assert normalized["last_name"] == "Sharma"
        assert normalized["phone"] == "+919820012345"
        assert normalized["email"] == "aarav.sharma@example.com"
        assert normalized["city"] == "Mumbai"
        assert normalized["state"] == "Maharashtra"
        assert normalized["pin_code"] == "400001"
        assert normalized["gst_number"] == "27ABCDE1234F1Z5"
        assert normalized["issues"] == []
        assert normalized["needs_review"] is False

    def test_normalize_record_with_blank_state_inferred_from_pin(self):
        # Priya Patel case from messy_leads fixture: state is blank, PIN is 122002 -> Haryana
        raw_record = {
            "Full Name": "Priya Patel",
            "Contact Number": "98765-43210",
            "Email Address": "priya.patel@test.co.in",
            "Town": "GGN",
            "State Name": "",
            "Pincode": "122002",
            "GSTIN": "06AAAAA0000A1Z5",
        }
        normalized = normalize_record(raw_record)

        assert normalized["first_name"] == "Priya"
        assert normalized["last_name"] == "Patel"
        assert normalized["phone"] == "+919876543210"
        assert normalized["city"] == "Gurugram"
        assert normalized["state"] == "Haryana"  # Inferred from PIN 122002!
        assert normalized["gst_number"] == "06AAAAA0000A1Z5"
        assert normalized["issues"] == []
        assert normalized["needs_review"] is False

    def test_normalize_record_with_invalid_phone_and_email(self):
        # Rajesh Kumar case from messy_leads fixture: 12345, bad-email
        raw_record = {
            "Full Name": "Rajesh Kumar",
            "Contact Number": "12345",
            "Email Address": "bad-email",
            "Town": "Patna",
            "State Name": "Bihar",
            "Pincode": "800001",
        }
        normalized = normalize_record(raw_record)

        assert normalized["first_name"] == "Rajesh"
        assert normalized["last_name"] == "Kumar"
        assert normalized["phone"] is None
        assert normalized["email"] is None
        assert normalized["city"] == "Patna"
        assert normalized["state"] == "Bihar"
        assert "phone_invalid" in normalized["issues"]
        assert "email_invalid" in normalized["issues"]
        assert normalized["needs_review"] is True

    def test_sample_specification_leads_suite(self):
        """Test all 10 representative Indian leads from Section 5 of specification."""
        leads = [
            {
                "Full Name": "Aarav Sharma",
                "Contact Number": "09820012345",
                "Email Address": "aarav.sharma@example.com",
                "Town": "Bombay",
                "State Name": "MH",
                "Pincode": "400001",
                "GSTIN": "27ABCDE1234F1Z5",
                "expected": {
                    "first_name": "Aarav",
                    "last_name": "Sharma",
                    "phone": "+919820012345",
                    "email": "aarav.sharma@example.com",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pin_code": "400001",
                    "gst_number": "27ABCDE1234F1Z5",
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Aarav Sharma",
                "Contact Number": "+91 98200 12345",
                "Email Address": "aarav.s@work.com",
                "Town": "Mumbai",
                "State Name": "Maharashtra",
                "Pincode": "400001",
                "GSTIN": "27ABCDE1234F1Z5",
                "expected": {
                    "first_name": "Aarav",
                    "last_name": "Sharma",
                    "phone": "+919820012345",
                    "email": "aarav.s@work.com",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pin_code": "400001",
                    "gst_number": "27ABCDE1234F1Z5",
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Priya Patel",
                "Contact Number": "98765-43210",
                "Email Address": "priya.patel@test.co.in",
                "Town": "GGN",
                "State Name": "",
                "Pincode": "122002",
                "GSTIN": "06AAAAA0000A1Z5",
                "expected": {
                    "first_name": "Priya",
                    "last_name": "Patel",
                    "phone": "+919876543210",
                    "email": "priya.patel@test.co.in",
                    "city": "Gurugram",
                    "state": "Haryana",  # Inferred from PIN
                    "pin_code": "122002",
                    "gst_number": "06AAAAA0000A1Z5",
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Priya Patel",
                "Contact Number": "9876543210",
                "Email Address": "priyap@gmail.com",
                "Town": "Gurgaon",
                "State Name": "Haryana",
                "Pincode": "122002",
                "GSTIN": "",
                "expected": {
                    "first_name": "Priya",
                    "last_name": "Patel",
                    "phone": "+919876543210",
                    "email": "priyap@gmail.com",
                    "city": "Gurugram",
                    "state": "Haryana",
                    "pin_code": "122002",
                    "gst_number": None,
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Vikram Malhotra",
                "Contact Number": "8123456789",
                "Email Address": "VIKRAM@VENTURES.COM",
                "Town": "Bangalore",
                "State Name": "Karnataka",
                "Pincode": "560001",
                "GSTIN": "29ABCDE1234F1Z5",
                "expected": {
                    "first_name": "Vikram",
                    "last_name": "Malhotra",
                    "phone": "+918123456789",
                    "email": "vikram@ventures.com",
                    "city": "Bengaluru",
                    "state": "Karnataka",
                    "pin_code": "560001",
                    "gst_number": "29ABCDE1234F1Z5",
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Vikram Malhotra",
                "Contact Number": "8123456789",
                "Email Address": "vikram@ventures.com",
                "Town": "Bengaluru",
                "State Name": "KA",
                "Pincode": "560001",
                "GSTIN": "",
                "expected": {
                    "first_name": "Vikram",
                    "last_name": "Malhotra",
                    "phone": "+918123456789",
                    "email": "vikram@ventures.com",
                    "city": "Bengaluru",
                    "state": "Karnataka",
                    "pin_code": "560001",
                    "gst_number": None,
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Ananya Gupta",
                "Contact Number": "919123456780",
                "Email Address": "ananya.g@guptafoods.com",
                "Town": "Calcutta",
                "State Name": "West Bengal",
                "Pincode": "700001",
                "GSTIN": "19AAAAA1111A1Z5",
                "expected": {
                    "first_name": "Ananya",
                    "last_name": "Gupta",
                    "phone": "+919123456780",
                    "email": "ananya.g@guptafoods.com",
                    "city": "Kolkata",
                    "state": "West Bengal",
                    "pin_code": "700001",
                    "gst_number": "19AAAAA1111A1Z5",
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Rajesh Kumar",
                "Contact Number": "12345",
                "Email Address": "bad-email",
                "Town": "Patna",
                "State Name": "Bihar",
                "Pincode": "800001",
                "GSTIN": "",
                "expected": {
                    "first_name": "Rajesh",
                    "last_name": "Kumar",
                    "phone": None,
                    "email": None,
                    "city": "Patna",
                    "state": "Bihar",
                    "pin_code": "800001",
                    "gst_number": None,
                    "needs_review": True,
                },
            },
            {
                "Full Name": "Sunita Rao",
                "Contact Number": "9988776655",
                "Email Address": "sunita@hyderabadtech.in",
                "Town": "Secunderabad",
                "State Name": "Telangana",
                "Pincode": "500003",
                "GSTIN": "36AAAAA1234A1Z5",
                "expected": {
                    "first_name": "Sunita",
                    "last_name": "Rao",
                    "phone": "+919988776655",
                    "email": "sunita@hyderabadtech.in",
                    "city": "Hyderabad",
                    "state": "Telangana",
                    "pin_code": "500003",
                    "gst_number": "36AAAAA1234A1Z5",
                    "needs_review": False,
                },
            },
            {
                "Full Name": "Deepak Verma",
                "Contact Number": "+91-7890123456",
                "Email Address": "deepak.verma@domain.com",
                "Town": "Noida",
                "State Name": "UP",
                "Pincode": "201301",
                "GSTIN": "09AAAAA9999A1Z5",
                "expected": {
                    "first_name": "Deepak",
                    "last_name": "Verma",
                    "phone": "+917890123456",
                    "email": "deepak.verma@domain.com",
                    "city": "Noida",
                    "state": "Uttar Pradesh",
                    "pin_code": "201301",
                    "gst_number": "09AAAAA9999A1Z5",
                    "needs_review": False,
                },
            },
        ]

        for lead in leads:
            expected = lead.pop("expected")
            result = normalize_record(lead)
            for key, exp_val in expected.items():
                assert result[key] == exp_val, f"Mismatch for lead {lead.get('Full Name')} on key '{key}': expected {exp_val}, got {result[key]}"

    def test_normalize_messy_leads_csv_file(self):
        """Verify normalizer directly against tests/fixtures/messy_leads.csv file."""
        import csv
        from pathlib import Path

        fixture_file = Path(__file__).resolve().parent / "fixtures" / "messy_leads.csv"
        assert fixture_file.exists()

        rows = []
        with open(fixture_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)

        assert len(rows) == 50
        normalized_records = [normalize_record(r) for r in rows]

        # 30 leads should be clean, 20 leads should require review due to edge case invalidations
        review_records = [rec for rec in normalized_records if rec["needs_review"]]
        clean_records = [rec for rec in normalized_records if not rec["needs_review"]]

        assert len(clean_records) == 30
        assert len(review_records) == 20

        # Check specific edge cases in the review queue
        rajesh = next(r for r in review_records if r["first_name"] == "Rajesh")
        assert "phone_invalid" in rajesh["issues"]
        assert "email_invalid" in rajesh["issues"]

        atlantis = next(r for r in review_records if r["raw_Town"] == "Atlantis")
        assert "city_unknown" in atlantis["issues"]

        nandan = next(r for r in review_records if r["first_name"] == "Nandan")
        assert "gst_state_mismatch" in nandan["issues"]

        harsh = next(r for r in review_records if r["first_name"] == "Harsh")
        assert "gst_invalid" in harsh["issues"]



