"""Field-level normalization module for Indian lead data hygiene.

Includes normalizers for:
- Phone numbers (Indian standard: +91XXXXXXXXXX)
- Email addresses (RFC 5322 regex validation)
- Cities and States (case-insensitive mapping from rules.yaml)
- PIN codes (6-digit validation and state inference via pin_prefixes)
- GST numbers (15-character format, state code validation and state matching)
- Names (trimming, title-casing, preserving spelling)
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

# RFC 5322 compliant regex for practical email validation
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}$"
)

# PIN Code regex: 6 digits, first digit 1-9
PIN_CODE_REGEX = re.compile(r"^[1-9][0-9]{5}$")

# Indian GSTIN regex: 15 characters
# 2 digits state code + 5 chars PAN alphabets + 4 chars PAN digits + 1 char PAN alphabet
# + 1 char entity code (1-9A-Z) + 'Z' + 1 checksum char (alphanumeric)
GST_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


@dataclass
class NormalizationResult:
    """Standard container for normalization results.

    Attributes:
        value: Normalized canonical string or None if invalid/missing.
        is_valid: True if value is valid according to schema rules.
        issue: Issue identifier (e.g. 'phone_invalid', 'city_unknown') or None.
        inferred_state: Inferred state name (from PIN or GST), if applicable.
        raw: Original raw value received by normalizer.
    """

    value: Optional[str]
    is_valid: bool
    issue: Optional[str] = None
    inferred_state: Optional[str] = None
    raw: Any = None

    def __iter__(self):
        """Allow unpacking as (value, is_valid, issue)."""
        yield self.value
        yield self.is_valid
        yield self.issue

    def __getitem__(self, index: int):
        return (self.value, self.is_valid, self.issue)[index]

    def __bool__(self) -> bool:
        return self.is_valid


_RULES_CACHE: Optional[Dict[str, Any]] = None


def get_default_rules_path() -> Path:
    """Return default path to config/rules.yaml."""
    return Path(__file__).resolve().parent.parent / "config" / "rules.yaml"


def load_rules(rules_path: Optional[Union[str, Path]] = None, reload: bool = False) -> Dict[str, Any]:
    """Load normalization rules from YAML configuration.

    Caches rules in memory unless reload=True.
    """
    global _RULES_CACHE
    if _RULES_CACHE is not None and not reload and rules_path is None:
        return _RULES_CACHE

    target_path = Path(rules_path) if rules_path else get_default_rules_path()

    if target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        # Fallback embedded defaults if rules.yaml is missing
        data = {
            "city_aliases": {
                "bombay": "Mumbai",
                "mumbai": "Mumbai",
                "ggn": "Gurugram",
                "gurgaon": "Gurugram",
                "gurugram": "Gurugram",
                "bangalore": "Bengaluru",
                "bengaluru": "Bengaluru",
                "calcutta": "Kolkata",
                "kolkata": "Kolkata",
                "madras": "Chennai",
                "chennai": "Chennai",
                "secunderabad": "Hyderabad",
                "hyderabad": "Hyderabad",
                "noida": "Noida",
                "patna": "Patna",
            },
            "state_aliases": {
                "mh": "Maharashtra",
                "maharashtra": "Maharashtra",
                "up": "Uttar Pradesh",
                "uttar pradesh": "Uttar Pradesh",
                "ka": "Karnataka",
                "karnataka": "Karnataka",
                "wb": "West Bengal",
                "west bengal": "West Bengal",
                "dl": "Delhi",
                "delhi": "Delhi",
                "hr": "Haryana",
                "haryana": "Haryana",
                "ts": "Telangana",
                "telangana": "Telangana",
                "br": "Bihar",
                "bihar": "Bihar",
            },
            "pin_prefixes": {
                "11": "Delhi",
                "12": "Haryana",
                "13": "Haryana",
                "20": "Uttar Pradesh",
                "21": "Uttar Pradesh",
                "22": "Uttar Pradesh",
                "27": "Maharashtra",
                "40": "Maharashtra",
                "56": "Karnataka",
                "70": "West Bengal",
                "50": "Telangana",
                "80": "Bihar",
            },
            "gst_state_codes": {
                "06": "Haryana",
                "07": "Delhi",
                "09": "Uttar Pradesh",
                "19": "West Bengal",
                "27": "Maharashtra",
                "29": "Karnataka",
                "36": "Telangana",
                "10": "Bihar",
            },
        }

    if rules_path is None:
        _RULES_CACHE = data
    return data


def _clean_str(val: Any) -> str:
    """Convert input to stripped string, handling floats and None."""
    if val is None:
        return ""
    if isinstance(val, float):
        if math.isnan(val):
            return ""
        if val.is_integer():
            return str(int(val))
        return str(val)
    if isinstance(val, int):
        return str(val)
    s = str(val).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def normalize_phone(phone: Any) -> NormalizationResult:
    """Normalize Indian phone numbers to E.164 format (+91XXXXXXXXXX).

    Rules:
    - Strip junk characters (spaces, hyphens, brackets, dots, commas).
    - Handle country code +91, 91, or 0091.
    - Handle leading 0.
    - Must be exactly 10 digits starting with 6, 7, 8, or 9.
    - If valid, format as +91XXXXXXXXXX.
    - Else route to review with 'phone_invalid' or 'phone_missing'.
    """
    raw_str = _clean_str(phone)
    if not raw_str:
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="phone_missing",
            raw=phone,
        )

    # Extract all digits
    digits = re.sub(r"\D", "", raw_str)

    # Handle various prefixes:
    # 1. 0091 prefix (international dialing format from landline/some exports)
    if digits.startswith("0091") and len(digits) == 14:
        digits = digits[4:]
    # 2. 910 prefix (country code + leading trunk zero, e.g. +91 09820012345)
    elif digits.startswith("910") and len(digits) == 13:
        digits = digits[3:]
    # 3. 91 prefix with 12 digits total (+91 9820012345)
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    # 4. Leading trunk 0 with 11 digits total (09820012345)
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]

    # Validate 10 digits starting with 6, 7, 8, 9
    if len(digits) == 10 and digits[0] in "6789":
        return NormalizationResult(
            value=f"+91{digits}",
            is_valid=True,
            issue=None,
            raw=phone,
        )

    return NormalizationResult(
        value=None,
        is_valid=False,
        issue="phone_invalid",
        raw=phone,
    )


def normalize_email(email: Any) -> NormalizationResult:
    """Normalize email address.

    Rules:
    - Strip whitespace, lowercase.
    - Validate against RFC 5322 compatible regex.
    - If valid, output cleaned email.
    - Else route to review with 'email_invalid' or 'email_missing'.
    """
    raw_str = _clean_str(email)
    if not raw_str:
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="email_missing",
            raw=email,
        )

    cleaned = raw_str.strip().lower()

    if EMAIL_REGEX.match(cleaned):
        return NormalizationResult(
            value=cleaned,
            is_valid=True,
            issue=None,
            raw=email,
        )

    return NormalizationResult(
        value=None,
        is_valid=False,
        issue="email_invalid",
        raw=email,
    )


def normalize_name(name: Any) -> NormalizationResult:
    """Normalize a person's name.

    Rules:
    - Trim leading/trailing whitespace.
    - Collapse multiple consecutive whitespace characters.
    - Title case each word.
    - Strictly preserve spelling, hyphens, and apostrophes (no autocorrect / transliteration).
    """
    raw_str = _clean_str(name)
    if not raw_str:
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="name_missing",
            raw=name,
        )

    # Collapse consecutive whitespace
    words = raw_str.split()
    # Title-case each word while preserving internal apostrophes and hyphens
    title_words = []
    for word in words:
        # Handle hyphenated parts (e.g. Mary-Jane)
        if "-" in word:
            parts = [p.capitalize() for p in word.split("-")]
            title_words.append("-".join(parts))
        elif "'" in word:
            parts = [p.capitalize() for p in word.split("'")]
            title_words.append("'".join(parts))
        else:
            title_words.append(word.capitalize())

    cleaned = " ".join(title_words)
    return NormalizationResult(
        value=cleaned,
        is_valid=True,
        issue=None,
        raw=name,
    )


def split_full_name(full_name: Any) -> Tuple[NormalizationResult, NormalizationResult]:
    """Split full name into normalized (first_name, last_name).

    Rules:
    - If full_name is empty, both first and last are missing.
    - If single word, first_name gets the word, last_name is empty string.
    - If multiple words, first_name contains all tokens except last; last_name contains the last token.
    """
    norm = normalize_name(full_name)
    if not norm.is_valid or not norm.value:
        return (
            NormalizationResult(value=None, is_valid=False, issue="first_name_missing", raw=full_name),
            NormalizationResult(value=None, is_valid=False, issue="last_name_missing", raw=full_name),
        )

    parts = norm.value.split()
    if len(parts) == 1:
        return (
            NormalizationResult(value=parts[0], is_valid=True, issue=None, raw=full_name),
            NormalizationResult(value="", is_valid=True, issue=None, raw=full_name),
        )

    first = " ".join(parts[:-1])
    last = parts[-1]
    return (
        NormalizationResult(value=first, is_valid=True, issue=None, raw=full_name),
        NormalizationResult(value=last, is_valid=True, issue=None, raw=full_name),
    )


def normalize_city(city: Any, rules: Optional[Dict[str, Any]] = None) -> NormalizationResult:
    """Normalize city name via case-insensitive lookup in rules.yaml.

    Rules:
    - Look up lowercased city in rules['city_aliases'].
    - If mapped, return standard city name.
    - If not mapped, check if city directly matches any canonical city name.
    - If unmapped, route to review with 'city_unknown' (do not guess).
    """
    raw_str = _clean_str(city)
    if not raw_str:
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="city_missing",
            raw=city,
        )

    rules_dict = rules if rules is not None else load_rules()
    city_aliases = rules_dict.get("city_aliases", {})

    key = raw_str.strip().lower()

    # 1. Exact match in city_aliases
    if key in city_aliases:
        return NormalizationResult(
            value=city_aliases[key],
            is_valid=True,
            issue=None,
            raw=city,
        )

    # 2. Check if key matches canonical values case-insensitively
    canonical_map = {v.lower(): v for v in city_aliases.values()}
    if key in canonical_map:
        return NormalizationResult(
            value=canonical_map[key],
            is_valid=True,
            issue=None,
            raw=city,
        )

    # Unmapped city -> flag for review, do not guess
    return NormalizationResult(
        value=None,
        is_valid=False,
        issue="city_unknown",
        raw=city,
    )


def normalize_state(state: Any, rules: Optional[Dict[str, Any]] = None) -> NormalizationResult:
    """Normalize state name via case-insensitive lookup in rules.yaml.

    Rules:
    - Look up lowercased state in rules['state_aliases'].
    - If mapped, return canonical state name.
    - If not mapped, check canonical state values from rules.
    - If unmapped, route to review with 'state_unknown' (do not guess).
    """
    raw_str = _clean_str(state)
    if not raw_str:
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="state_missing",
            raw=state,
        )

    rules_dict = rules if rules is not None else load_rules()
    state_aliases = rules_dict.get("state_aliases", {})

    key = raw_str.strip().lower()

    # 1. Exact match in state_aliases
    if key in state_aliases:
        return NormalizationResult(
            value=state_aliases[key],
            is_valid=True,
            issue=None,
            raw=state,
        )

    # 2. Check known canonical states across rules (state_aliases, gst_state_codes, pin_prefixes)
    known_canonical = set(state_aliases.values())
    known_canonical.update(rules_dict.get("gst_state_codes", {}).values())
    known_canonical.update(rules_dict.get("pin_prefixes", {}).values())

    canonical_map = {s.lower(): s for s in known_canonical if s}
    if key in canonical_map:
        return NormalizationResult(
            value=canonical_map[key],
            is_valid=True,
            issue=None,
            raw=state,
        )

    return NormalizationResult(
        value=None,
        is_valid=False,
        issue="state_unknown",
        raw=state,
    )


def normalize_pin_code(
    pin_code: Any,
    state: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> NormalizationResult:
    """Validate 6-digit Indian PIN code and infer state if blank.

    Rules:
    - Validate regex: ^[1-9][0-9]{5}$
    - If state is blank or missing, query first 2 digits against pin_prefixes in rules.yaml.
    - Set inferred_state if found in pin_prefixes.
    - If malformed, route to review with 'pin_invalid'.
    """
    raw_str = _clean_str(pin_code)
    if not raw_str:
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="pin_missing",
            raw=pin_code,
        )

    # Strip any internal spaces or hyphens (e.g. 122 002 or 122-002)
    cleaned = re.sub(r"[\s-]", "", raw_str)

    if not PIN_CODE_REGEX.match(cleaned):
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="pin_invalid",
            raw=pin_code,
        )

    # Lookup state from pin_prefixes
    rules_dict = rules if rules is not None else load_rules()
    pin_prefixes = rules_dict.get("pin_prefixes", {})
    prefix = cleaned[:2]
    inferred_state = pin_prefixes.get(prefix)

    # Check if state was blank/missing
    state_str = _clean_str(state)
    state_inferred_for_blank = inferred_state if not state_str else None

    return NormalizationResult(
        value=cleaned,
        is_valid=True,
        issue=None,
        inferred_state=inferred_state if not state_str else inferred_state,
        raw=pin_code,
    )


def normalize_gst(
    gst: Any,
    state: Optional[str] = None,
    rules: Optional[Dict[str, Any]] = None,
) -> NormalizationResult:
    """Validate Indian GST number and check first 2 digits against gst_state_codes.

    Rules:
    - 15-character format: ^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$
    - Check first 2 digits against gst_state_codes in rules.yaml.
    - If state is provided, verify state matches the GST state code.
    - Route to review with 'gst_invalid', 'gst_state_code_unknown', or 'gst_state_mismatch'.
    """
    raw_str = _clean_str(gst)
    if not raw_str:
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="gst_missing",
            raw=gst,
        )

    cleaned = re.sub(r"\s+", "", raw_str).upper()

    if not GST_REGEX.match(cleaned):
        return NormalizationResult(
            value=None,
            is_valid=False,
            issue="gst_invalid",
            raw=gst,
        )

    rules_dict = rules if rules is not None else load_rules()
    gst_state_codes = rules_dict.get("gst_state_codes", {})
    state_code = cleaned[:2]

    gst_state = gst_state_codes.get(state_code)
    if not gst_state:
        return NormalizationResult(
            value=cleaned,
            is_valid=False,
            issue="gst_state_code_unknown",
            inferred_state=None,
            raw=gst,
        )

    # If state is provided, check for match
    state_str = _clean_str(state)
    if state_str:
        norm_state = normalize_state(state_str, rules=rules_dict)
        expected_state = norm_state.value if norm_state.is_valid else state_str.strip()
        if expected_state.lower() != gst_state.lower():
            return NormalizationResult(
                value=cleaned,
                is_valid=False,
                issue="gst_state_mismatch",
                inferred_state=gst_state,
                raw=gst,
            )

    return NormalizationResult(
        value=cleaned,
        is_valid=True,
        issue=None,
        inferred_state=gst_state,
        raw=gst,
    )


def _get_field(record: Dict[str, Any], *aliases: str) -> Any:
    """Retrieve field value from record matching any alias case-insensitively."""
    # 1. Direct match
    for alias in aliases:
        if alias in record and record[alias] is not None:
            return record[alias]

    # 2. Key-normalized match (case-insensitive, ignoring spaces/underscores/hyphens)
    normalized_keys = {
        re.sub(r"[\s_-]+", "", str(k).lower()): v for k, v in record.items()
    }
    for alias in aliases:
        norm_alias = re.sub(r"[\s_-]+", "", alias.lower())
        if norm_alias in normalized_keys and normalized_keys[norm_alias] is not None:
            return normalized_keys[norm_alias]

    return None


def normalize_record(
    record: Dict[str, Any],
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize a complete row/record of lead data.

    Returns a dictionary containing normalized canonical fields and collected issues.
    Preserves all original fields with raw_ prefix.
    """
    rules_dict = rules if rules is not None else load_rules()
    normalized: Dict[str, Any] = {}
    issues: List[str] = []

    # Preserve raw fields
    for k, v in record.items():
        if not str(k).startswith("raw_"):
            normalized[f"raw_{k}"] = v
        else:
            normalized[str(k)] = v

    # 1. Names
    first_name_input = _get_field(record, "first_name", "first name", "firstname", "fname")
    last_name_input = _get_field(record, "last_name", "last name", "lastname", "lname", "surname")
    full_name_input = _get_field(record, "full_name", "full name", "fullname", "name", "contact name")

    if full_name_input and (not first_name_input and not last_name_input):
        fn_res, ln_res = split_full_name(full_name_input)
        normalized["first_name"] = fn_res.value
        normalized["last_name"] = ln_res.value
        if fn_res.issue:
            issues.append(fn_res.issue)
    else:
        fn_res = normalize_name(first_name_input) if first_name_input else NormalizationResult(None, False, "first_name_missing")
        ln_res = normalize_name(last_name_input) if last_name_input else NormalizationResult(None, False, "last_name_missing")
        normalized["first_name"] = fn_res.value
        normalized["last_name"] = ln_res.value
        if fn_res.issue and fn_res.issue != "name_missing":
            issues.append(fn_res.issue)

    # 2. Phone
    phone_res = normalize_phone(
        _get_field(record, "phone", "contact number", "contact_number", "mobile", "phone number", "phone_number", "telephone")
    )
    normalized["phone"] = phone_res.value
    if phone_res.issue:
        issues.append(phone_res.issue)

    # 3. Email
    email_res = normalize_email(
        _get_field(record, "email", "email address", "email_address", "mail")
    )
    normalized["email"] = email_res.value
    if email_res.issue:
        issues.append(email_res.issue)

    # 4. City
    city_res = normalize_city(
        _get_field(record, "city", "town", "city_name", "city name"),
        rules=rules_dict,
    )
    normalized["city"] = city_res.value
    if city_res.issue:
        issues.append(city_res.issue)

    # 5. State (Initial lookup)
    raw_state = _get_field(record, "state", "state name", "state_name", "province")
    state_res = normalize_state(raw_state, rules=rules_dict)

    # 6. PIN Code (with state inference if state is blank)
    pin_input = _get_field(record, "pin_code", "pin code", "pincode", "postal_code", "postal code", "zip")
    pin_res = normalize_pin_code(pin_input, state=state_res.value, rules=rules_dict)
    normalized["pin_code"] = pin_res.value
    if pin_res.issue:
        issues.append(pin_res.issue)

    # Resolve state: use explicit state if valid, otherwise infer from PIN
    final_state = state_res.value
    if not final_state and pin_res.inferred_state:
        final_state = pin_res.inferred_state
    elif state_res.issue and not (not raw_state and pin_res.inferred_state):
        issues.append(state_res.issue)

    normalized["state"] = final_state

    # 7. GST (check against state)
    gst_input = _get_field(record, "gst_number", "gst number", "gstin", "gst", "gst no", "gst_no")
    if gst_input:
        gst_res = normalize_gst(gst_input, state=final_state, rules=rules_dict)
        normalized["gst_number"] = gst_res.value
        if gst_res.issue:
            issues.append(gst_res.issue)
        # If state was still blank and GST has valid state code, infer it
        if not normalized["state"] and gst_res.inferred_state:
            normalized["state"] = gst_res.inferred_state
    else:
        normalized["gst_number"] = None

    normalized["issues"] = issues
    normalized["needs_review"] = len(issues) > 0

    return normalized

