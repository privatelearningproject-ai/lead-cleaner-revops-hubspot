"""Tests for server.py FastAPI application endpoints."""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from cleaner.db import increment_enrichment_quota_used, save_portal
from server import app


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


def test_health_check(client):
    """Verify /health returns status: ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_oauth_install_redirects_to_hubspot(client, monkeypatch):
    """Verify /oauth/install generates state and redirects to HubSpot consent URL."""
    monkeypatch.setenv("HUBSPOT_CLIENT_ID", "test_client_id_123")
    monkeypatch.setenv("HUBSPOT_REDIRECT_URI", "https://app.test.com/oauth/callback")

    response = client.get("/oauth/install", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers.get("location")
    assert location is not None
    assert "https://app.hubspot.com/oauth/authorize" in location
    assert "client_id=test_client_id_123" in location
    assert "redirect_uri=https%3A%2F%2Fapp.test.com%2Foauth%2Fcallback" in location
    assert "state=" in location


def test_oauth_install_missing_config_returns_500(client, monkeypatch):
    """Verify /oauth/install returns 500 when client_id is missing."""
    monkeypatch.delenv("HUBSPOT_CLIENT_ID", raising=False)
    monkeypatch.delenv("HUBSPOT_REDIRECT_URI", raising=False)

    response = client.get("/oauth/install")
    assert response.status_code == 500
    assert "Server configuration error" in response.json()["detail"]


def test_oauth_callback_user_denied(client):
    """Verify /oauth/callback returns user-friendly error HTML when error query param is present."""
    response = client.get("/oauth/callback?error=access_denied&error_description=User+cancelled+install")
    assert response.status_code == 400
    assert "Installation Denied or Failed" in response.text
    assert "User cancelled install" in response.text


def test_oauth_callback_missing_code(client):
    """Verify /oauth/callback returns 400 if authorization code is missing."""
    response = client.get("/oauth/callback")
    assert response.status_code == 400
    assert "Missing required authorization code" in response.json()["detail"]


@patch("server.exchange_authorization_code")
def test_oauth_callback_success(mock_exchange, client):
    """Verify /oauth/callback executes code exchange and returns success page with portal_id."""
    from server import _OAUTH_STATES
    _OAUTH_STATES.add("some_state")

    mock_exchange.return_value = {
        "portal_id": "9876543",
        "access_token": "token_abc_123",
        "refresh_token": "refresh_xyz_456",
        "expires_in": 21600,
    }

    response = client.get("/oauth/callback?code=valid_hubspot_code&state=some_state")
    assert response.status_code == 200
    assert "Connected to HubSpot!" in response.text
    assert "Connected Portal ID: 9876543" in response.text
    mock_exchange.assert_called_once_with("valid_hubspot_code")


def test_oauth_callback_invalid_state(client):
    """Verify /oauth/callback rejects mismatched or replayed state tokens."""
    from server import _OAUTH_STATES
    _OAUTH_STATES.add("legitimate_state")

    response = client.get("/oauth/callback?code=some_code&state=forged_state")
    assert response.status_code == 400
    assert "Invalid or Expired OAuth State" in response.text


@patch("server.exchange_authorization_code")
def test_oauth_callback_with_return_url(mock_exchange, client):
    """Verify /oauth/callback redirects to returnUrl for HubSpot Seamless Install."""
    mock_exchange.return_value = {
        "portal_id": "9876543",
        "access_token": "token_abc_123",
        "refresh_token": "refresh_xyz_456",
        "expires_in": 21600,
    }

    response = client.get(
        "/oauth/callback?code=valid_hubspot_code&returnUrl=https://app.hubspot.com/install-success&step=finalize",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers.get("location") == "https://app.hubspot.com/install-success"


def test_portal_quota_api_endpoint(client, tmp_path, monkeypatch):
    """Verify /api/portal/{portal_id}/quota returns accurate quota and registration status."""
    db_path = tmp_path / "test_api_quota.db"
    monkeypatch.setenv("LEADS_AUDIT_DB_PATH", str(db_path))

    portal_id = "test_portal_88"

    # Save portal with 500 limit and 125 used
    save_portal(
        portal_id=portal_id,
        enrichment_quota_limit=500,
        plan_tier="free",
        db_path=db_path,
    )
    increment_enrichment_quota_used(portal_id, count=125, db_path=db_path)

    response = client.get(f"/api/portal/{portal_id}/quota")

    assert response.status_code == 200
    data = response.json()
    assert data["portal_id"] == portal_id
    assert data["is_registered"] is True
    assert data["quota_limit"] == 500
    assert data["quota_used"] == 125
    assert data["quota_remaining"] == 375
    assert data["is_exceeded"] is False


def test_public_documentation_endpoints(client):
    """Verify /setup-guide, /privacy, and /terms are live and return valid HTML."""
    for path in ["/setup-guide", "/privacy", "/terms"]:
        resp = client.get(path)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert len(resp.text) > 100


def test_persistent_oauth_state_lifecycle(tmp_path):
    """Verify save_oauth_state and consume_oauth_state single-use & TTL behavior."""
    from cleaner.db import consume_oauth_state, save_oauth_state
    db_path = tmp_path / "test_oauth_states.db"

    # 1. State saved and consumed
    save_oauth_state("state_one", ttl_seconds=60, db_path=db_path)
    assert consume_oauth_state("state_one", db_path=db_path) is True
    # 2. Cannot be consumed twice (replay attack protection)
    assert consume_oauth_state("state_one", db_path=db_path) is False

    # 3. Expired state cannot be consumed
    save_oauth_state("state_expired", ttl_seconds=-1, db_path=db_path)
    assert consume_oauth_state("state_expired", db_path=db_path) is False


def test_disconnect_portal_endpoint(client, tmp_path, monkeypatch):
    """Verify POST /api/portal/{portal_id}/disconnect deletes stored credentials."""
    db_path = tmp_path / "test_disconnect.db"
    monkeypatch.setenv("LEADS_AUDIT_DB_PATH", str(db_path))

    portal_id = "test_disconnect_portal_99"
    save_portal(
        portal_id=portal_id,
        access_token="tok_123",
        refresh_token="ref_456",
        db_path=db_path,
    )

    # Disconnect
    resp = client.post(f"/api/portal/{portal_id}/disconnect")
    assert resp.status_code == 200
    assert resp.json() == {"portal_id": portal_id, "disconnected": True}

    # Verify portal is removed
    from cleaner.db import get_portal
    assert get_portal(portal_id, db_path=db_path) is None


@patch("server.exchange_authorization_code")
def test_oauth_callback_api_error_returns_400(mock_exchange, client):
    """Verify /oauth/callback returns 400 when HubSpot API error occurs during token exchange."""
    from cleaner.hubspot import HubSpotAPIError
    from server import _OAUTH_STATES
    _OAUTH_STATES.add("valid_state_err")

    mock_exchange.side_effect = HubSpotAPIError("Bad request from HubSpot", status_code=400)

    response = client.get("/oauth/callback?code=bad_code&state=valid_state_err")
    assert response.status_code == 400
    assert "HubSpot OAuth error" in response.json()["detail"]

