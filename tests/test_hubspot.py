"""Unit tests for cleaner/hubspot.py HubSpot CRM v3 API integration.

Uses unittest.mock to simulate API responses without network calls:
- Search by email hit -> non-destructive update
- Search by email miss -> search by phone hit -> non-destructive update
- Search miss on both -> create new contact
- Dry-run mode safety -> no live mutations, actions marked DRY_RUN_*
- Consent missing -> marketing exclusion flags set
- HTTP 429 rate limit backoff retry simulation
- Missing token exception handling
- Batch sync_cleaned_leads execution
"""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
import requests

from cleaner.hubspot import (
    ConfigurationError,
    HubSpotAPIError,
    HubSpotClient,
)


class TestHubSpotClientInit:
    def test_missing_token_raises_configuration_error_in_live_mode(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("cleaner.hubspot.get_token_from_env", return_value=None):
                with pytest.raises(ConfigurationError):
                    HubSpotClient(dry_run=False)

    def test_missing_token_allowed_in_dry_run_mode(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("cleaner.hubspot.get_token_from_env", return_value=None):
                client = HubSpotClient(dry_run=True)
                assert client.dry_run is True
                assert client.token == "mock_dry_run_token"


class TestHubSpotSearchAndUpsert:
    def test_search_by_email_hit_and_non_destructive_update(self):
        mock_session = MagicMock(spec=requests.Session())

        # Mock Search response: Contact found by email with existing firstname & city
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.content = b'{"results": [{"id": "101", "properties": {"firstname": "ExistingAarav", "city": "Mumbai", "company": ""}}]}'
        search_resp.json.return_value = {
            "results": [
                {
                    "id": "101",
                    "properties": {
                        "firstname": "ExistingAarav",
                        "city": "Mumbai",
                        "company": "",  # Empty on HubSpot
                    },
                }
            ]
        }

        # Mock Patch response
        patch_resp = MagicMock()
        patch_resp.status_code = 200
        patch_resp.content = b'{"id": "101", "properties": {"company": "NewCo"}}'
        patch_resp.json.return_value = {"id": "101", "properties": {"company": "NewCo"}}

        mock_session.request.side_effect = [search_resp, patch_resp]

        client = HubSpotClient(token="test_token", dry_run=False, session=mock_session)

        lead = {
            "first_name": "AaravChanged",
            "last_name": "Sharma",
            "email": "aarav@test.com",
            "phone": "+919820012345",
            "company": "NewCo",
            "city": "Pune",  # Different city, but existing is 'Mumbai'
            "consent_source": "Website",
        }

        result = client.upsert_contact(lead)

        assert result["action"] == "UPDATE"
        assert result["contact_id"] == "101"
        updated_props = result["updated_properties"]

        # Non-destructive check:
        # 'firstname' was already 'ExistingAarav' -> NOT updated!
        # 'city' was already 'Mumbai' -> NOT updated!
        # 'company' was empty -> UPDATED to 'NewCo'!
        assert "firstname" not in updated_props
        assert "city" not in updated_props
        assert updated_props["company"] == "NewCo"
        assert updated_props["lastname"] == "Sharma"
        assert updated_props["phone"] == "+919820012345"

    def test_search_by_email_miss_then_phone_hit(self):
        mock_session = MagicMock(spec=requests.Session())

        # 1st request (search by email) -> empty results
        email_search_resp = MagicMock()
        email_search_resp.status_code = 200
        email_search_resp.json.return_value = {"results": []}

        # 2nd request (search by phone) -> found contact 202
        phone_search_resp = MagicMock()
        phone_search_resp.status_code = 200
        phone_search_resp.json.return_value = {
            "results": [
                {
                    "id": "202",
                    "properties": {
                        "phone": "+919876543210",
                        "firstname": "Priya",
                        "email": "",  # Empty email on HubSpot
                    },
                }
            ]
        }

        # 3rd request (patch contact 202)
        patch_resp = MagicMock()
        patch_resp.status_code = 200
        patch_resp.json.return_value = {"id": "202"}

        mock_session.request.side_effect = [email_search_resp, phone_search_resp, patch_resp]

        client = HubSpotClient(token="test_token", dry_run=False, session=mock_session)

        lead = {
            "first_name": "Priya",
            "last_name": "Patel",
            "email": "priya.new@gmail.com",
            "phone": "+919876543210",
            "consent_source": "WhatsApp",
        }

        result = client.upsert_contact(lead)

        assert result["action"] == "UPDATE"
        assert result["contact_id"] == "202"
        assert result["updated_properties"]["email"] == "priya.new@gmail.com"

    def test_search_miss_on_both_creates_new_contact(self):
        mock_session = MagicMock(spec=requests.Session())

        # Email search -> empty
        email_search = MagicMock()
        email_search.status_code = 200
        email_search.json.return_value = {"results": []}

        # Phone search -> empty
        phone_search = MagicMock()
        phone_search.status_code = 200
        phone_search.json.return_value = {"results": []}

        # Create contact POST
        create_resp = MagicMock()
        create_resp.status_code = 201
        create_resp.json.return_value = {"id": "303"}

        mock_session.request.side_effect = [email_search, phone_search, create_resp]

        client = HubSpotClient(token="test_token", dry_run=False, session=mock_session)

        lead = {
            "first_name": "Vikram",
            "last_name": "Malhotra",
            "email": "vikram@ventures.com",
            "phone": "+918123456789",
            "city": "Bengaluru",
            "source": "messy_leads.csv",
            "consent_source": "Cold Call",
        }

        result = client.upsert_contact(lead)

        assert result["action"] == "CREATE"
        assert result["contact_id"] == "303"
        assert result["updated_properties"]["firstname"] == "Vikram"
        assert result["updated_properties"]["lead_source"] == "messy_leads.csv"


class TestDryRunSafetyMode:
    def test_dry_run_create_simulation_no_network_post(self):
        mock_session = MagicMock(spec=requests.Session())
        client = HubSpotClient(token="test_token", dry_run=True, session=mock_session)

        # Mock find_contact to return None (no existing contact)
        with patch.object(client, "find_contact", return_value=None):
            lead = {
                "first_name": "Aarav",
                "last_name": "Sharma",
                "email": "aarav@test.com",
                "phone": "+919820012345",
                "city": "Mumbai",
            }
            result = client.upsert_contact(lead)

            assert result["action"] == "DRY_RUN_CREATE"
            assert result["dry_run"] is True
            assert "simulated_" in result["contact_id"]
            # Verify no live HTTP network mutations made by session
            assert mock_session.request.call_count == 0

    def test_dry_run_update_simulation_no_network_patch(self):
        mock_session = MagicMock(spec=requests.Session())
        client = HubSpotClient(token="test_token", dry_run=True, session=mock_session)

        existing = {
            "id": "existing_999",
            "properties": {
                "firstname": "Aarav",
                "city": "",
                "lead_source": "existing_source",
                "consent_missing": "false",
                "hs_email_optout": "false",
            },
        }


        with patch.object(client, "find_contact", return_value=existing):
            lead = {
                "first_name": "Aarav",
                "city": "Mumbai",
            }
            result = client.upsert_contact(lead)

            assert result["action"] == "DRY_RUN_UPDATE"
            assert result["contact_id"] == "existing_999"
            assert result["updated_properties"] == {"city": "Mumbai"}
            assert mock_session.request.call_count == 0


class TestMarketingConsentExclusion:
    def test_consent_missing_sets_marketing_exclusion_flags(self):
        client = HubSpotClient(token="test_token", dry_run=True)

        # Lead with missing consent
        lead = {
            "first_name": "Rajesh",
            "last_name": "Kumar",
            "email": "rajesh@test.com",
            "consent_source": "",
            "issues": ["consent_missing"],
        }

        props = client._prepare_contact_properties(lead)

        assert props["consent_missing"] == "true"
        assert props["hs_email_optout"] == "true"
        assert "lead_consent_source" not in props

    def test_consent_present_records_consent_source(self):
        client = HubSpotClient(token="test_token", dry_run=True)

        lead = {
            "first_name": "Sunita",
            "last_name": "Rao",
            "email": "sunita@test.com",
            "consent_source": "Organic Search",
            "issues": [],
        }

        props = client._prepare_contact_properties(lead)

        assert props["consent_missing"] == "false"
        assert props["lead_consent_source"] == "Organic Search"
        assert "hs_email_optout" not in props


class TestRateLimitingAndBackoff:
    def test_rate_limit_429_backoff_and_recovery(self):
        mock_session = MagicMock(spec=requests.Session())

        # 1st attempt: 429 Too Many Requests with Retry-After header
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "0.01"}
        resp_429.text = "Rate limit reached"

        # 2nd attempt: 200 OK
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.content = b'{"results": []}'
        resp_200.json.return_value = {"results": []}

        mock_session.request.side_effect = [resp_429, resp_200]

        client = HubSpotClient(
            token="test_token",
            dry_run=False,
            session=mock_session,
            max_retries=2,
            backoff_factor=0.01,
        )

        with patch("time.sleep", return_value=None) as mock_sleep:
            res = client._request("GET", "/crm/v3/objects/contacts")
            assert res == {"results": []}
            assert mock_sleep.called
            assert mock_session.request.call_count == 2


class TestBatchSyncCleanedLeads:
    def test_sync_cleaned_leads_batch(self):
        client = HubSpotClient(token="test_token", dry_run=True)

        leads_df = pd.DataFrame(
            [
                {"first_name": "Aarav", "email": "aarav@test.com", "phone": "+919820012345"},
                {"first_name": "Priya", "email": "priya@test.com", "phone": "+919876543210"},
            ]
        )

        batch_result = client.sync_cleaned_leads(leads_df, source_name="test_batch.csv")

        assert batch_result["total_processed"] == 2
        assert batch_result["counts"]["created"] == 2
        assert batch_result["dry_run"] is True
        assert len(batch_result["results"]) == 2


class TestMultiTenantOAuth:
    def test_portal_token_resolution_from_db(self, tmp_path):
        from cleaner.db import save_portal
        db_path = tmp_path / "test_tenant.db"
        portal_id = "portal_12345"

        save_portal(
            portal_id=portal_id,
            access_token="tenant_access_token_xyz",
            db_path=db_path,
        )

        client = HubSpotClient(portal_id=portal_id, dry_run=True, db_path=db_path)
        assert client.token == "tenant_access_token_xyz"
        assert client.portal_id == portal_id

    def test_automatic_token_refresh_when_expired(self, tmp_path):
        from datetime import datetime, timedelta, timezone
        from cleaner.db import get_portal, save_portal
        from cleaner.hubspot import refresh_portal_token

        db_path = tmp_path / "test_refresh.db"
        portal_id = "portal_exp_999"

        # Past expiration date
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        save_portal(
            portal_id=portal_id,
            access_token="old_expired_token",
            refresh_token="valid_refresh_token",
            token_expires_at=expired_time,
            db_path=db_path,
        )

        mock_refresh_resp = MagicMock()
        mock_refresh_resp.status_code = 200
        mock_refresh_resp.json.return_value = {
            "access_token": "new_refreshed_token_abc",
            "refresh_token": "new_refresh_token_def",
            "expires_in": 3600,
        }

        with patch("cleaner.hubspot.requests.post", return_value=mock_refresh_resp):
            with patch.dict("os.environ", {"HUBSPOT_CLIENT_ID": "client_id", "HUBSPOT_CLIENT_SECRET": "client_secret"}):
                client = HubSpotClient(portal_id=portal_id, dry_run=True, db_path=db_path)
                assert client.token == "new_refreshed_token_abc"

                # Verify updated in database
                portal = get_portal(portal_id, db_path=db_path)
                assert portal["access_token"] == "new_refreshed_token_abc"
                assert portal["refresh_token"] == "new_refresh_token_def"

    def test_authorization_code_exchange(self, tmp_path):
        from cleaner.db import get_portal
        from cleaner.hubspot import exchange_authorization_code

        db_path = tmp_path / "test_exchange.db"
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "oauth_token_123",
            "refresh_token": "oauth_refresh_456",
            "expires_in": 7200,
        }

        mock_info_resp = MagicMock()
        mock_info_resp.status_code = 200
        mock_info_resp.json.return_value = {"hub_id": "78910"}

        with patch("cleaner.hubspot.requests.post", return_value=mock_token_resp):
            with patch("cleaner.hubspot.requests.get", return_value=mock_info_resp):
                with patch.dict(
                    "os.environ",
                    {
                        "HUBSPOT_CLIENT_ID": "cid",
                        "HUBSPOT_CLIENT_SECRET": "csecret",
                        "HUBSPOT_REDIRECT_URI": "https://callback.com",
                    },
                ):
                    res = exchange_authorization_code("sample_auth_code", db_path=db_path)
                    assert res["portal_id"] == "78910"
                    assert res["access_token"] == "oauth_token_123"

                    portal = get_portal("78910", db_path=db_path)
                    assert portal is not None
                    assert portal["access_token"] == "oauth_token_123"


