"""Batch statistics, report generation, and export utilities.

Generates:
- Statistical analysis of quality scores and issues
- Export to cleaned.csv and review.csv
- Human-readable analytical Markdown summary report (report.md)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import pandas as pd


def generate_summary_stats(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate summary metrics and distributions for a processed batch of leads."""
    total_rows = len(df)
    if total_rows == 0:
        return {
            "total_rows": 0,
            "cleaned_count": 0,
            "cleaned_pct": 0.0,
            "review_count": 0,
            "review_pct": 0.0,
            "avg_quality_score": 0.0,
            "min_quality_score": 0,
            "max_quality_score": 0,
            "median_quality_score": 0.0,
            "score_buckets": {"90-100": 0, "70-89": 0, "50-69": 0, "<50": 0},
            "issue_counts": {},
            "missing_consent_count": 0,
        }

    # Route counts
    routes = df["route"] if "route" in df.columns else df.get("needs_review", pd.Series([False]*total_rows)).map(
        lambda x: "review" if x else "cleaned"
    )
    cleaned_count = int((routes == "cleaned").sum())
    review_count = int((routes == "review").sum())
    cleaned_pct = round((cleaned_count / total_rows) * 100, 1)
    review_pct = round((review_count / total_rows) * 100, 1)

    # Quality scores
    scores = df["quality_score"] if "quality_score" in df.columns else pd.Series([100]*total_rows)
    avg_score = round(float(scores.mean()), 1)
    min_score = int(scores.min())
    max_score = int(scores.max())
    median_score = round(float(scores.median()), 1)

    # Score buckets
    bucket_90_100 = int(((scores >= 90) & (scores <= 100)).sum())
    bucket_70_89 = int(((scores >= 70) & (scores < 90)).sum())
    bucket_50_69 = int(((scores >= 50) & (scores < 70)).sum())
    bucket_lt_50 = int((scores < 50).sum())

    score_buckets = {
        "90-100": bucket_90_100,
        "70-89": bucket_70_89,
        "50-69": bucket_50_69,
        "<50": bucket_lt_50,
    }

    # Issue breakdown
    issue_counts: Dict[str, int] = {}
    missing_consent_count = 0

    if "issues" in df.columns:
        for issues_val in df["issues"]:
            if isinstance(issues_val, (list, set, tuple)):
                items = list(issues_val)
            elif isinstance(issues_val, str) and issues_val.strip():
                items = [i.strip() for i in issues_val.split(",") if i.strip()]
            else:
                items = []

            for item in items:
                issue_counts[item] = issue_counts.get(item, 0) + 1
                if item == "consent_missing":
                    missing_consent_count += 1
    elif "consent_source" in df.columns:
        missing_consent_count = int(df["consent_source"].isna().sum() + (df["consent_source"] == "").sum())

    # Sort issue counts descending
    sorted_issue_counts = dict(sorted(issue_counts.items(), key=lambda x: x[1], reverse=True))

    return {
        "total_rows": total_rows,
        "cleaned_count": cleaned_count,
        "cleaned_pct": cleaned_pct,
        "review_count": review_count,
        "review_pct": review_pct,
        "avg_quality_score": avg_score,
        "min_quality_score": min_score,
        "max_quality_score": max_score,
        "median_quality_score": median_score,
        "score_buckets": score_buckets,
        "issue_counts": sorted_issue_counts,
        "missing_consent_count": missing_consent_count,
    }


def _sanitize_formula_injection(val: Any) -> Any:
    """Escape CSV formula injection triggers (=, +, -, @, tab, cr) while preserving safe negative numbers."""
    if isinstance(val, str) and val:
        stripped = val.lstrip(" \t\r\n")
        if stripped:
            first_char = stripped[0]
            if first_char in ("=", "+", "@"):
                return "'" + val
            elif first_char == "-":
                # Check if it is a pure numeric negative number (e.g., "-5", "-12.50")
                try:
                    float(stripped)
                    return val
                except ValueError:
                    return "'" + val
    return val


