"""
Filter normalization for cache-key consistency.

Two queries that produce the same filters must produce the same cache key,
regardless of how they were expressed by the user. This module is the single
source of truth for "what does it mean for two queries to be equivalent."

Approach:
1. Convert every filter value to its canonical scalar form (str/int/float),
   stripped, case-normalized to match storage (gender/age_group lowercase,
   country_id uppercase).
2. Drop empty/None values entirely so "?gender=" and (no gender) collide.
3. Sort keys alphabetically to remove ordering noise.
4. Render to a stable JSON string and hash with sha256 for the cache key.

The approach is deterministic: same input filters → same hash, always.
No AI, no fuzzy matching, no semantic guessing.
"""

import hashlib
import json


# Filters that participate in the canonical form. Anything outside this set
# is ignored for cache-key purposes (e.g., timing-only params).
FILTER_KEYS = {
    "gender",
    "age_group",
    "country_id",
    "min_age",
    "max_age",
    "min_gender_probability",
    "min_country_probability",
}

# Sorting keys are kept separate from filters because two queries with the
# same filters but different sort orders are NOT the same query.
SORT_KEYS = {"sort_by", "order"}

# Pagination is also separate.
PAGE_KEYS = {"page", "limit"}


def _coerce_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _coerce_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_filters(params: dict) -> dict:
    """
    Take a raw query-params-like dict (from QueryDict, request.data, or the
    parser output) and return a canonical filter dict. Drops keys we don't
    care about. Coerces types. Lower/upper-cases categorical fields.
    """
    out = {}
    for key in FILTER_KEYS:
        if key not in params:
            continue
        raw = params.get(key)
        if raw is None or raw == "":
            continue

        if key == "gender":
            out[key] = str(raw).strip().lower()
        elif key == "age_group":
            out[key] = str(raw).strip().lower()
        elif key == "country_id":
            out[key] = str(raw).strip().upper()
        elif key in ("min_age", "max_age"):
            n = _coerce_int(raw)
            if n is not None and n >= 0:
                out[key] = n
        elif key in ("min_gender_probability", "min_country_probability"):
            f = _coerce_float(raw)
            if f is not None and 0.0 <= f <= 1.0:
                out[key] = f
    return out


def normalize_sort(params: dict) -> dict:
    """Canonical sort dict — defaults filled in, invalid values dropped."""
    sort_by = params.get("sort_by")
    order = params.get("order")

    valid_sort = {"age", "created_at", "gender_probability"}
    valid_order = {"asc", "desc"}

    if sort_by not in valid_sort:
        sort_by = "created_at"
    if order not in valid_order:
        order = "asc"
    return {"sort_by": sort_by, "order": order}


def normalize_pagination(params: dict) -> dict:
    """Canonical page dict — clamped to valid ranges."""
    try:
        page = max(1, int(params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        limit = min(50, max(1, int(params.get("limit", 10))))
    except (TypeError, ValueError):
        limit = 10
    return {"page": page, "limit": limit}


def canonical_key(
    filters: dict, sort: dict | None = None, pagination: dict | None = None
) -> str:
    """
    Build a deterministic cache key from already-normalized parts.
    Returns sha256 hex digest. Truncated to 32 chars for compact keys —
    32 hex chars = 128 bits, more than enough for collision avoidance.
    """
    payload = {"f": filters}
    if sort is not None:
        payload["s"] = sort
    if pagination is not None:
        payload["p"] = pagination

    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def cache_key_for_query(params: dict, prefix: str = "q") -> str:
    """
    One-shot helper: take raw params, return a cache key.
    Both the parser-output dict and the request.query_params dict work here.
    """
    f = normalize_filters(params)
    s = normalize_sort(params)
    p = normalize_pagination(params)
    return f"{prefix}:{canonical_key(f, s, p)}"
