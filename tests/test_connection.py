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
