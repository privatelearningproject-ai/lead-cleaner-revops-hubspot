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

