"""Lead file ingestion and column mapping module.

Handles:
- Loading CSV and Excel (.xlsx, .xls) files
- Automatic encoding detection (UTF-8 first, fallback to windows-1252 / latin1 via chardet)
- Column alias mapping against config/mappings.yaml
- Preserving all raw incoming data under raw_* columns
- Splitting combined Full Name into first_name and last_name
- Producing a clean DataFrame conforming to standard canonical schema
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import chardet
import pandas as pd
import yaml

from cleaner.normalize import split_full_name

CANONICAL_COLUMNS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "company",
    "city",
    "state",
    "pin_code",
    "gst_number",
    "consent_source",
    "consent_date",
    "source",
    "notes_raw",
]

_MAPPINGS_CACHE: Optional[Dict[str, Any]] = None


def get_default_mappings_path() -> Path:
    """Return default path to config/mappings.yaml."""
    return Path(__file__).resolve().parent.parent / "config" / "mappings.yaml"


def load_mappings(
    mappings_path: Optional[Union[str, Path]] = None, reload: bool = False
) -> Dict[str, Any]:
    """Load column mappings from YAML configuration."""
    global _MAPPINGS_CACHE
    if _MAPPINGS_CACHE is not None and not reload and mappings_path is None:
        return _MAPPINGS_CACHE

    target_path = Path(mappings_path) if mappings_path else get_default_mappings_path()
    if target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        # Fallback embedded mappings
        data = {
            "exact_matches": {
                "Full Name": "full_name",
                "Contact Number": "phone",
                "Email Address": "email",
                "Town": "city",
                "State Name": "state",
                "Pincode": "pin_code",
                "GSTIN": "gst_number",
                "Consent Source": "consent_source",
                "Notes": "notes_raw",
            },
            "normalized_matches": {
                "fullname": "full_name",
                "contactnumber": "phone",
                "emailaddress": "email",
                "town": "city",
                "statename": "state",
                "pincode": "pin_code",
                "gstin": "gst_number",
                "consentsource": "consent_source",
                "notes": "notes_raw",
            },
        }

    if mappings_path is None:
        _MAPPINGS_CACHE = data
    return data


def normalize_col_header(header: str) -> str:
    """Normalize a header string: stripped, lowercase, alphanumeric only."""
    import re
    return re.sub(r"[^a-zA-Z0-9]", "", str(header).strip()).lower()


def detect_encoding(file_path_or_bytes: Union[str, Path, bytes, io.BytesIO]) -> str:
    """Detect encoding of a CSV file or bytes using chardet.

    Tries UTF-8 first; if that fails or confidence is low, falls back to detected encoding
    or windows-1252.
    """
    if isinstance(file_path_or_bytes, (str, Path)):
        with open(file_path_or_bytes, "rb") as f:
            raw_bytes = f.read(65536)
    elif isinstance(file_path_or_bytes, io.BytesIO):
        pos = file_path_or_bytes.tell()
        raw_bytes = file_path_or_bytes.read(65536)
        file_path_or_bytes.seek(pos)
    elif isinstance(file_path_or_bytes, bytes):
        raw_bytes = file_path_or_bytes[:65536]
    else:
        raw_bytes = b""

    # Test UTF-8 decoding directly
    try:
        raw_bytes.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Use chardet
    detected = chardet.detect(raw_bytes)
    encoding = detected.get("encoding")
    if encoding and detected.get("confidence", 0) > 0.6:
        return encoding

    # Default fallback for Excel-generated CSVs
    return "windows-1252"


def read_file(
    file_path_or_buffer: Union[str, Path, bytes, io.BytesIO],
    filename: Optional[str] = None,
) -> Tuple[pd.DataFrame, str]:
    """Read a CSV or Excel file into a raw pandas DataFrame.

    Returns (df, detected_filename).
    """
    target_filename = filename
    if target_filename is None:
        if isinstance(file_path_or_buffer, (str, Path)):
            target_filename = Path(file_path_or_buffer).name
        else:
            target_filename = "leads_input.csv"

    lower_name = target_filename.lower()
    is_excel = lower_name.endswith(".xlsx") or lower_name.endswith(".xls")
    is_csv = lower_name.endswith(".csv")

    if not (is_excel or is_csv):
        raise ValueError(
            f"Unsupported file format for '{target_filename}'. Only CSV (.csv) and Excel (.xlsx, .xls) files are supported."
        )

    if is_excel:
        if isinstance(file_path_or_buffer, bytes):
            buffer = io.BytesIO(file_path_or_buffer)
            df = pd.read_excel(buffer)
        else:
            df = pd.read_excel(file_path_or_buffer)
        return df, target_filename

    # Handle CSV
    # Try reading as utf-8 first
    encodings_to_try = ["utf-8", "utf-8-sig"]
    detected_enc = detect_encoding(file_path_or_buffer)
    if detected_enc not in encodings_to_try:
        encodings_to_try.append(detected_enc)
    for fallback in ["windows-1252", "latin1", "iso-8859-1"]:
        if fallback not in encodings_to_try:
            encodings_to_try.append(fallback)

    last_error: Optional[Exception] = None
    for enc in encodings_to_try:
        try:
            if isinstance(file_path_or_buffer, bytes):
                buffer = io.BytesIO(file_path_or_buffer)
                df = pd.read_csv(buffer, encoding=enc, dtype=str)
            elif isinstance(file_path_or_buffer, io.BytesIO):
                pos = file_path_or_buffer.tell()
                df = pd.read_csv(file_path_or_buffer, encoding=enc, dtype=str)
                file_path_or_buffer.seek(pos)
            else:
                df = pd.read_csv(file_path_or_buffer, encoding=enc, dtype=str)
            return df, target_filename
        except (UnicodeDecodeError, Exception) as e:
            last_error = e
            continue

    raise ValueError(f"Failed to decode CSV file {target_filename}: {last_error}")


def map_columns(
    df: pd.DataFrame,
    mappings: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Determine the mapping from raw column names to canonical target fields.

    Uses config/mappings.yaml exact_matches and normalized_matches.
    Returns dict {raw_column_name: target_field_name}.
    """
    rules = mappings if mappings is not None else load_mappings()
    exact_matches = rules.get("exact_matches", {})
    normalized_matches = rules.get("normalized_matches", {})

    col_map: Dict[str, str] = {}
    used_targets = set()

    for col in df.columns:
        col_str = str(col).strip()
        target: Optional[str] = None

        # 1. Exact match
        if col_str in exact_matches:
            target = exact_matches[col_str]
        # 2. Case-insensitive / normalized match
        else:
            norm_col = normalize_col_header(col_str)
            if norm_col in normalized_matches:
                target = normalized_matches[norm_col]

        if target:
            # Avoid duplicate target field mapping if already assigned
            if target not in used_targets or target == "full_name":
                col_map[col] = target
                used_targets.add(target)

    return col_map


