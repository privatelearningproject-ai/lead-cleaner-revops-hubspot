"""Validation and Lead Quality Scoring Engine for Indian SMB leads.

Inspects normalized records, accumulates validation issue tags,
computes quality scores (0-100), and classifies leads for
either cleaned.csv or review.csv.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Union
import pandas as pd

from cleaner.normalize import (
    load_rules,
    normalize_city,
    normalize_email,
    normalize_gst,
    normalize_name,
    normalize_phone,
    normalize_pin_code,
    normalize_state,
)

# Issues that fatally prevent automatic export to cleaned.csv
FATAL_ISSUES: Set[str] = {
    "phone_invalid",
    "email_invalid",
    "missing_contact",
    "gst_state_mismatch",
    "city_unknown",
    "state_unknown",
    "missing_name",
}


def _val_to_str(val: Any) -> str:
    """Helper to convert value to clean stripped string."""
    if val is None or pd.isna(val):
        return ""
    return str(val).strip()


def calculate_quality_score(row: Union[Dict[str, Any], pd.Series]) -> int:
    """Calculate lead quality score from 0 to 100.

    Deduction rules:
    - Base score: 100
    - No valid phone or email: -40
    - Invalid phone (when phone was provided): -20
    - Invalid email (when email was provided): -20
    - Missing first name: -15
    - Unknown or missing city: -10
    - Unknown or missing state: -10
    - Missing PIN or invalid: -5
    - GST invalid or state mismatch (when GST provided): -10
    - Missing consent source: -10

    Score is clamped between 0 and 100.
    """
    score = 100

    # Extract fields
    first_name = _val_to_str(row.get("first_name"))
    phone = _val_to_str(row.get("phone"))
    email = _val_to_str(row.get("email"))
    city = _val_to_str(row.get("city"))
    state = _val_to_str(row.get("state"))
    pin = _val_to_str(row.get("pin_code"))
    gst = _val_to_str(row.get("gst_number"))
    consent = _val_to_str(row.get("consent_source"))

    # Extract issues if already computed
    issues_val = row.get("issues", [])
    if isinstance(issues_val, str):
        issues_set = set(i.strip() for i in issues_val.split(",") if i.strip())
    elif isinstance(issues_val, (list, set, tuple)):
        issues_set = set(issues_val)
    else:
        issues_set = set()

    # 1. Contact checks
    has_valid_phone = bool(phone and "phone_invalid" not in issues_set)
    has_valid_email = bool(email and "email_invalid" not in issues_set)

    if not has_valid_phone and not has_valid_email:
        score -= 40

    if "phone_invalid" in issues_set:
        score -= 20

    if "email_invalid" in issues_set:
        score -= 20

    # 2. Name check
    if not first_name or "missing_name" in issues_set:
        score -= 15

    # 3. Location checks
    if not city or "city_unknown" in issues_set:
        score -= 10

    if not state or "state_unknown" in issues_set:
        score -= 10

    if not pin or "pin_invalid" in issues_set:
        score -= 5

    # 4. GST check (only deduct if GST was provided or attempted)
    if "gst_invalid" in issues_set or "gst_state_mismatch" in issues_set or "gst_state_code_unknown" in issues_set:
        score -= 10

    # 5. Consent check
    if not consent or "consent_missing" in issues_set:
        score -= 10

    return max(0, min(100, score))


def validate_row(
    row: Union[Dict[str, Any], pd.Series],
    rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate a single lead row, collecting issue flags, score, and routing decision.

    Inspects both normalized fields and raw values.
    Returns a dict with updated fields:
    - issues: list of string tags
    - issues_str: comma-separated string of issues
    - quality_score: integer 0-100
    - route: 'cleaned' or 'review'
    - needs_review: boolean
    """
    rules_dict = rules if rules is not None else load_rules()
    data = dict(row)
    issues: List[str] = []

    # 1. Names
    first_name = _val_to_str(data.get("first_name"))
    last_name = _val_to_str(data.get("last_name"))
    raw_name = _val_to_str(data.get("raw_Full Name") or data.get("raw_Name") or data.get("raw_Cust Name") or data.get("raw_first_name"))

    if not first_name and not last_name:
        issues.append("missing_name")

    # 2. Phone
    phone = _val_to_str(data.get("phone"))
    raw_phone = _val_to_str(
        data.get("raw_Contact Number") or data.get("raw_Phone") or data.get("raw_Mobile") or data.get("raw_Mobile Number")
    )
    if raw_phone:
        phone_norm = normalize_phone(raw_phone)
        if not phone_norm.is_valid:
            if "phone_invalid" not in issues:
                issues.append("phone_invalid")
            data["phone"] = None
        else:
            data["phone"] = phone_norm.value

    # 3. Email
    email = _val_to_str(data.get("email"))
    raw_email = _val_to_str(
        data.get("raw_Email Address") or data.get("raw_Email") or data.get("raw_Email ID") or data.get("raw_Mail")
    )
    if raw_email:
        email_norm = normalize_email(raw_email)
        if not email_norm.is_valid:
            if "email_invalid" not in issues:
                issues.append("email_invalid")
            data["email"] = None
        else:
            data["email"] = email_norm.value

    # Contact check: both phone and email empty or invalid
    curr_phone = _val_to_str(data.get("phone"))
    curr_email = _val_to_str(data.get("email"))
    if not curr_phone and not curr_email:
        issues.append("missing_contact")

    # 4. City
    city = _val_to_str(data.get("city"))
    raw_city = _val_to_str(data.get("raw_Town") or data.get("raw_City") or data.get("raw_Town/City") or data.get("raw_Location"))
    if raw_city:
        city_norm = normalize_city(raw_city, rules=rules_dict)
        if not city_norm.is_valid:
            if "city_unknown" not in issues:
                issues.append("city_unknown")
            data["city"] = None
        else:
            data["city"] = city_norm.value

    # 5. State
    state = _val_to_str(data.get("state"))
    raw_state = _val_to_str(data.get("raw_State Name") or data.get("raw_State") or data.get("raw_Province"))
    if raw_state:
        state_norm = normalize_state(raw_state, rules=rules_dict)
        if not state_norm.is_valid:
            # Check if state was inferred by PIN
            raw_pin = _val_to_str(data.get("raw_Pincode") or data.get("raw_pin_code") or data.get("raw_PIN Code") or data.get("pin_code"))
            pin_norm = normalize_pin_code(raw_pin, state=None, rules=rules_dict) if raw_pin else None
            if pin_norm and pin_norm.inferred_state:
                data["state"] = pin_norm.inferred_state
            else:
                if "state_unknown" not in issues:
                    issues.append("state_unknown")
                data["state"] = None
        else:
            data["state"] = state_norm.value
    elif not state:
        # Check if state can be inferred from PIN code
        raw_pin = _val_to_str(data.get("raw_Pincode") or data.get("raw_pin_code") or data.get("pin_code"))
        if raw_pin:
            pin_norm = normalize_pin_code(raw_pin, state=None, rules=rules_dict)
            if pin_norm.is_valid and pin_norm.inferred_state:
                data["state"] = pin_norm.inferred_state

    # 6. PIN Code
    pin = _val_to_str(data.get("pin_code"))
    raw_pin = _val_to_str(data.get("raw_Pincode") or data.get("raw_pin_code") or data.get("raw_PIN Code") or data.get("pin_code"))
    if raw_pin:
        pin_norm = normalize_pin_code(raw_pin, state=data.get("state"), rules=rules_dict)
        if not pin_norm.is_valid:
            if "pin_invalid" not in issues:
                issues.append("pin_invalid")
            data["pin_code"] = None
        else:
            data["pin_code"] = pin_norm.value
            if not data.get("state") and pin_norm.inferred_state:
                data["state"] = pin_norm.inferred_state

    # 7. GST
    raw_gst = _val_to_str(data.get("raw_GSTIN") or data.get("raw_gst_number") or data.get("raw_GST") or data.get("gst_number"))
    if raw_gst:
        gst_norm = normalize_gst(raw_gst, state=data.get("state"), rules=rules_dict)
        if not gst_norm.is_valid:
            if gst_norm.issue and gst_norm.issue not in issues:
                issues.append(gst_norm.issue)
            data["gst_number"] = None
        else:
            data["gst_number"] = gst_norm.value

    # 8. Consent
    consent = _val_to_str(data.get("consent_source") or data.get("raw_Consent Source"))
    if not consent:
        issues.append("consent_missing")
        data["consent_source"] = None
    else:
        data["consent_source"] = consent

    # Merge with existing issues in row if any
    existing_issues = data.get("issues", [])
    if isinstance(existing_issues, (list, tuple, set)):
        for iss in existing_issues:
            if iss not in issues:
                issues.append(iss)

    data["issues"] = issues
    data["issues_str"] = ", ".join(issues)

    # Compute quality score
    score = calculate_quality_score(data)
    data["quality_score"] = score

    # Classification
    # Score >= 70 AND no fatal issues -> cleaned.csv
    has_fatal_issue = any(iss in FATAL_ISSUES for iss in issues)
    if score >= 70 and not has_fatal_issue:
        data["route"] = "cleaned"
        data["needs_review"] = False
    else:
        data["route"] = "review"
        data["needs_review"] = True

    return data


def validate_dataframe(
    df: pd.DataFrame,
    rules: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Validate all rows in a DataFrame, appending quality_score, issues, and route columns."""
    rules_dict = rules if rules is not None else load_rules()
    validated_rows: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        validated_rows.append(validate_row(row.to_dict(), rules=rules_dict))

    out_df = pd.DataFrame(validated_rows)
    return out_df
