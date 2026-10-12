# Lead Cleaner — Engineering, Governance & Testing Guide

## 1. Project Architecture & Local Topology
The **Lead Cleaner** application operates as a multi-tenant HubSpot CRM data quality and RevOps pipeline engine consisting of two services running in tandem:
1. **FastAPI Backend (port 8000):**
   - Handles multi-tenant OAuth 2.0 installation (`GET /oauth/install`), state validation, and token exchanges (`GET /oauth/callback`).
   - Manages portal disconnection and token eviction (`POST /api/portal/{portal_id}/disconnect`).
   - Serves tenant quota tracking (`GET /api/portal/{portal_id}/quota`) and public Marketplace docs (`/setup-guide`, `/privacy`, `/terms`).
2. **Streamlit Frontend (port 8501):**
   - Renders 5-view workspace: Overview, Clean CRM, Upload Leads, History, Settings.
   - Defaults strictly to **Preview Mode (Dry-Run)** for all data hygiene scans.
   - Dual-gated confirmation required before applying any live CRM writes or merges.
3. **Storage & Multi-Tenancy:**
   - Persistent SQLite database located at `leads_audit.db` (or custom path via `LEADS_AUDIT_DB_PATH`).
   - Tables: `portals` (credentials & quotas), `runs` (history), `record_audit` (per-lead diffs), `merge_audit` (duplicate proposals), and `oauth_states` (anti-CSRF TTL tokens).

---

## 2. Safe Git & Editing Practices
- **Preserve Uncommitted Changes:** Always check `git status` prior to editing files.
- **Never Reset Working Tree:** Avoid `git reset --hard` or deleting files indiscriminately.
- **No Direct GitHub Pushes:** All work must remain in local branches pending review.
- **Zero Secret Exposure:** Never commit `.env` files, private app tokens, client secrets, access tokens, or refresh tokens.

---

## 3. HubSpot OAuth & Least-Privilege Scopes
All operations adhere strictly to the [official HubSpot Scopes specification](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes):
- **Requested Scopes:**
  - `oauth`: Base authorization protocol.
  - `crm.objects.contacts.read`: Contact querying, search by email/phone, and pre-flight diagnostics.
  - `crm.objects.contacts.write`: Non-destructive blank-only property backfills, new lead creation, and duplicate merging.
  - `crm.schemas.contacts.read`: Property schema inspection and field validation.
- **Eliminated Scopes:** Do not request `deals.*` or `companies.*` permissions as no deal or company mutations are performed.

---

## 4. CRM Mutation Safety Rules
1. **Preview-First Principle:** All operations default to `dry_run=True`. Preview modes must never execute HTTP mutations (`POST`, `PATCH`, `DELETE`).
2. **Dual-Gated Confirmation:** In live mode, execution buttons remain disabled until the user explicitly checks an authorization checkbox.
3. **Change-Set & Stale-Preview Guard:** Sync executions validate that the active authenticated portal matches the inspected dataset and verify record count fingerprints before transmitting updates.
4. **Non-Destructive Backfills:** Contact updates only populate blank fields on HubSpot (`overwrite=False`) unless the user explicitly authorizes an overwrite. Existing data is preserved.
5. **Human Review for Fuzzy Matches:** Fuzzy duplicate clusters remain advisory proposals requiring human review; automatic merges based solely on similarity scores are prohibited.
6. **Formula Injection Neutralization:** All spreadsheet exports escape formula triggers (`=`, `+`, `-`, `@`, `\t`, `\r`) by prepending a single-quote (`'`), while preserving valid negative numeric values.

---

## 5. Verification Framework: Distinguishing Test Evidence

| Verification Tier | Description | Status in this Repository |
| :--- | :--- | :--- |
| **Tier 1: Automated Unit / Mock Tests** | Run with `./.venv/bin/pytest -v`. Tests logic against simulated responses. | **PASSED (262/262 tests)** |
| **Tier 2: Local Docker Smoke Tests** | Verifies FastAPI health on `:8000` and Streamlit on `:8501`. | **PASSED (Local container operational)** |
| **Tier 3: Real HubSpot OAuth Handshake** | Live user authorization redirect against `app.hubspot.com`. | **PENDING (Requires external developer app credentials)** |
| **Tier 4: Read-Only Test Portal Access** | Live contact retrieval from an authorized developer portal. | **PENDING (Requires external test account connection)** |
| **Tier 5: Controlled Live Writes on Test Data** | Non-destructive update and merge tests on disposable contacts. | **PENDING (Blocked until Tier 3 & 4 are authorized)** |

---

## 6. How to Run Locally

### Using Local Virtual Environment:
```bash
# Run FastAPI Backend
./.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000 &

# Run Streamlit UI
./.venv/bin/streamlit run app.py --server.port 8501
```

### Running Test Suite:
```bash
./.venv/bin/pytest -v
```

### Using Local Docker Container:
```bash
# Build staging container
docker build -t lead-cleaner:staging .

# Run container with persistent volume
docker run -d --name lead-cleaner-smoke \
  -p 127.0.0.1:8000:8000 \
  -p 127.0.0.1:8501:8501 \
  -v $(pwd)/data:/data \
  -e LEADS_AUDIT_DB_PATH=/data/leads_audit.db \
  lead-cleaner:staging
```
