"""FastAPI Backend Server for Multi-Tenant HubSpot OAuth & Quota API.

Endpoints:
- GET /health: Health check endpoint
- GET /oauth/install: Generates state and redirects to HubSpot OAuth consent screen
- GET /oauth/callback: Handles OAuth code exchange, persists tokens, and returns success page
- GET /api/portal/{portal_id}/quota: Returns quota status and limits for a specific tenant
"""

from __future__ import annotations

import os
import secrets
import urllib.parse
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from cleaner.db import DEFAULT_DB_PATH, get_enrichment_quota, get_portal
from cleaner.hubspot import (
    ConfigurationError,
    HubSpotAPIError,
    exchange_authorization_code,
    get_oauth_credentials,
)

load_dotenv()

app = FastAPI(
    title="HubSpot RevOps Lead Cleaner API",
    description="Multi-tenant OAuth & Quota management server for HubSpot App Marketplace",
    version="1.0.0",
)

# In-memory store for OAuth state validation (or single session validation)
_OAUTH_STATES: set[str] = set()

HUBSPOT_AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
DEFAULT_SCOPES = "crm.objects.contacts.read crm.objects.contacts.write"


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check endpoint for container orchestrators and load balancers."""
    return {"status": "ok"}


@app.get("/oauth/install")
def oauth_install(
    scope: Optional[str] = Query(None, description="OAuth scopes requested"),
) -> RedirectResponse:
    """Initiates HubSpot OAuth 2.0 flow by redirecting to HubSpot's authorization page."""
    client_id, _, redirect_uri = get_oauth_credentials()
    if not client_id or not redirect_uri:
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: HUBSPOT_CLIENT_ID or HUBSPOT_REDIRECT_URI missing.",
        )

    state = secrets.token_urlsafe(24)
    _OAUTH_STATES.add(state)

    requested_scope = scope or os.environ.get("HUBSPOT_SCOPE", DEFAULT_SCOPES)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": requested_scope,
        "state": state,
    }
    url = f"{HUBSPOT_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@app.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
) -> HTMLResponse:
    """Handles the OAuth callback from HubSpot after the user grants permissions."""
    if error:
        detail = error_description or error
        return HTMLResponse(
            status_code=400,
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Installation Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h1 style="color: #e53e3e;">❌ Installation Denied or Failed</h1>
                <p>Error: {detail}</p>
                <p><a href="/oauth/install">Try again</a></p>
            </body>
            </html>
            """,
        )

    if not code:
        raise HTTPException(status_code=400, detail="Missing required authorization code")

    try:
        token_info = exchange_authorization_code(code)
        portal_id = token_info.get("portal_id", "unknown")
    except ConfigurationError as ce:
        raise HTTPException(status_code=500, detail=str(ce))
    except HubSpotAPIError as he:
        raise HTTPException(status_code=400, detail=f"HubSpot OAuth error: {he}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal token exchange error: {e}")

    # Return clean, user-friendly confirmation HTML page
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Lead Cleaner Installed Successfully</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: #f7fafc;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
            }}
            .card {{
                background: white;
                border-radius: 12px;
                padding: 40px;
                max-width: 480px;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
                text-align: center;
            }}
            .badge {{
                display: inline-block;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: 600;
                background-color: #ebf8ff;
                color: #2b6cb0;
                border-radius: 20px;
                margin: 15px 0;
            }}
            h1 {{ color: #2d3748; margin-bottom: 8px; font-size: 24px; }}
            p {{ color: #718096; line-height: 1.5; font-size: 15px; }}
            .btn {{
                display: inline-block;
                margin-top: 24px;
                background: #ff7a59;
                color: white;
                text-decoration: none;
                padding: 12px 28px;
                border-radius: 6px;
                font-weight: 600;
                font-size: 15px;
            }}
            .btn:hover {{ background: #e06040; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div style="font-size: 48px; margin-bottom: 12px;">🎉</div>
            <h1>Connected to HubSpot!</h1>
            <p>The Lead Cleaner RevOps App has been securely authorized for your account.</p>
            <div class="badge">Connected Portal ID: {portal_id}</div>
            <p>You can now return to the Lead Cleaner dashboard and process your contact lists.</p>
            <a href="/" class="btn">Open Lead Cleaner Dashboard</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/api/portal/{portal_id}/quota")
def get_portal_quota(portal_id: str) -> Dict[str, Any]:
    """Retrieve the LLM enrichment quota and usage status for a portal."""
    pid = str(portal_id).strip()
    db_path = os.environ.get("LEADS_AUDIT_DB_PATH", DEFAULT_DB_PATH)
    quota = get_enrichment_quota(pid, db_path=db_path)
    portal = get_portal(pid, db_path=db_path)

    return {
        "portal_id": pid,
        "is_registered": portal is not None,
        "plan_tier": quota["plan_tier"],
        "quota_limit": quota["limit"],
        "quota_used": quota["used"],
        "quota_remaining": quota["remaining"],
        "is_exceeded": quota["is_exceeded"],
    }
