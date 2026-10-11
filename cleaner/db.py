"""SQLite audit trail, multi-tenant portal management, and logging database module.

Manages tables:
- portals / tenants: Multi-tenant OAuth credentials, plan tiers, and enrichment quotas
- runs: Run metadata (run_id, portal_id, timestamp, file_name, file_hash, row counts, dry_run, status)
- record_audit: Per-record transformation, scoring, issues, cluster assignment, and status
- merge_audit: Duplicate clusters, match types, primary vs merged record details, backfilled fields
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd

DEFAULT_DB_PATH = "leads_audit.db"
DEFAULT_FREEMIUM_QUOTA = 500


def compute_file_hash(file_path: Union[str, Path]) -> str:
    """Compute SHA-256 hash of a file."""
    path = Path(file_path)
    if not path.exists():
        return ""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_connection(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create or connect to the SQLite database and enable foreign keys."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str, col_type: str) -> None:
    """Helper to add column to existing table if missing (for seamless SQLite migration)."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {col_type}")


def init_db(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    """Initialize multi-tenant database schema if tables do not exist."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # 0. portals / tenants table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS portals (
                portal_id TEXT PRIMARY KEY,
                access_token TEXT,
                refresh_token TEXT,
                token_expires_at DATETIME,
                plan_tier TEXT DEFAULT 'free',
                enrichment_quota_limit INTEGER DEFAULT 500,
                enrichment_quota_used INTEGER DEFAULT 0,
                created_at DATETIME NOT NULL
            )
            """
        )

        # 1. runs table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                portal_id TEXT,
                timestamp DATETIME NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT,
                total_rows INTEGER NOT NULL,
                cleaned_rows INTEGER NOT NULL,
                review_rows INTEGER NOT NULL,
                dry_run BOOLEAN NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        _ensure_column_exists(cursor, "runs", "portal_id", "TEXT")

        # 2. record_audit table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS record_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                portal_id TEXT,
                original_index INTEGER,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                email TEXT,
                quality_score INTEGER,
                status TEXT NOT NULL,
                issues TEXT,
                cluster_id TEXT,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs (run_id)
            )
            """
        )
        _ensure_column_exists(cursor, "record_audit", "portal_id", "TEXT")

        # 3. merge_audit table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS merge_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                portal_id TEXT,
                cluster_id TEXT NOT NULL,
                match_type TEXT NOT NULL,
                primary_record_info TEXT,
                merged_records_info TEXT,
                backfilled_fields TEXT,
                timestamp DATETIME NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs (run_id)
            )
            """
        )
        _ensure_column_exists(cursor, "merge_audit", "portal_id", "TEXT")

        conn.commit()


# =============================================================================
# Multi-Tenant Portal & OAuth Token Management
# =============================================================================

