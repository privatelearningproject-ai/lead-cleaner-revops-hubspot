"""Cloud LLM enrichment module with multi-tenant quota enforcement.

Extracts structured insights (budget, product_interest, city) from unstructured
lead notes (notes_raw) using cloud LLM APIs:
- Primary: Google Gemini API (gemini-1.5-flash)
- Alternative: Grok (xAI)

Features:
- Enforced Multi-Tenant Freemium Quota: Exactly 500 contacts lifetime/cycle per portal_id.
- Batch Cap: If a batch exceeds remaining quota, only enriches up to remaining quota,
  then tags remaining records with 'quota_exceeded' and provides an upgrade alert.
- Zero Crashes: Timeouts, network errors, or malformed JSON responses fail gracefully
  with 'enrichment_failed'.
- Strict JSON Schema: {"budget": str|null, "product_interest": str|null, "city": str|null}.
- Safety Guardrail: All enriched records tagged with enrichment_pending_review=True.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple, Union
from dotenv import load_dotenv
import pandas as pd
import requests

from cleaner.db import (
    DEFAULT_DB_PATH,
    get_enrichment_quota,
    increment_enrichment_quota_used,
)

DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
DEFAULT_GROK_MODEL = "grok-beta"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_FREEMIUM_QUOTA = 500
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GROK_API_BASE = "https://api.x.ai/v1/chat/completions"


def is_enrichment_enabled(default: bool = False) -> bool:
    """Check if LLM enrichment is enabled via environment variables or parameter."""
    load_dotenv()
    env_val = os.environ.get("ENRICHMENT_ENABLED")
    if env_val is not None:
        return env_val.strip().lower() in {"true", "1", "yes", "y", "t"}
    return default


def get_gemini_api_key() -> Optional[str]:
    """Retrieve Google Gemini API key from environment."""
    load_dotenv()
    key = os.environ.get("GEMINI_API_KEY")
    return key.strip() if key and key.strip() else None


def get_grok_api_key() -> Optional[str]:
    """Retrieve Grok API key from environment."""
    load_dotenv()
    key = os.environ.get("GROK_API_KEY")
    return key.strip() if key and key.strip() else None


def get_llm_provider() -> str:
    """Retrieve configured LLM provider ('gemini' or 'grok')."""
    load_dotenv()
    return os.environ.get("LLM_PROVIDER", "gemini").strip().lower()


def _clean_json_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON from model response, handling optional markdown code fences."""
    if not raw_text or not raw_text.strip():
        return None

    cleaned = raw_text.strip()
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = cleaned[first_brace : last_brace + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


def _call_gemini_api(
    text: str,
    api_key: str,
    model: str = DEFAULT_GEMINI_MODEL,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Call Google Gemini generateContent API enforcing JSON output."""
    url = f"{GEMINI_API_BASE}/{model}:generateContent?key={api_key}"

    prompt = (
        "You are an expert RevOps CRM data extraction assistant for Indian businesses.\n"
        "Analyze the following sales lead note and extract structured fields in JSON format:\n"
        "- budget: Numeric amount or range with currency/units if stated (e.g. '50,000 INR', '2.5 Lakhs', '10k USD', or null if not mentioned).\n"
        "- product_interest: Specific product, software, or service named (or null if not mentioned).\n"
        "- city: Geographic location or city mentioned (or null if not mentioned).\n\n"
        f"Lead Note: {text}\n\n"
        "Output ONLY a valid JSON object with keys 'budget', 'product_interest', and 'city'. Do not add commentary or markdown."
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0,
        },
    }

    response = requests.post(url, json=payload, timeout=timeout)
    if response.status_code != 200:
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "failed",
            "error": f"Gemini HTTP {response.status_code}: {response.text[:100]}",
        }

    res_data = response.json()
    candidates = res_data.get("candidates", [])
    if not candidates:
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "failed",
            "error": "No candidates returned by Gemini",
        }

    part_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    extracted = _clean_json_response(part_text)
    if extracted is None:
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "failed",
            "error": "Failed to parse JSON from Gemini response",
        }

    return {
        "budget": str(extracted.get("budget")).strip() if extracted.get("budget") is not None else None,
        "product_interest": str(extracted.get("product_interest")).strip() if extracted.get("product_interest") is not None else None,
        "city": str(extracted.get("city")).strip() if extracted.get("city") is not None else None,
        "status": "success",
        "error": None,
    }


def _call_grok_api(
    text: str,
    api_key: str,
    model: str = DEFAULT_GROK_MODEL,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Call Grok xAI API with JSON response format."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a RevOps assistant. Extract budget, product_interest, and city from lead notes into JSON: {'budget': str|null, 'product_interest': str|null, 'city': str|null}.",
            },
            {"role": "user", "content": text},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }

    response = requests.post(GROK_API_BASE, json=payload, headers=headers, timeout=timeout)
    if response.status_code != 200:
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "failed",
            "error": f"Grok HTTP {response.status_code}: {response.text[:100]}",
        }

    res_data = response.json()
    content = res_data.get("choices", [{}])[0].get("message", {}).get("content", "")
    extracted = _clean_json_response(content)
    if extracted is None:
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "failed",
            "error": "Failed to parse JSON from Grok response",
        }

    return {
        "budget": str(extracted.get("budget")).strip() if extracted.get("budget") is not None else None,
        "product_interest": str(extracted.get("product_interest")).strip() if extracted.get("product_interest") is not None else None,
        "city": str(extracted.get("city")).strip() if extracted.get("city") is not None else None,
        "status": "success",
        "error": None,
    }


def extract_lead_notes(
    notes_raw: Any,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """Extract structured budget, product_interest, and city from raw notes.

    Args:
        notes_raw: Unstructured text note.
        api_key: API key for Gemini or Grok (defaults to env var).
        provider: 'gemini' (default) or 'grok'.
        model: Model name.
        timeout: Per-request timeout in seconds.

    Returns:
        Dict with keys: budget, product_interest, city, status, error.
    """
    if notes_raw is None or pd.isna(notes_raw):
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "skipped",
            "error": None,
        }

    text = str(notes_raw).strip()
    if not text:
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "skipped",
            "error": None,
        }

    chosen_provider = (provider or get_llm_provider()).lower()

    if chosen_provider == "grok":
        key = api_key or get_grok_api_key()
        if not key:
            return {
                "budget": None,
                "product_interest": None,
                "city": None,
                "status": "failed",
                "error": "GROK_API_KEY missing",
            }
        try:
            return _call_grok_api(text, api_key=key, model=model or DEFAULT_GROK_MODEL, timeout=timeout)
        except requests.exceptions.Timeout:
            return {"budget": None, "product_interest": None, "city": None, "status": "failed", "error": f"Timed out after {timeout}s"}
        except Exception as e:
            return {"budget": None, "product_interest": None, "city": None, "status": "failed", "error": str(e)}

    # Default: Google Gemini Flash
    key = api_key or get_gemini_api_key()
    if not key:
        return {
            "budget": None,
            "product_interest": None,
            "city": None,
            "status": "failed",
            "error": "GEMINI_API_KEY missing",
        }

    try:
        return _call_gemini_api(text, api_key=key, model=model or DEFAULT_GEMINI_MODEL, timeout=timeout)
    except requests.exceptions.Timeout:
        return {"budget": None, "product_interest": None, "city": None, "status": "failed", "error": f"Timed out after {timeout}s"}
    except requests.exceptions.ConnectionError:
        return {"budget": None, "product_interest": None, "city": None, "status": "failed", "error": "Connection error reaching Cloud LLM API"}
    except Exception as e:
        return {"budget": None, "product_interest": None, "city": None, "status": "failed", "error": str(e)}


def enrich_dataframe(
    df: pd.DataFrame,
    enabled: bool = False,
    portal_id: Union[str, int] = "default_portal",
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Enrich lead DataFrame notes with multi-tenant quota enforcement.

    Quota & Billing Guard:
    - Freemium Limit: 500 contacts per portal_id.
    - If remaining quota <= 0: Bypasses LLM, tags records with 'quota_exceeded',
      and returns upgrade warning prompt.
    - If batch > remaining quota: Enriches up to remaining quota, halts LLM calls,
      and tags the remainder as 'quota_exceeded'.

    Returns:
        Tuple of (enriched_df, quota_summary_dict)
    """
    enriched_df = df.copy()

    # Ensure tracking columns exist
    if "notes_structured" not in enriched_df.columns:
        enriched_df["notes_structured"] = None
    if "enrichment_status" not in enriched_df.columns:
        enriched_df["enrichment_status"] = "skipped"
    if "enrichment_pending_review" not in enriched_df.columns:
        enriched_df["enrichment_pending_review"] = False

    quota_info = get_enrichment_quota(portal_id, db_path=db_path)

    if not enabled:
        return enriched_df, {
            "portal_id": str(portal_id),
            "quota_limit": quota_info["limit"],
            "quota_used": quota_info["used"],
            "quota_remaining": quota_info["remaining"],
            "enriched_this_run": 0,
            "quota_exceeded": quota_info["is_exceeded"],
            "message": "Enrichment disabled.",
        }

    if "notes_raw" not in enriched_df.columns:
        return enriched_df, {
            "portal_id": str(portal_id),
            "quota_limit": quota_info["limit"],
            "quota_used": quota_info["used"],
            "quota_remaining": quota_info["remaining"],
            "enriched_this_run": 0,
            "quota_exceeded": False,
            "message": "No notes_raw column in input.",
        }

    remaining_allowance = quota_info["remaining"]
    enriched_count = 0
    quota_hit = remaining_allowance <= 0

    for idx in enriched_df.index:
        raw_note = enriched_df.at[idx, "notes_raw"]
        is_empty_note = raw_note is None or pd.isna(raw_note) or not str(raw_note).strip()

        if is_empty_note:
            enriched_df.at[idx, "enrichment_status"] = "skipped"
            enriched_df.at[idx, "enrichment_pending_review"] = False
            continue

        # Check quota guard before calling LLM
        if remaining_allowance <= 0:
            quota_hit = True
            enriched_df.at[idx, "enrichment_status"] = "quota_exceeded"
            enriched_df.at[idx, "enrichment_pending_review"] = False
            # Tag issue
            if "issues" in enriched_df.columns:
                existing_issues = enriched_df.at[idx, "issues"]
                if isinstance(existing_issues, list):
                    if "quota_exceeded" not in existing_issues:
                        enriched_df.at[idx, "issues"].append("quota_exceeded")
                elif isinstance(existing_issues, str):
                    issues_list = [i.strip() for i in existing_issues.split(",") if i.strip()]
                    if "quota_exceeded" not in issues_list:
                        issues_list.append("quota_exceeded")
                        enriched_df.at[idx, "issues"] = ", ".join(issues_list)
            continue

        # Allowed to call Cloud LLM
        res = extract_lead_notes(
            notes_raw=raw_note,
            api_key=api_key,
            provider=provider,
            model=model,
            timeout=timeout,
        )

        status = res.get("status", "skipped")
        enriched_df.at[idx, "enrichment_status"] = status

        if status == "success":
            payload = {
                "budget": res.get("budget"),
                "product_interest": res.get("product_interest"),
                "city": res.get("city"),
            }
            enriched_df.at[idx, "notes_structured"] = json.dumps(payload, ensure_ascii=False)
            enriched_df.at[idx, "enrichment_pending_review"] = True

            # Decrement allowance and increment used count in db
            remaining_allowance -= 1
            enriched_count += 1
            increment_enrichment_quota_used(portal_id, count=1, db_path=db_path)

        elif status == "failed":
            enriched_df.at[idx, "notes_structured"] = None
            enriched_df.at[idx, "enrichment_pending_review"] = False

            if "issues" in enriched_df.columns:
                existing_issues = enriched_df.at[idx, "issues"]
                if isinstance(existing_issues, list):
                    if "enrichment_failed" not in existing_issues:
                        enriched_df.at[idx, "issues"].append("enrichment_failed")
                elif isinstance(existing_issues, str):
                    issues_list = [i.strip() for i in existing_issues.split(",") if i.strip()]
                    if "enrichment_failed" not in issues_list:
                        issues_list.append("enrichment_failed")
                        enriched_df.at[idx, "issues"] = ", ".join(issues_list)
        else:
            enriched_df.at[idx, "enrichment_pending_review"] = False

    updated_quota = get_enrichment_quota(portal_id, db_path=db_path)
    message = (
        "Freemium quota reached (500/500 contacts). Please upgrade to the paid plan to enrich more lead notes."
        if updated_quota["is_exceeded"] or quota_hit
        else f"Successfully enriched {enriched_count} leads. {updated_quota['remaining']} leads remaining in freemium quota."
    )

    summary = {
        "portal_id": str(portal_id),
        "quota_limit": updated_quota["limit"],
        "quota_used": updated_quota["used"],
        "quota_remaining": updated_quota["remaining"],
        "enriched_this_run": enriched_count,
        "quota_exceeded": updated_quota["is_exceeded"] or quota_hit,
        "message": message,
    }

    return enriched_df, summary
