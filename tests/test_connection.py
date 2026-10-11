"""Unit tests for hubspot/connection.py validation and error handling."""

from unittest.mock import MagicMock, patch
import requests
import pytest

from hubspot.connection import validate_and_connect


def test_validate_and_connect_empty_token():
    ok, portal, err = validate_and_connect("")
    assert not ok
    assert portal is None
    assert "cannot be empty" in err.lower()


def test_validate_and_connect_401_invalid():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {"message": "Invalid token"}

    secret_pat = "pat-na1-test-secret-token"
    with patch("requests.get", return_value=mock_resp):
        ok, portal, err = validate_and_connect(secret_pat)
        assert not ok
        assert portal is None
        assert "401" in err or "unauthorized" in err.lower()
        # Verify secret token is NOT leaked in error
        assert secret_pat not in err


def test_validate_and_connect_403_forbidden():
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.json.return_value = {"message": "Scope missing"}

    secret_pat = "pat-na1-insufficient-scopes"
    with patch("requests.get", return_value=mock_resp):
        ok, portal, err = validate_and_connect(secret_pat)
        assert not ok
        assert portal is None
        assert "403" in err or "scopes" in err.lower()
        assert secret_pat not in err


def test_validate_and_connect_success():
    resp_contacts = MagicMock()
    resp_contacts.status_code = 200
    resp_contacts.json.return_value = {"results": []}

    resp_account = MagicMock()
    resp_account.status_code = 200
    resp_account.json.return_value = {"portalId": 44112233}

    secret_pat = "pat-na1-valid-key"

    def side_effect(url, **kwargs):
        if "account-info" in url:
            return resp_account
        return resp_contacts

    with patch("requests.get", side_effect=side_effect):
        ok, portal, err = validate_and_connect(secret_pat)
        assert ok
        assert portal == "44112233"
        assert err is None


def test_validate_and_connect_timeout():
    secret_pat = "pat-na1-timeout-token"
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Connection timeout")):
        ok, portal, err = validate_and_connect(secret_pat)
        assert not ok
        assert portal is None
        assert "timed out" in err.lower()
        assert secret_pat not in err


def test_oauth_provider_get_auth_url():
    from hubspot.connection import HubSpotOAuthProvider

    provider = HubSpotOAuthProvider(
        client_id="test_client_id_123",
        client_secret="test_secret_456",
        redirect_uri="http://localhost:8501",
    )
    url = provider.get_auth_url(state="test_session")
    assert "https://app.hubspot.com/oauth/authorize" in url
    assert "client_id=test_client_id_123" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8501" in url
    assert "crm.objects.contacts.read" in url
    assert "state=test_session" in url


def test_oauth_provider_exchange_token_and_details():
    from hubspot.connection import HubSpotOAuthProvider, handle_oauth_callback

    provider = HubSpotOAuthProvider(
        client_id="cid",
        client_secret="csecret",
        redirect_uri="http://localhost:8501",
    )

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "oauth_access_token_xyz",
        "refresh_token": "oauth_refresh_token_abc",
        "expires_in": 1800,
    }

    mock_info_resp = MagicMock()
    mock_info_resp.status_code = 200
    mock_info_resp.json.return_value = {
        "hub_id": 99887766,
        "hub_domain": "revops-demo.hubspot.com",
        "user": "revops@company.in",
        "scopes": ["crm.objects.contacts.read"],
    }

    with patch("requests.post", return_value=mock_token_resp), patch("requests.get", return_value=mock_info_resp):
        token_data = provider.get_access_token("auth_code_123")
        assert token_data["access_token"] == "oauth_access_token_xyz"

        details = provider.get_portal_details("oauth_access_token_xyz")
        assert details["hubId"] == 99887766
        assert details["hubDomain"] == "revops-demo.hubspot.com"
        assert details["user"] == "revops@company.in"

        # Test handle_oauth_callback helper
        ok, res, err = handle_oauth_callback(
            code="auth_code_123",
            redirect_uri="http://localhost:8501",
            client_id="cid",
            client_secret="csecret",
        )
        assert ok
        assert res["portalId"] == "99887766"
        assert res["access_token"] == "oauth_access_token_xyz"
        assert err is None

