"""Tests for cleaner/enrich.py: Cloud LLM enrichment and multi-tenant quota engine."""

import json
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
import requests

from cleaner.db import (
    get_enrichment_quota,
    increment_enrichment_quota_used,
    save_portal,
)
from cleaner.enrich import (
    DEFAULT_FREEMIUM_QUOTA,
    DEFAULT_GEMINI_MODEL,
    enrich_dataframe,
    extract_lead_notes,
    get_gemini_api_key,
    get_grok_api_key,
    get_llm_provider,
    is_enrichment_enabled,
)


class TestConfigAndFlags:
    """Test environment variables and feature flag configuration."""

    def test_enrichment_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ENRICHMENT_ENABLED", raising=False)
        assert is_enrichment_enabled() is False
        assert is_enrichment_enabled(default=True) is True

    def test_enrichment_enabled_via_env(self, monkeypatch):
        for val in ["true", "True", "1", "yes", "Y"]:
            monkeypatch.setenv("ENRICHMENT_ENABLED", val)
            assert is_enrichment_enabled() is True

        for val in ["false", "False", "0", "no", "N"]:
            monkeypatch.setenv("ENRICHMENT_ENABLED", val)
            assert is_enrichment_enabled() is False

    def test_api_keys_and_provider_defaults(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GROK_API_KEY", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        assert get_gemini_api_key() is None
        assert get_grok_api_key() is None
        assert get_llm_provider() == "gemini"

        monkeypatch.setenv("GEMINI_API_KEY", "gemini_secret_123")
        monkeypatch.setenv("GROK_API_KEY", "grok_secret_456")
        monkeypatch.setenv("LLM_PROVIDER", "grok")

        assert get_gemini_api_key() == "gemini_secret_123"
        assert get_grok_api_key() == "grok_secret_456"
        assert get_llm_provider() == "grok"


class TestExtractLeadNotesCloud:
    """Test Cloud LLM extraction (Gemini & Grok) with mocks."""

    def test_empty_or_whitespace_notes_bypasses_http(self):
        with patch("cleaner.enrich.requests.post") as mock_post:
            for val in [None, "", "   ", "\n\t", float("nan")]:
                res = extract_lead_notes(val, api_key="dummy_key")
                assert res["status"] == "skipped"
                assert res["budget"] is None
                assert res["product_interest"] is None
                assert res["city"] is None
            mock_post.assert_not_called()

    @patch("cleaner.enrich.requests.post")
    def test_successful_gemini_extraction(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "budget": "2.5 Lakhs",
                                        "product_interest": "commercial ovens",
                                        "city": "Delhi",
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        note = "Looking for commercial ovens in Delhi, budget approx 2.5 lakhs"
        res = extract_lead_notes(note, api_key="test_gemini_key", provider="gemini")

        assert res["status"] == "success"
        assert res["budget"] == "2.5 Lakhs"
        assert res["product_interest"] == "commercial ovens"
        assert res["city"] == "Delhi"
        assert res["error"] is None

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "generativelanguage.googleapis.com" in url
        assert "key=test_gemini_key" in url

    @patch("cleaner.enrich.requests.post")
    def test_gemini_markdown_wrapped_json(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        markdown_text = (
            "```json\n"
            "{\n  \"budget\": \"50,000 INR\",\n  \"product_interest\": \"CRM software\",\n  \"city\": \"Mumbai\"\n}\n"
            "```"
        )
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": markdown_text}]}}]
        }
        mock_post.return_value = mock_response

        res = extract_lead_notes("Need CRM for Mumbai office, budget 50,000 INR", api_key="key")
        assert res["status"] == "success"
        assert res["budget"] == "50,000 INR"
        assert res["product_interest"] == "CRM software"
        assert res["city"] == "Mumbai"

    @patch("cleaner.enrich.requests.post")
    def test_grok_provider_extraction(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "budget": "10 Lakhs",
                                "product_interest": "ERP",
                                "city": "Bengaluru",
                            }
                        )
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        res = extract_lead_notes(
            "ERP software required in Bengaluru, 10 Lakhs budget",
            api_key="grok_key",
            provider="grok",
        )
        assert res["status"] == "success"
        assert res["budget"] == "10 Lakhs"
        assert res["city"] == "Bengaluru"

    @patch("cleaner.enrich.requests.post")
    def test_malformed_json_response(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "I am unable to find any details."}]}}]
        }
        mock_post.return_value = mock_response

        res = extract_lead_notes("Random notes", api_key="key")
        assert res["status"] == "failed"
        assert "Failed to parse JSON" in res["error"]

    @patch("cleaner.enrich.requests.post")
    def test_timeout_handled_gracefully(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

        res = extract_lead_notes("Large note", api_key="key", timeout=10)
        assert res["status"] == "failed"
        assert "timed out" in res["error"].lower()

    def test_missing_api_key_fails_gracefully(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        res = extract_lead_notes("Some note", api_key=None, provider="gemini")
        assert res["status"] == "failed"
        assert "GEMINI_API_KEY missing" in res["error"]


class TestEnrichDataframeAndQuotaGuard:
    """Test multi-tenant quota enforcement and batch capping."""

    def test_disabled_by_default_zero_http_calls(self, tmp_path):
        db_path = tmp_path / "test_disabled.db"
        df = pd.DataFrame(
            [
                {"first_name": "Aarav", "notes_raw": "Budget 5 Lakhs for ERP"},
                {"first_name": "Priya", "notes_raw": "Looking for CRM"},
            ]
        )

        with patch("cleaner.enrich.requests.post") as mock_post:
            result_df, summary = enrich_dataframe(df, enabled=False, db_path=db_path)
            mock_post.assert_not_called()

        assert "notes_structured" in result_df.columns
        assert "enrichment_status" in result_df.columns
        assert bool((result_df["enrichment_pending_review"] == False).all()) is True
        assert summary["enriched_this_run"] == 0

    @patch("cleaner.enrich.extract_lead_notes")
    def test_quota_enforcement_stops_at_limit(self, mock_extract, tmp_path):
        """When tenant has already reached 500 contacts, zero LLM calls should be made."""
        db_path = tmp_path / "test_quota.db"
        portal_id = "portal_maxed_out"

        # Create portal with 500 / 500 quota already used
        save_portal(
            portal_id=portal_id,
            enrichment_quota_limit=500,
            db_path=db_path,
        )
        increment_enrichment_quota_used(portal_id, count=500, db_path=db_path)

        df = pd.DataFrame(
            [
                {"first_name": "Aarav", "notes_raw": "Looking for 10 licenses"},
                {"first_name": "Priya", "notes_raw": "Budget 2 Lakhs"},
            ]
        )

        enriched_df, summary = enrich_dataframe(
            df,
            enabled=True,
            portal_id=portal_id,
            db_path=db_path,
        )

        # Zero LLM calls made!
        mock_extract.assert_not_called()
        assert summary["quota_exceeded"] is True
        assert summary["quota_remaining"] == 0
        assert summary["enriched_this_run"] == 0
        assert "Freemium quota reached" in summary["message"]

        # Rows tagged as quota_exceeded
        assert (enriched_df["enrichment_status"] == "quota_exceeded").all()
        assert (enriched_df["enrichment_pending_review"] == False).all()

    @patch("cleaner.enrich.extract_lead_notes")
    def test_batch_capping_when_batch_exceeds_remaining_quota(self, mock_extract, tmp_path):
        """If tenant has 2 remaining quota, but batch has 5 records:

        Only enrich the first 2, and halt/tag the remaining 3 as quota_exceeded.
        """
        db_path = tmp_path / "test_batch_cap.db"
        portal_id = "portal_near_limit"

        # 498 used out of 500 -> 2 remaining
        save_portal(
            portal_id=portal_id,
            enrichment_quota_limit=500,
            db_path=db_path,
        )
        increment_enrichment_quota_used(portal_id, count=498, db_path=db_path)

        mock_extract.return_value = {
            "budget": "5 Lakhs",
            "product_interest": "Machinery",
            "city": "Mumbai",
            "status": "success",
            "error": None,
        }

        # 5 rows
        df = pd.DataFrame(
            [{"first_name": f"Lead_{i}", "notes_raw": f"Note {i}"} for i in range(5)]
        )

        enriched_df, summary = enrich_dataframe(
            df,
            enabled=True,
            portal_id=portal_id,
            db_path=db_path,
        )

        # Only 2 LLM calls should have occurred
        assert mock_extract.call_count == 2
        assert summary["enriched_this_run"] == 2
        assert summary["quota_remaining"] == 0
        assert summary["quota_exceeded"] is True

        # First 2 rows are success, remaining 3 rows are quota_exceeded
        assert enriched_df.at[0, "enrichment_status"] == "success"
        assert enriched_df.at[1, "enrichment_status"] == "success"
        assert bool(enriched_df.at[0, "enrichment_pending_review"]) is True
        assert bool(enriched_df.at[1, "enrichment_pending_review"]) is True

        assert enriched_df.at[2, "enrichment_status"] == "quota_exceeded"
        assert enriched_df.at[3, "enrichment_status"] == "quota_exceeded"
        assert enriched_df.at[4, "enrichment_status"] == "quota_exceeded"
        assert bool(enriched_df.at[2, "enrichment_pending_review"]) is False