class TestFetchContactsAndAssociations:
    def test_fetch_contacts_with_pagination(self):
        client = HubSpotClient(token="test_token", dry_run=False)

        page1_resp = {
            "results": [
                {
                    "id": "1",
                    "properties": {"firstname": "Aarav", "lastname": "Sharma", "email": "aarav@test.com"},
                    "associations": {"companies": {"results": [{"id": "comp_101"}]}},
                }
            ],
            "paging": {"next": {"after": "page2_cursor"}},
        }
        page2_resp = {
            "results": [
                {
                    "id": "2",
                    "properties": {"firstname": "Priya", "lastname": "Patel", "email": "priya@test.com"},
                    "associations": {"deals": {"results": [{"id": "deal_202"}]}},
                }
            ],
        }

        with patch.object(client, "_request", side_effect=[page1_resp, page2_resp]) as mock_req:
            contacts = client.fetch_contacts(max_records=2)
            assert len(contacts) == 2
            assert contacts[0]["id"] == "1"
            assert contacts[1]["id"] == "2"
            assert mock_req.call_count == 2

    def test_contacts_to_dataframe_canonical_mapping(self):
        client = HubSpotClient(token="test_token", dry_run=True)
        raw_contacts = [
            {
                "id": "555",
                "properties": {
                    "firstname": "Vikram",
                    "lastname": "Malhotra",
                    "email": "vikram@test.com",
                    "phone": "9812345678",
                    "company": "Ventures Ltd",
                    "city": "Bengaluru",
                    "state": "Karnataka",
                    "zip": "560001",
                    "lead_consent_source": "IndiaMART",
                },
                "associations": {
                    "companies": {"results": [{"id": "comp_900"}]},
                    "deals": {"results": [{"id": "deal_800"}]},
                },
            }
        ]

        df = client.contacts_to_dataframe(raw_contacts)
        assert len(df) == 1
        assert df.at[0, "hubspot_contact_id"] == "555"
        assert df.at[0, "first_name"] == "Vikram"
        assert df.at[0, "last_name"] == "Malhotra"
        assert df.at[0, "email"] == "vikram@test.com"
        assert df.at[0, "phone"] == "9812345678"
        assert df.at[0, "city"] == "Bengaluru"
        assert df.at[0, "state"] == "Karnataka"
        assert df.at[0, "pin_code"] == "560001"
        assert df.at[0, "consent_source"] == "IndiaMART"
        assert df.at[0, "hubspot_associated_company_id"] == "comp_900"
        assert df.at[0, "hubspot_associated_deal_ids"] == ["deal_800"]
        # Raw preservation
        assert df.at[0, "raw_firstname"] == "Vikram"
        assert df.at[0, "raw_id"] == "555"