def load_and_map(
    file_path_or_buffer: Union[str, Path, bytes, io.BytesIO],
    filename: Optional[str] = None,
    mappings_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Load an input lead file (CSV or Excel) and apply column mapping.

    Steps:
    1. Read raw CSV or Excel into DataFrame, detecting encoding.
    2. Retain all original source columns with 'raw_' prefix.
    3. Map recognized raw columns to canonical target fields.
    4. Handle 'full_name' splitting into 'first_name' and 'last_name' if unified.
    5. Ensure all standard canonical columns are present in the output.
    6. Populate 'source' with filename if empty.
    7. Return clean DataFrame ready for normalization.
    """
    raw_df, target_filename = read_file(file_path_or_buffer, filename=filename)
    mappings = load_mappings(mappings_path)
    col_mapping = map_columns(raw_df, mappings=mappings)

    out_df = pd.DataFrame()

    # 1. Preserve ALL raw columns prefixed with raw_
    for col in raw_df.columns:
        raw_key = col if str(col).startswith("raw_") else f"raw_{col}"
        # Keep raw values converted to string (or None if NaN)
        out_df[raw_key] = raw_df[col].apply(
            lambda v: str(v).strip() if pd.notna(v) and str(v).strip() != "" else ""
        )

    # 2. Populate canonical columns from mapped columns
    for raw_col, target_field in col_mapping.items():
        if target_field not in out_df.columns or target_field == "full_name":
            out_df[target_field] = raw_df[raw_col].apply(
                lambda v: str(v).strip() if pd.notna(v) and str(v).strip() != "" else ""
            )

    # 3. Handle full_name splitting if first_name / last_name not provided
    if "full_name" in out_df.columns:
        if "first_name" not in out_df.columns:
            out_df["first_name"] = ""
        if "last_name" not in out_df.columns:
            out_df["last_name"] = ""

        # For rows where first_name is empty, split from full_name
        for idx, row in out_df.iterrows():
            fn_val = row.get("first_name", "")
            full_val = row.get("full_name", "")
            if (not fn_val or pd.isna(fn_val)) and full_val and pd.notna(full_val):
                fn_res, ln_res = split_full_name(full_val)
                out_df.at[idx, "first_name"] = fn_res.value or ""
                # Also set last_name if empty
                if not row.get("last_name") or pd.isna(row.get("last_name")):
                    out_df.at[idx, "last_name"] = ln_res.value or ""

        # Drop the temporary full_name column from standard schema
        out_df.drop(columns=["full_name"], inplace=True)

    # 4. Ensure all standard canonical schema columns exist
    for col in CANONICAL_COLUMNS:
        if col not in out_df.columns:
            out_df[col] = ""

    # 5. Populate source column with input filename if empty
    out_df["source"] = out_df["source"].apply(
        lambda v: v if pd.notna(v) and str(v).strip() != "" else target_filename
    )

    # Reorder columns: Canonical columns first, followed by raw_* columns
    raw_cols = [c for c in out_df.columns if c.startswith("raw_")]
    final_cols = CANONICAL_COLUMNS + [c for c in raw_cols if c not in CANONICAL_COLUMNS]

    return out_df[final_cols]
