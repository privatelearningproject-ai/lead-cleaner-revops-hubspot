"""Deduplication Engine and Merge Proposals for Indian SMB Leads.

Follows the strict hierarchy:
1. Exact match on normalized E.164 phone (non-empty).
2. Exact match on normalized email (non-empty).
3. Fuzzy match on full name (first_name + " " + last_name) AND identical city:
   - Evaluated using rapidfuzz.fuzz.token_sort_ratio > threshold (default 90).
   - Fuzzy matches are NEVER automatically merged.
   - Flagged with issue 'duplicate_fuzzy_review' and routed to review.csv.

Supports:
- Union-Find cluster generation
- Identifying primary surviving records by quality score
- Non-destructive field backfilling for exact duplicates
- Cluster audit trace and merge proposals
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
from rapidfuzz import fuzz

from cleaner.loader import CANONICAL_COLUMNS


def _clean_str(val: Any) -> str:
    """Helper to convert value to trimmed string or empty string."""
    if val is None or pd.isna(val):
        return ""
    return str(val).strip()


class UnionFind:
    """Disjoint Set Union (Union-Find) with path compression for clustering."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, i: int) -> int:
        if self.parent[i] != i:
            self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: int, j: int) -> bool:
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i == root_j:
            return False
        if self.rank[root_i] < self.rank[root_j]:
            self.parent[root_i] = root_j
        elif self.rank[root_i] > self.rank[root_j]:
            self.parent[root_j] = root_i
        else:
            self.parent[root_j] = root_i
            self.rank[root_i] += 1
        return True