def write_csv_outputs(
    df: pd.DataFrame,
    cleaned_path: Union[str, Path] = "cleaned.csv",
    review_path: Union[str, Path] = "review.csv",
) -> Tuple[Path, Path]:
    """Export validated DataFrame into cleaned.csv and review.csv."""
    clean_p = Path(cleaned_path)
    review_p = Path(review_path)

    clean_p.parent.mkdir(parents=True, exist_ok=True)
    review_p.parent.mkdir(parents=True, exist_ok=True)

    export_df = df.copy()

    # Format issues column nicely as string if it is a list
    if "issues" in export_df.columns:
        export_df["issues"] = export_df["issues"].apply(
            lambda x: ", ".join(x) if isinstance(x, (list, tuple, set)) else str(x or "")
        )

    # Protect against CSV formula injection on all object/string columns
    for col in export_df.columns:
        export_df[col] = export_df[col].apply(_sanitize_formula_injection)

    # Split rows
    if "route" in export_df.columns:
        cleaned_df = export_df[export_df["route"] == "cleaned"]
        review_df = export_df[export_df["route"] == "review"]
    else:
        cleaned_df = export_df[export_df.get("needs_review", False) == False]
        review_df = export_df[export_df.get("needs_review", False) == True]

    cleaned_df.to_csv(clean_p, index=False, encoding="utf-8")
    review_df.to_csv(review_p, index=False, encoding="utf-8")

    return clean_p, review_p


def generate_markdown_report(
    stats: Dict[str, Any],
    output_path: Optional[Union[str, Path]] = "report.md",
) -> str:
    """Generate human-readable Markdown summary report from batch stats."""
    total = stats.get("total_rows", 0)
    cleaned = stats.get("cleaned_count", 0)
    cleaned_pct = stats.get("cleaned_pct", 0.0)
    review = stats.get("review_count", 0)
    review_pct = stats.get("review_pct", 0.0)

    avg_score = stats.get("avg_quality_score", 0.0)
    min_score = stats.get("min_quality_score", 0)
    max_score = stats.get("max_quality_score", 0)
    median_score = stats.get("median_quality_score", 0.0)

    buckets = stats.get("score_buckets", {})
    issues = stats.get("issue_counts", {})
    missing_consent = stats.get("missing_consent_count", 0)

    lines = [
        "# Lead Hygiene & Data Quality Report",
        "",
        "## 1. Executive Summary",
        "",
        f"- **Total Leads Processed:** {total}",
        f"- **Cleaned & Approved (>= 70):** {cleaned} ({cleaned_pct}%)",
        f"- **Flagged for Review (< 70 or Fatal Issue):** {review} ({review_pct}%)",
        "",
        "| Metric | Count | Percentage |",
        "| :--- | :--- | :--- |",
        f"| **Cleaned Leads (`cleaned.csv`)** | {cleaned} | {cleaned_pct}% |",
        f"| **Review Required (`review.csv`)** | {review} | {review_pct}% |",
        f"| **Total Processed** | {total} | 100.0% |",
        "",
        "## 2. Lead Quality Score Distribution",
        "",
        f"- **Average Quality Score:** {avg_score} / 100",
        f"- **Median Quality Score:** {median_score} / 100",
        f"- **Score Range:** {min_score} – {max_score}",
        "",
        "| Score Range | Tier | Lead Count | Share |",
        "| :--- | :--- | :--- | :--- |",
        f"| 90 – 100 | Excellent | {buckets.get('90-100', 0)} | {round(buckets.get('90-100', 0) / max(total, 1) * 100, 1)}% |",
        f"| 70 – 89 | Good (Approved) | {buckets.get('70-89', 0)} | {round(buckets.get('70-89', 0) / max(total, 1) * 100, 1)}% |",
        f"| 50 – 69 | Needs Review | {buckets.get('50-69', 0)} | {round(buckets.get('50-69', 0) / max(total, 1) * 100, 1)}% |",
        f"| < 50 | Critical Issues | {buckets.get('<50', 0)} | {round(buckets.get('<50', 0) / max(total, 1) * 100, 1)}% |",
        "",
        "## 3. Issue Breakdown Frequency",
        "",
    ]

    if issues:
        lines.append("| Issue Flag | Occurrences | Impact / Action |")
        lines.append("| :--- | :--- | :--- |")
        for issue_tag, count in issues.items():
            pct = round(count / max(total, 1) * 100, 1)
            action = "Fatal / Routed to Review" if issue_tag in FATAL_ISSUES_NAMES else "Score Deducted / Informational"
            lines.append(f"| `{issue_tag}` | {count} ({pct}%) | {action} |")
        lines.append("")
    else:
        lines.append("No validation issues detected in this batch.\n")

    lines.extend([
        "## 4. Compliance & Consent Status",
        "",
        f"- **Missing Consent Records:** {missing_consent}",
        "- **Policy Note:** Leads with missing consent are tagged with `consent_missing` to exclude them from automated marketing campaigns while preserving contact records.",
        "",
        "---",
        "*Report generated automatically by Lead-Cleaner Agent.*",
    ])

    report_content = "\n".join(lines)

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(report_content, encoding="utf-8")

    return report_content


FATAL_ISSUES_NAMES = {
    "phone_invalid",
    "email_invalid",
    "missing_contact",
    "gst_state_mismatch",
    "city_unknown",
    "state_unknown",
    "missing_name",
}
