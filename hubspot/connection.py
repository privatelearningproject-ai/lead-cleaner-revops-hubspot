"""HubSpot Connection Validator, Account Metadata & OAuth 2.0 Module.

Implements the complete HubSpot OAuth 2.0 Provider flow:
1. get_auth_url: Generates the HubSpot OAuth consent authorization URL.
2. get_access_token: Exchanges the authorization code for access & refresh tokens.
3. refresh_access_token: Refreshes an expired access token using the refresh token.
4. get_portal_details: Fetches connected portal ID (hub_id), domain, user, and scopes.
5. validate_and_connect: Lightweight verification for HubSpot Private App Tokens (PAT).
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from dotenv import load_dotenv

from cleaner.db import DEFAULT_DB_PATH, save_portal

HUBSPOT_API_BASE = "https://api.hubapi.com"
HUBSPOT_AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
HUBSPOT_OAUTH_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"

DEFAULT_OAUTH_SCOPES = [
    "oauth",
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.companies.read",
    "crm.objects.companies.write",
    "crm.objects.deals.read",
    "crm.objects.deals.write",
]


class HubSpotOAuthProvider:
    """HubSpot OAuth 2.0 Provider service for initiating and completing account authentication."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ):
        load_dotenv()
        self.client_id = (client_id or os.environ.get("HUBSPOT_CLIENT_ID") or "").strip()
        self.client_secret = (client_secret or os.environ.get("HUBSPOT_CLIENT_SECRET") or "").strip()
        self.redirect_uri = (redirect_uri or os.environ.get("HUBSPOT_REDIRECT_URI") or "").strip()

    def get_auth_url(
        self,
        state: str = "streamlit_app",
        redirect_uri: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> str:
        """Generates the HubSpot OAuth 2.0 authorization URL."""
        c_id = self.client_id
        r_uri = redirect_uri or self.redirect_uri

        if not c_id:
            raise ValueError("[HUBSPOT_CONFIG_ERROR]: Missing HUBSPOT_CLIENT_ID.")
        if not r_uri:
            raise ValueError("[HUBSPOT_CONFIG_ERROR]: Missing HUBSPOT_REDIRECT_URI.")

        scope_list = scopes or DEFAULT_OAUTH_SCOPES
        scope_str = " ".join(scope_list)

        params = {
            "client_id": c_id,
            "redirect_uri": r_uri,
            "scope": scope_str,
        }
        if state:
            params["state"] = state.strip()

        return f"{HUBSPOT_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def get_access_token(
        self,
        code: str,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Exchanges the temporary authorization code for OAuth access and refresh tokens."""
        c_id = self.client_id
        c_secret = self.client_secret
        r_uri = redirect_uri or self.redirect_uri

        if not (c_id and c_secret and r_uri):
            raise ValueError("[HUBSPOT_CONFIG_ERROR]: Cannot exchange token due to missing client credentials or redirect_uri.")

        payload = {
            "grant_type": "authorization_code",
            "client_id": c_id,
            "client_secret": c_secret,
            "redirect_uri": r_uri,
            "code": code.strip(),
        }

        resp = requests.post(
            HUBSPOT_OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Failed to exchange authorization code: HTTP {resp.status_code} - {resp.text}")

        return resp.json()

    def refresh_access_token(
        self,
        refresh_token: str,
    ) -> Dict[str, Any]:
        """Refreshes an expired access token using the refresh token."""
        c_id = self.client_id
        c_secret = self.client_secret

        if not (c_id and c_secret):
            raise ValueError("[HUBSPOT_CONFIG_ERROR]: Missing credentials for token refresh.")

        payload = {
            "grant_type": "refresh_token",
            "client_id": c_id,
            "client_secret": c_secret,
            "refresh_token": refresh_token.strip(),
        }

        resp = requests.post(
            HUBSPOT_OAUTH_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Failed to refresh HubSpot token: HTTP {resp.status_code} - {resp.text}")

        return resp.json()

    def get_portal_details(self, access_token: str) -> Dict[str, Any]:
        """Retrieves Portal ID and metadata for the authenticated connection."""
        resp = requests.get(
            f"{HUBSPOT_API_BASE}/oauth/v1/access-tokens/{access_token.strip()}",
            timeout=8,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch token metadata: HTTP {resp.status_code} - {resp.text}")

        data = resp.json()
        return {
            "hubId": data.get("hub_id"),
            "hub_id": data.get("hub_id"),
            "hubDomain": data.get("hub_domain"),
            "hub_domain": data.get("hub_domain"),
            "user": data.get("user"),
            "scopes": data.get("scopes", []),
            "app_id": data.get("app_id"),
        }


def handle_oauth_callback(
    code: str,
    redirect_uri: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Complete the OAuth exchange and fetch portal details.

    Returns:
        (success, details_dict, error_message)
    """
    try:
        provider = HubSpotOAuthProvider(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        token_data = provider.get_access_token(code, redirect_uri=redirect_uri)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 21600)

        if not access_token:
            return False, None, "No access token returned from HubSpot."

        portal_details = provider.get_portal_details(access_token)
        portal_id = str(portal_details.get("hubId") or portal_details.get("hub_id") or "connected_portal")

        # Save connection to SQLite for persistent multi-tenant lookup
        try:
            expires_at = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc)
            save_portal(
                portal_id=portal_id,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
            )
        except Exception:
            pass

        return True, {
            "portalId": portal_id,
            "hubId": portal_id,
            "hubDomain": portal_details.get("hubDomain"),
            "user": portal_details.get("user"),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "scopes": portal_details.get("scopes", []),
        }, None

    except Exception as e:
        return False, None, str(e)


def validate_and_connect(token: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Validate a HubSpot Private App token and fetch connected Portal ID.

    Returns:
        (is_connected, portal_id, error_message)
    """
    cleaned_token = str(token or "").strip()
    if not cleaned_token:
        return False, None, "Token cannot be empty."

    headers = {
        "Authorization": f"Bearer {cleaned_token}",
        "Content-Type": "application/json",
    }

    try:
        # Step 1: Lightweight validation call on contacts endpoint
        contacts_resp = requests.get(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts",
            headers=headers,
            params={"limit": 1},
            timeout=8,
        )

        if contacts_resp.status_code == 401:
            return False, None, "Invalid or expired HubSpot Private App Token (401 Unauthorized)."
        if contacts_resp.status_code == 403:
            return False, None, "Insufficient scopes (403 Forbidden). Token requires 'crm.objects.contacts.read'."
        if contacts_resp.status_code != 200:
            return False, None, f"HubSpot API error (HTTP {contacts_resp.status_code})."

        # Step 2: Fetch real Portal ID from account-info endpoint
        info_resp = requests.get(
            f"{HUBSPOT_API_BASE}/account-info/v3/details",
            headers=headers,
            timeout=8,
        )

        portal_id = None
        if info_resp.status_code == 200:
            info_data = info_resp.json()
            raw_portal = info_data.get("portalId") or info_data.get("portal_id") or info_data.get("hubId")
            if raw_portal:
                portal_id = str(raw_portal)

        # Fallback if account-info endpoint doesn't return portalId
        if not portal_id:
            portal_id = "connected_portal"

        return True, portal_id, None

    except requests.exceptions.Timeout:
        return False, None, "Connection timed out while contacting HubSpot API."
    except requests.exceptions.RequestException:
        return False, None, "Network error: Unable to reach HubSpot API."
    except Exception as e:
        return False, None, f"Connection validation failed: {type(e).__name__}"
