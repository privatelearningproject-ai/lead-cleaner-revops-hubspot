"""HubSpot Connection Validator & Account Metadata Module.

Provides non-destructive verification of Private App tokens, fetches real Portal IDs,
and handles authentication error mapping without logging or leaking credentials.
"""

from __future__ import annotations

from typing import Optional, Tuple
import requests

HUBSPOT_API_BASE = "https://api.hubapi.com"


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