class TestContactMerging:
    def test_merge_contacts_payload_and_url(self):
        client = HubSpotClient(token="test_token", dry_run=False)

        mock_resp = {"status": "success", "primaryObjectId": "101", "objectIdToMerge": "102"}
        with patch.object(client, "_request", return_value=mock_resp) as mock_req:
            res = client.merge_contacts("101", "102")
            assert res["status"] == "success"
            assert res["primaryObjectId"] == "101"
            assert res["objectIdToMerge"] == "102"
            mock_req.assert_called_once_with(
                "POST",
                "/crm/v3/objects/contacts/merge",
                json_payload={"primaryObjectId": "101", "objectIdToMerge": "102"},
            )

    def test_merge_contacts_dry_run_no_network_call(self):
        client = HubSpotClient(token="test_token", dry_run=True)

        with patch.object(client, "_request") as mock_req:
            res = client.merge_contacts("101", "102")
            assert res["status"] == "dry_run"
            assert res["action"] == "DRY_RUN_MERGE"
            assert res["primaryObjectId"] == "101"
            assert res["objectIdToMerge"] == "102"
            mock_req.assert_not_called()

    def test_merge_contacts_api_error_handling(self):
        client = HubSpotClient(token="test_token", dry_run=False)

        error_exception = HubSpotAPIError("Contact 102 was already merged or deleted", status_code=404)
        with patch.object(client, "_request", side_effect=error_exception):
            res = client.merge_contacts("101", "102")
            assert res["status"] == "failed"
            assert res["status_code"] == 404
            assert "Contact 102 was already merged" in res["error"]

    def test_merge_duplicate_clusters_batch(self):
        client = HubSpotClient(token="test_token", dry_run=True)

        clusters = [
            {
                "cluster_id": "cluster_1",
                "primary_contact_id": "101",
                "secondary_contact_ids": ["102", "103"],
            },
            {
                "cluster_id": "cluster_2",
                "primary_contact_id": "201",
                "secondary_contact_ids": ["202"],
            },
        ]

        results = client.merge_duplicate_clusters(clusters)
        assert len(results) == 3  # 102->101, 103->101, 202->201
        assert results[0]["primaryObjectId"] == "101"
        assert results[0]["objectIdToMerge"] == "102"
        assert results[1]["objectIdToMerge"] == "103"
        assert results[2]["primaryObjectId"] == "201"
        assert results[2]["objectIdToMerge"] == "202"
        assert all(r["status"] == "dry_run" for r in results)



