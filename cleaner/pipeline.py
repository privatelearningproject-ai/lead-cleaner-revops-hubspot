"""Core Pipeline Orchestrator and CLI Execution Module.

Orchestrates:
Step 1: Load file and map columns (cleaner/loader.py)
Step 2: Field normalization (cleaner/normalize.py)
Step 3: Validation and quality scoring (cleaner/validate.py)
Step 4: Deduplication, fuzzy match review flagging, and exact backfilling (cleaner/dedupe.py)
Step 5: Final routing (cleaned.csv vs review.csv)
Step 6: Reporting and artifact generation (cleaner/report.py)
Step 7: Immutable audit logging in SQLite (cleaner/db.py)
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

from cleaner.db import (
    DEFAULT_DB_PATH,
    compute_file_hash,
    log_merge_proposals,
    log_record_audits,
    log_run,
)
from cleaner.dedupe import deduplicate_leads
from cleaner.enrich import enrich_dataframe
from cleaner.loader import load_and_map
from cleaner.report import (
    generate_markdown_report,
    generate_summary_stats,
    write_csv_outputs,
)
from cleaner.validate import FATAL_ISSUES, validate_dataframe


def run_pipeline(
    input_file_path: Union[str, Path],
    output_dir: Union[str, Path] = "output",
    dry_run: bool = True,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
    fuzzy_threshold: int = 90,
    run_id: Optional[str] = None,
    enrich: bool = False,
    portal_id: Optional[str] = "default_portal",
) -> Dict[str, Any]:
    """Execute the end-to-end lead cleaning and validation pipeline.

    Args:
        input_file_path: Path to raw input file (.csv, .xlsx, .xls).
        output_dir: Directory where cleaned.csv, review.csv, and report.md are written.
        dry_run: Safety flag. Always defaults to True.
        db_path: Path to SQLite audit database.
        fuzzy_threshold: rapidfuzz token_sort_ratio threshold for name similarity.
        run_id: Optional custom run identifier; generates UUID4 if None.
        enrich: Optional flag to extract structured notes via Cloud LLM.
        portal_id: Optional tenant portal ID for multi-tenant audit logs & quota tracking.

    Returns:
        Summary dictionary with metrics, paths, and status.
    """
    input_path = Path(input_file_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    current_run_id = run_id or str(uuid.uuid4())
    out_dir_path = Path(output_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    file_name = input_path.name
    file_hash = compute_file_hash(input_path)

    # -------------------------------------------------------------------------
    # Step 1: Ingestion and Column Mapping (cleaner/loader.py)
    # -------------------------------------------------------------------------
    raw_df = load_and_map(input_path)
    total_loaded = len(raw_df)

    # -------------------------------------------------------------------------
    # Step 2 & 3: Normalization & Validation Scoring (cleaner/validate.py)
    # -------------------------------------------------------------------------
    validated_df = validate_dataframe(raw_df)

    # -------------------------------------------------------------------------
    # Step 4: Deduplication & Exact Merge Backfilling (cleaner/dedupe.py)
    # -------------------------------------------------------------------------
    deduped_df, proposals_df = deduplicate_leads(
        validated_df,
        fuzzy_threshold=fuzzy_threshold,
        auto_merge_exact=True,
    )

    # -------------------------------------------------------------------------
    # Step 4.5: Optional Cloud LLM Enrichment with Quota Guard (cleaner/enrich.py)
    # -------------------------------------------------------------------------
    deduped_df, enrichment_quota_summary = enrich_dataframe(
        deduped_df,
        enabled=enrich,
        portal_id=portal_id or "default_portal",
        db_path=db_path,
    )

    # -------------------------------------------------------------------------
    # Step 5: Final Routing
    # -------------------------------------------------------------------------
    # Any record with fatal issues, duplicate_fuzzy_review, or score < 70 goes to review
    for idx in deduped_df.index:
        issues = deduped_df.at[idx, "issues"] or []
        if isinstance(issues, str):
            issue_list = [i.strip() for i in issues.split(",") if i.strip()]
        elif isinstance(issues, list):
            issue_list = list(issues)
        else:
            issue_list = []

        q_score = deduped_df.at[idx, "quality_score"]
        has_fatal = any(f in issue_list for f in FATAL_ISSUES)
        is_fuzzy_review = "duplicate_fuzzy_review" in issue_list

        if q_score < 70 or has_fatal or is_fuzzy_review:
            deduped_df.at[idx, "route"] = "review"
            deduped_df.at[idx, "needs_review"] = True
        else:
            deduped_df.at[idx, "route"] = "cleaned"
            deduped_df.at[idx, "needs_review"] = False

    cleaned_df = deduped_df[deduped_df["route"] == "cleaned"]
    review_df = deduped_df[deduped_df["route"] == "review"]

    cleaned_count = len(cleaned_df)
    review_count = len(review_df)

    # -------------------------------------------------------------------------
    # Step 6: Write Output Artifacts (cleaner/report.py)
    # -------------------------------------------------------------------------
    cleaned_file_path = out_dir_path / "cleaned.csv"
    review_file_path = out_dir_path / "review.csv"
    report_file_path = out_dir_path / "report.md"

    write_csv_outputs(deduped_df, cleaned_file_path, review_file_path)

    batch_stats = generate_summary_stats(deduped_df)
    generate_markdown_report(batch_stats, output_path=report_file_path)

    # Optional: write proposals to proposals.csv if any exist
    if not proposals_df.empty:
        proposals_file_path = out_dir_path / "proposals.csv"
        proposals_df.to_csv(proposals_file_path, index=False, encoding="utf-8")

    # -------------------------------------------------------------------------
    # Step 7: Immutable Audit Logging (cleaner/db.py)
    # -------------------------------------------------------------------------
    log_run(
        run_id=current_run_id,
        file_name=file_name,
        file_hash=file_hash,
        total_rows=total_loaded,
        cleaned_rows=cleaned_count,
        review_rows=review_count,
        dry_run=dry_run,
        status="completed",
        portal_id=portal_id,
        db_path=db_path,
    )

    # Log record audits for all rows in the deduped dataset
    log_record_audits(
        run_id=current_run_id,
        records=deduped_df,
        portal_id=portal_id,
        db_path=db_path,
    )

    # Log merge proposals
    if not proposals_df.empty:
        log_merge_proposals(
            run_id=current_run_id,
            proposals=proposals_df,
            portal_id=portal_id,
            db_path=db_path,
        )

    return {
        "run_id": current_run_id,
        "portal_id": portal_id,
        "input_file": str(input_path),
        "total_rows": total_loaded,
        "cleaned_count": cleaned_count,
        "review_count": review_count,
        "deduped_total": len(deduped_df),
        "merged_clusters_count": len(proposals_df),
        "cleaned_file": str(cleaned_file_path),
        "review_file": str(review_file_path),
        "report_file": str(report_file_path),
        "dry_run": dry_run,
        "status": "completed",
        "enrichment_quota": enrichment_quota_summary,
    }


def main() -> None:
    """CLI Entrypoint for the Lead Cleaner Pipeline."""
    parser = argparse.ArgumentParser(
        description="Lead Cleaner: Ingest, normalize, validate, dedupe, and audit Indian SMB leads."
    )
    parser.add_argument("input_file", help="Path to input .csv or .xlsx file")
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to save cleaned.csv, review.csv, and report.md (default: output)",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Run in dry-run mode without external mutations (default: True)",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Disable dry-run mode (requires explicit flag)",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help="SQLite database path for audit logs (default: leads_audit.db)",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=int,
        default=90,
        help="Rapidfuzz token_sort_ratio threshold for name duplicates (default: 90)",
    )
    parser.add_argument(
        "--enrich",
        dest="enrich",
        action="store_true",
        default=False,
        help="Enable optional local LLM notes enrichment via Ollama (default: False)",
    )
    parser.add_argument(
        "--no-enrich",
        dest="enrich",
        action="store_false",
        help="Disable optional local LLM notes enrichment",
    )
    parser.add_argument(
        "--portal-id",
        dest="portal_id",
        default="default_portal",
        help="HubSpot Account / Portal ID for multi-tenant tenant isolation and quota enforcement",
    )

    args = parser.parse_args()

    try:
        summary = run_pipeline(
            input_file_path=args.input_file,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            db_path=args.db_path,
            fuzzy_threshold=args.fuzzy_threshold,
            enrich=args.enrich,
            portal_id=args.portal_id,
        )

        print("\n" + "=" * 60)
        print("LEAD CLEANER PIPELINE COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print(f"Run ID:            {summary['run_id']}")
        print(f"Input File:        {summary['input_file']}")
        print(f"Total Rows Ingest: {summary['total_rows']}")
        print(f"Cleaned Leads:     {summary['cleaned_count']} -> {summary['cleaned_file']}")
        print(f"Review Leads:      {summary['review_count']} -> {summary['review_file']}")
        print(f"Duplicate Merges:  {summary['merged_clusters_count']}")
        print(f"Markdown Report:   {summary['report_file']}")
        print(f"Dry Run Mode:      {summary['dry_run']}")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