def save_portal(
    portal_id: Union[str, int],
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    token_expires_at: Optional[Union[str, datetime]] = None,
    plan_tier: str = "free",
    enrichment_quota_limit: int = DEFAULT_FREEMIUM_QUOTA,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Create or update a portal/tenant in the database."""
    init_db(db_path)
    pid = str(portal_id).strip()

    expires_str = None
    if isinstance(token_expires_at, datetime):
        expires_str = token_expires_at.isoformat()
    elif token_expires_at is not None:
        expires_str = str(token_expires_at)

    now_str = datetime.now(timezone.utc).isoformat()

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM portals WHERE portal_id = ?", (pid,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """
                UPDATE portals
                SET access_token = COALESCE(?, access_token),
                    refresh_token = COALESCE(?, refresh_token),
                    token_expires_at = COALESCE(?, token_expires_at),
                    plan_tier = ?,
                    enrichment_quota_limit = ?
                WHERE portal_id = ?
                """,
                (access_token, refresh_token, expires_str, plan_tier, enrichment_quota_limit, pid),
            )
        else:
            cursor.execute(
                """
                INSERT INTO portals (
                    portal_id, access_token, refresh_token, token_expires_at,
                    plan_tier, enrichment_quota_limit, enrichment_quota_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (pid, access_token, refresh_token, expires_str, plan_tier, enrichment_quota_limit, now_str),
            )
        conn.commit()

    return get_portal(pid, db_path=db_path) or {}


def get_portal(
    portal_id: Union[str, int],
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Optional[Dict[str, Any]]:
    """Retrieve portal/tenant details by portal_id."""
    init_db(db_path)
    pid = str(portal_id).strip()
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM portals WHERE portal_id = ?", (pid,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_portals(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """List all registered portals."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM portals ORDER BY created_at DESC")
        return [dict(r) for r in cursor.fetchall()]


# =============================================================================
# Quota & Billing Guard Helpers
# =============================================================================

def get_enrichment_quota(
    portal_id: Union[str, int],
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """Get enrichment quota usage and remaining allowance for a portal.

    Returns:
        Dict with keys: portal_id, limit, used, remaining, plan_tier, is_exceeded
    """
    portal = get_portal(portal_id, db_path=db_path)
    if not portal:
        # Default freemium tenant if not registered yet
        limit = DEFAULT_FREEMIUM_QUOTA
        used = 0
        plan = "free"
    else:
        limit = portal.get("enrichment_quota_limit", DEFAULT_FREEMIUM_QUOTA)
        used = portal.get("enrichment_quota_used", 0)
        plan = portal.get("plan_tier", "free")

    remaining = max(0, limit - used)
    return {
        "portal_id": str(portal_id),
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "plan_tier": plan,
        "is_exceeded": remaining <= 0,
    }


def increment_enrichment_quota_used(
    portal_id: Union[str, int],
    count: int = 1,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> int:
    """Atomically increment the used enrichment quota for a portal.

    Returns:
        New updated quota used count.
    """
    init_db(db_path)
    pid = str(portal_id).strip()

    # Ensure portal exists
    if not get_portal(pid, db_path=db_path):
        save_portal(pid, db_path=db_path)

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE portals
            SET enrichment_quota_used = enrichment_quota_used + ?
            WHERE portal_id = ?
            """,
            (int(count), pid),
        )
        conn.commit()

        cursor.execute("SELECT enrichment_quota_used FROM portals WHERE portal_id = ?", (pid,))
        row = cursor.fetchone()
        return row[0] if row else 0


# =============================================================================
# Run & Audit Logging
# =============================================================================

def log_run(
    run_id: str,
    file_name: str,
    file_hash: str,
    total_rows: int,
    cleaned_rows: int,
    review_rows: int,
    dry_run: bool = True,
    status: str = "completed",
    timestamp: Optional[Union[str, datetime]] = None,
    portal_id: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> None:
    """Log pipeline run execution metadata with optional multi-tenant portal_id."""
    init_db(db_path)
    if timestamp is None:
        ts_str = datetime.now(timezone.utc).isoformat()
    elif isinstance(timestamp, datetime):
        ts_str = timestamp.isoformat()
    else:
        ts_str = str(timestamp)

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, portal_id, timestamp, file_name, file_hash,
                total_rows, cleaned_rows, review_rows, dry_run, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                str(portal_id) if portal_id else None,
                ts_str,
                file_name,
                file_hash,
                int(total_rows),
                int(cleaned_rows),
                int(review_rows),
                int(dry_run),
                status,
            ),
        )
        conn.commit()


def log_record_audits(
    run_id: str,
    records: Union[List[Dict[str, Any]], pd.DataFrame],
    portal_id: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> None:
    """Log individual records processed in the run with optional portal_id."""
    init_db(db_path)
    if isinstance(records, pd.DataFrame):
        row_dicts = records.to_dict(orient="records")
    else:
        row_dicts = records

    now_str = datetime.now(timezone.utc).isoformat()
    rows_to_insert = []

    for idx, r in enumerate(row_dicts):
        first_name = r.get("first_name") or ""
        last_name = r.get("last_name") or ""
        phone = r.get("phone") or ""
        email = r.get("email") or ""
        q_score = r.get("quality_score", 0)
        status = r.get("route") or ("review" if r.get("needs_review") else "cleaned")

        issues_val = r.get("issues", "")
        if isinstance(issues_val, (list, tuple, set)):
            issues_str = ", ".join(issues_val)
        else:
            issues_str = str(issues_val or "")

        cluster_id = r.get("duplicate_cluster_id") or ""
        original_idx = r.get("original_index", idx)

        rows_to_insert.append(
            (
                run_id,
                str(portal_id) if portal_id else None,
                original_idx,
                str(first_name),
                str(last_name),
                str(phone),
                str(email),
                int(q_score) if pd.notna(q_score) else 0,
                str(status),
                issues_str,
                str(cluster_id) if cluster_id else None,
                now_str,
            )
        )

    if rows_to_insert:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO record_audit (
                    run_id, portal_id, original_index, first_name, last_name, phone, email,
                    quality_score, status, issues, cluster_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_insert,
            )
            conn.commit()


def log_merge_proposals(
    run_id: str,
    proposals: Union[List[Dict[str, Any]], pd.DataFrame],
    portal_id: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> None:
    """Log duplicate merge clusters and proposals with optional portal_id."""
    init_db(db_path)
    if isinstance(proposals, pd.DataFrame):
        proposal_dicts = proposals.to_dict(orient="records")
    else:
        proposal_dicts = proposals

    now_str = datetime.now(timezone.utc).isoformat()
    rows_to_insert = []

    for p in proposal_dicts:
        cluster_id = str(p.get("cluster_id") or "")
        match_type = str(p.get("match_type") or "")

        prim_info = p.get("primary_record_info")
        if prim_info is None:
            prim_info = json.dumps(
                {"index": p.get("primary_index"), "name": p.get("primary_name")}
            )
        elif not isinstance(prim_info, str):
            prim_info = json.dumps(prim_info)

        sec_info = p.get("merged_records_info")
        if sec_info is None:
            sec_info = json.dumps({"indices": p.get("secondary_indices")})
        elif not isinstance(sec_info, str):
            sec_info = json.dumps(sec_info)

        backfilled = str(p.get("backfilled_fields") or "")

        rows_to_insert.append(
            (
                run_id,
                str(portal_id) if portal_id else None,
                cluster_id,
                match_type,
                prim_info,
                sec_info,
                backfilled,
                now_str,
            )
        )

    if rows_to_insert:
        with get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO merge_audit (
                    run_id, portal_id, cluster_id, match_type, primary_record_info,
                    merged_records_info, backfilled_fields, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_to_insert,
            )
            conn.commit()


def get_run(run_id: str, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Retrieve run record by run_id."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_record_audits(run_id: str, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve all record audit entries for a run."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM record_audit WHERE run_id = ? ORDER BY audit_id ASC", (run_id,))
        return [dict(r) for r in cursor.fetchall()]


def get_merge_audits(run_id: str, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve all merge proposals / audits for a run."""
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM merge_audit WHERE run_id = ? ORDER BY id ASC", (run_id,))
        return [dict(r) for r in cursor.fetchall()]