def deduplicate_leads(
    df: pd.DataFrame,
    fuzzy_threshold: int = 90,
    auto_merge_exact: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Execute deduplication across leads following the strict matching hierarchy.

    Args:
        df: Input DataFrame containing normalized and validated leads.
        fuzzy_threshold: Minimum rapidfuzz token_sort_ratio for name similarity (default 90).
        auto_merge_exact: If True, backfill primary record and merge exact duplicates.

    Returns:
        (deduped_df, proposals_df):
        - deduped_df: Processed DataFrame with cluster metadata and merged records.
        - proposals_df: Audit DataFrame describing all duplicate clusters and merge proposals.
    """
    if df.empty:
        empty_proposals = pd.DataFrame(
            columns=[
                "cluster_id",
                "match_type",
                "primary_index",
                "secondary_indices",
                "primary_name",
                "backfilled_fields",
                "requires_review",
            ]
        )
        return df.copy(), empty_proposals

    n = len(df)
    work_df = df.copy().reset_index(drop=True)

    # Ensure required trace columns exist
    work_df["duplicate_cluster_id"] = None
    work_df["duplicate_match_type"] = "none"
    work_df["is_duplicate_primary"] = True

    # Prepare index lookups for matching
    # 1. Exact Phone matching (priority 1)
    phone_map: Dict[str, List[int]] = {}
    for idx, row in work_df.iterrows():
        p = _clean_str(row.get("phone"))
        # Exclude empty or invalid phone placeholders
        if p and p != "+91" and len(p) >= 10:
            phone_map.setdefault(p, []).append(idx)

    # 2. Exact Email matching (priority 2)
    email_map: Dict[str, List[int]] = {}
    for idx, row in work_df.iterrows():
        e = _clean_str(row.get("email")).lower()
        if e and "@" in e:
            email_map.setdefault(e, []).append(idx)

    # 3. Match tracking structures
    uf = UnionFind(n)
    pair_match_types: Dict[Tuple[int, int], str] = {}

    # Step 1: Connect exact phone matches
    for phone_val, indices in phone_map.items():
        if len(indices) > 1:
            first = indices[0]
            for other in indices[1:]:
                uf.union(first, other)
                pair_key = (min(first, other), max(first, other))
                pair_match_types[pair_key] = "exact_phone"

    # Step 2: Connect exact email matches
    for email_val, indices in email_map.items():
        if len(indices) > 1:
            first = indices[0]
            for other in indices[1:]:
                uf.union(first, other)
                pair_key = (min(first, other), max(first, other))
                if pair_key not in pair_match_types:
                    pair_match_types[pair_key] = "exact_email"

    # Step 3: Fuzzy Name + City matching (priority 3)
    # Never match on name alone; city must be identical and non-empty
    city_indices: Dict[str, List[int]] = {}
    for idx, row in work_df.iterrows():
        city_val = _clean_str(row.get("city")).lower()
        if city_val:
            city_indices.setdefault(city_val, []).append(idx)

    for city_val, indices in city_indices.items():
        if len(indices) > 1:
            # Compare pairs in same city
            for i_pos in range(len(indices)):
                idx_i = indices[i_pos]
                name_i = f"{_clean_str(work_df.at[idx_i, 'first_name'])} {_clean_str(work_df.at[idx_i, 'last_name'])}".strip()
                if not name_i:
                    continue

                for j_pos in range(i_pos + 1, len(indices)):
                    idx_j = indices[j_pos]
                    name_j = f"{_clean_str(work_df.at[idx_j, 'first_name'])} {_clean_str(work_df.at[idx_j, 'last_name'])}".strip()
                    if not name_j:
                        continue

                    # If already connected by exact phone/email, keep exact priority
                    if uf.find(idx_i) == uf.find(idx_j):
                        continue

                    score = fuzz.token_sort_ratio(name_i, name_j)
                    if score > fuzzy_threshold:
                        uf.union(idx_i, idx_j)
                        pair_key = (min(idx_i, idx_j), max(idx_i, idx_j))
                        pair_match_types[pair_key] = "fuzzy_name_city"

    # Group records into clusters
    clusters_map: Dict[int, List[int]] = {}
    for i in range(n):
        root = uf.find(i)
        clusters_map.setdefault(root, []).append(i)

    # Process each cluster
    cluster_counter = 1
    proposal_records: List[Dict[str, Any]] = []
    indices_to_drop_if_merged: Set[int] = set()

    for root_id, member_indices in clusters_map.items():
        if len(member_indices) <= 1:
            # Unique record
            idx = member_indices[0]
            work_df.at[idx, "duplicate_match_type"] = "none"
            work_df.at[idx, "is_duplicate_primary"] = True
            continue

        cluster_id = f"cluster_{cluster_counter:03d}"
        cluster_counter += 1

        # Determine dominant match type for this cluster
        cluster_pair_types = set()
        for i_pos in range(len(member_indices)):
            for j_pos in range(i_pos + 1, len(member_indices)):
                pair = (min(member_indices[i_pos], member_indices[j_pos]), max(member_indices[i_pos], member_indices[j_pos]))
                if pair in pair_match_types:
                    cluster_pair_types.add(pair_match_types[pair])

        if "fuzzy_name_city" in cluster_pair_types:
            cluster_match_type = "fuzzy_name_city"
            is_fuzzy = True
        elif "exact_phone" in cluster_pair_types:
            cluster_match_type = "exact_phone"
            is_fuzzy = False
        else:
            cluster_match_type = "exact_email"
            is_fuzzy = False

        # Select primary record: highest quality score; ties broken by earliest index
        def _get_sort_key(idx: int):
            q_score = work_df.at[idx, "quality_score"] if "quality_score" in work_df.columns else 0
            try:
                q_score = float(q_score)
            except (ValueError, TypeError):
                q_score = 0.0
            return (-q_score, idx)

        sorted_indices = sorted(member_indices, key=_get_sort_key)
        primary_idx = sorted_indices[0]
        secondary_indices = sorted_indices[1:]

        # Annotate records
        for idx in member_indices:
            work_df.at[idx, "duplicate_cluster_id"] = cluster_id
            work_df.at[idx, "duplicate_match_type"] = cluster_match_type
            work_df.at[idx, "is_duplicate_primary"] = (idx == primary_idx)

        # Handle Fuzzy Matches vs Exact Matches
        if is_fuzzy:
            # Crucial Rule: Fuzzy matches must NEVER be automatically merged.
            # Flag with issue 'duplicate_fuzzy_review' and route to review.csv.
            for idx in member_indices:
                curr_issues = work_df.at[idx, "issues"] if "issues" in work_df.columns else []
                if isinstance(curr_issues, str):
                    issue_list = [i.strip() for i in curr_issues.split(",") if i.strip()]
                elif isinstance(curr_issues, list):
                    issue_list = list(curr_issues)
                else:
                    issue_list = []

                if "duplicate_fuzzy_review" not in issue_list:
                    issue_list.append("duplicate_fuzzy_review")

                work_df.at[idx, "issues"] = issue_list
                work_df.at[idx, "issues_str"] = ", ".join(issue_list)
                work_df.at[idx, "route"] = "review"
                work_df.at[idx, "needs_review"] = True

            prim_hs_id = _clean_str(work_df.at[primary_idx, "hubspot_contact_id"]) if "hubspot_contact_id" in work_df.columns else ""
            sec_hs_ids = [
                _clean_str(work_df.at[s_idx, "hubspot_contact_id"])
                for s_idx in secondary_indices
                if "hubspot_contact_id" in work_df.columns and _clean_str(work_df.at[s_idx, "hubspot_contact_id"])
            ]

            proposal_records.append(
                {
                    "cluster_id": cluster_id,
                    "match_type": "fuzzy_name_city",
                    "primary_index": primary_idx,
                    "secondary_indices": secondary_indices,
                    "primary_name": f"{_clean_str(work_df.at[primary_idx, 'first_name'])} {_clean_str(work_df.at[primary_idx, 'last_name'])}",
                    "primary_contact_id": prim_hs_id,
                    "secondary_contact_ids": sec_hs_ids,
                    "backfilled_fields": "",
                    "requires_review": True,
                }
            )

        else:
            # Exact match (exact_phone or exact_email)
            backfilled: Dict[str, Any] = {}
            if auto_merge_exact:
                # Field backfilling: Fill missing values in primary record from secondary records
                for field in CANONICAL_COLUMNS:
                    if field not in work_df.columns:
                        continue
                    primary_val = _clean_str(work_df.at[primary_idx, field])
                    if not primary_val:
                        # Find first non-empty value in secondaries
                        for sec_idx in secondary_indices:
                            sec_val = _clean_str(work_df.at[sec_idx, field])
                            if sec_val:
                                work_df.at[primary_idx, field] = sec_val
                                backfilled[field] = sec_val
                                break

                # Handle notes concatenation if both have notes
                if "notes_raw" in work_df.columns:
                    for sec_idx in secondary_indices:
                        sec_notes = _clean_str(work_df.at[sec_idx, "notes_raw"])
                        prim_notes = _clean_str(work_df.at[primary_idx, "notes_raw"])
                        if sec_notes and sec_notes not in prim_notes:
                            if prim_notes:
                                work_df.at[primary_idx, "notes_raw"] = f"{prim_notes} | {sec_notes}"
                            else:
                                work_df.at[primary_idx, "notes_raw"] = sec_notes

                # Mark secondaries to be dropped from active clean output
                indices_to_drop_if_merged.update(secondary_indices)

            prim_hs_id = _clean_str(work_df.at[primary_idx, "hubspot_contact_id"]) if "hubspot_contact_id" in work_df.columns else ""
            sec_hs_ids = [
                _clean_str(work_df.at[s_idx, "hubspot_contact_id"])
                for s_idx in secondary_indices
                if "hubspot_contact_id" in work_df.columns and _clean_str(work_df.at[s_idx, "hubspot_contact_id"])
            ]

            proposal_records.append(
                {
                    "cluster_id": cluster_id,
                    "match_type": cluster_match_type,
                    "primary_index": primary_idx,
                    "secondary_indices": secondary_indices,
                    "primary_name": f"{_clean_str(work_df.at[primary_idx, 'first_name'])} {_clean_str(work_df.at[primary_idx, 'last_name'])}",
                    "primary_contact_id": prim_hs_id,
                    "secondary_contact_ids": sec_hs_ids,
                    "backfilled_fields": ", ".join(backfilled.keys()) if backfilled else "",
                    "requires_review": False,
                }
            )

    proposals_df = pd.DataFrame(proposal_records)

    # If auto_merge_exact is True, drop the merged secondary records from deduped output
    if auto_merge_exact and indices_to_drop_if_merged:
        deduped_df = work_df.drop(index=list(indices_to_drop_if_merged)).reset_index(drop=True)
    else:
        deduped_df = work_df.copy()

    return deduped_df, proposals_df
