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
from pathlib import Path
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
DEFAULT_SCOPES = "crm.objects.contacts.read crm.objects.contacts.write crm.schemas.contacts.read"


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
    db_path = os.environ.get("LEADS_AUDIT_DB_PATH", DEFAULT_DB_PATH)
    try:
        from cleaner.db import save_oauth_state
        save_oauth_state(state, ttl_seconds=600, db_path=db_path)
    except Exception:
        _OAUTH_STATES.add(state)

    configured_scope = os.environ.get("HUBSPOT_SCOPES") or os.environ.get("HUBSPOT_SCOPE")
    requested_scope = scope or configured_scope or DEFAULT_SCOPES
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": requested_scope,
        "state": state,
    }
    url = f"{HUBSPOT_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@app.get("/oauth/callback")
def oauth_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    return_url: Optional[str] = Query(None, alias="returnUrl"),
    step: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
) -> Any:
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

    # Validate state parameter across workers with persistent TTL store
    if state:
        db_path = os.environ.get("LEADS_AUDIT_DB_PATH", DEFAULT_DB_PATH)
        is_valid_state = False
        try:
            from cleaner.db import consume_oauth_state
            is_valid_state = consume_oauth_state(state, db_path=db_path)
        except Exception:
            pass

        # Fallback to in-memory check if DB check did not pass
        if not is_valid_state:
            if state in _OAUTH_STATES:
                _OAUTH_STATES.discard(state)
                is_valid_state = True

        if not is_valid_state:
            return HTMLResponse(
                status_code=400,
                content="""
                <!DOCTYPE html>
                <html>
                <head><title>Authorization Failed</title></head>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: #e53e3e;">❌ Invalid or Expired OAuth State</h1>
                    <p>The authorization request could not be verified (possible CSRF or expired session).</p>
                    <p><a href="/oauth/install">Restart Authorization</a></p>
                </body>
                </html>
                """,
            )

    try:
        token_info = exchange_authorization_code(code)
        portal_id = token_info.get("portal_id", "unknown")
    except ConfigurationError as ce:
        raise HTTPException(status_code=500, detail=str(ce))
    except HubSpotAPIError as he:
        raise HTTPException(status_code=400, detail=f"HubSpot OAuth error: {he}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal token exchange error: {e}")

    # If returnUrl was provided by HubSpot (Seamless Install flow), redirect back to HubSpot
    if return_url:
        return RedirectResponse(url=return_url, status_code=302)

    app_url = os.environ.get("HUBSPOT_APP_URL", "/").strip()
    if not app_url:
        app_url = "/"

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
            <a href="{app_url}?portal_id={portal_id}" class="btn">Open Lead Cleaner Dashboard</a>
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


@app.post("/api/portal/{portal_id}/disconnect")
def disconnect_portal(portal_id: str) -> Dict[str, Any]:
    """Disconnect a portal and remove its stored OAuth tokens."""
    pid = str(portal_id).strip()
    db_path = os.environ.get("LEADS_AUDIT_DB_PATH", DEFAULT_DB_PATH)
    from cleaner.db import delete_portal
    deleted = delete_portal(pid, db_path=db_path)
    return {"portal_id": pid, "disconnected": deleted}


@app.get("/setup-guide", response_class=HTMLResponse)
def get_setup_guide() -> HTMLResponse:
    """Public setup documentation required for HubSpot Marketplace listing."""
    guide_path = Path(__file__).resolve().parent / "docs" / "setup-guide.html"
    if guide_path.exists():
        return HTMLResponse(content=guide_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Setup Guide</h1><p>Documentation coming soon.</p>")


@app.get("/privacy", response_class=HTMLResponse)
def get_privacy_policy() -> HTMLResponse:
    """Public privacy policy required for HubSpot Marketplace listing."""
    privacy_path = Path(__file__).resolve().parent / "docs" / "privacy-policy.html"
    if privacy_path.exists():
        return HTMLResponse(content=privacy_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Privacy Policy</h1><p>Privacy policy coming soon.</p>")


@app.get("/terms", response_class=HTMLResponse)
def get_terms_of_service() -> HTMLResponse:
    """Public terms of service required for HubSpot Marketplace listing."""
    terms_path = Path(__file__).resolve().parent / "docs" / "terms-of-service.html"
    if terms_path.exists():
        return HTMLResponse(content=terms_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Terms of Service</h1><p>Terms of service coming soon.</p>")


# =============================================================================
# Reverse Proxy to Internal Streamlit Instance (Render Single-Port Topology)
# =============================================================================

STREAMLIT_INTERNAL_PORT = int(os.environ.get("STREAMLIT_INTERNAL_PORT", "8501"))
STREAMLIT_INTERNAL_HOST = os.environ.get("STREAMLIT_INTERNAL_HOST", "127.0.0.1")
ENABLE_STREAMLIT_PROXY = os.environ.get("ENABLE_STREAMLIT_PROXY", "true").lower() in ("true", "1", "yes")

if ENABLE_STREAMLIT_PROXY:
    import asyncio
    import httpx
    import websockets
    from fastapi import Request, Response, WebSocket
    from fastapi.responses import StreamingResponse

    @app.websocket("/{path:path}")
    async def proxy_streamlit_websocket(client_ws: WebSocket, path: str):
        """Forward WebSocket traffic between browser and internal Streamlit process."""
        await client_ws.accept()
        query = str(client_ws.query_params)
        target_ws_url = f"ws://{STREAMLIT_INTERNAL_HOST}:{STREAMLIT_INTERNAL_PORT}/{path}"
        if query:
            target_ws_url += f"?{query}"

        try:
            async with websockets.connect(target_ws_url, ping_interval=20, ping_timeout=20) as server_ws:
                async def forward_to_server():
                    try:
                        while True:
                            msg = await client_ws.receive()
                            if "text" in msg:
                                await server_ws.send(msg["text"])
                            elif "bytes" in msg:
                                await server_ws.send(msg["bytes"])
                    except Exception:
                        pass

                async def forward_to_client():
                    try:
                        async for msg in server_ws:
                            if isinstance(msg, str):
                                await client_ws.send_text(msg)
                            else:
                                await client_ws.send_bytes(msg)
                    except Exception:
                        pass

                await asyncio.gather(forward_to_server(), forward_to_client(), return_exceptions=True)
        except Exception:
            pass
        finally:
            try:
                await client_ws.close()
            except Exception:
                pass

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"])
    async def proxy_streamlit_http(request: Request, path: str):
        """Forward all other HTTP routes to the internal Streamlit frontend."""
        query = str(request.url.query)
        target_http_url = f"http://{STREAMLIT_INTERNAL_HOST}:{STREAMLIT_INTERNAL_PORT}/{path}"
        if query:
            target_http_url += f"?{query}"

        # Filter hop-by-hop headers
        excluded_headers = {"host", "content-length", "connection", "transfer-encoding"}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded_headers}

        async with httpx.AsyncClient(timeout=30.0) as client:
            req_content = await request.body()
            try:
                resp = await client.request(
                    method=request.method,
                    url=target_http_url,
                    headers=headers,
                    content=req_content,
                    follow_redirects=False,
                )
            except Exception as exc:
                return Response(
                    content=f"<html><body><h2>Application Starting Up</h2><p>Streamlit is initializing... Please refresh in a moment. ({exc})</p></body></html>",
                    status_code=503,
                    media_type="text/html",
                )

            resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type"),
            )


