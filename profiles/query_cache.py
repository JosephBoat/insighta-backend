"""
Read-through cache for profile list / search queries.

Why cache the *response payload* (not the queryset)?
A queryset is lazy and can't be pickled in a useful way once executed.
The expensive parts of a list endpoint are: count(), the LIMIT/OFFSET fetch,
and JSON serialization. Caching the final response dict skips all of them.

Why a short TTL (60s)?
Profiles change rarely (writes are batch ingestion). A 60-second window means
the worst-case staleness is bounded, but repeated queries from the same
dashboard/UI in a session almost always hit the cache. With ~40% repeat rate
and 60s TTL, the DB load reduction is roughly proportional.

We invalidate on writes (create/delete/bulk ingest) by bumping a version
counter — every cached entry is namespaced with the current version, so a
single counter increment evicts the entire query-cache namespace at once.
That's much cheaper than tracking which keys are stale.
"""

from django.core.cache import cache
from .normalize import (
    normalize_filters,
    normalize_sort,
    normalize_pagination,
    canonical_key,
)

CACHE_TTL_SECONDS = 60
VERSION_KEY = "profiles:list:version"


def _current_version() -> int:
    v = cache.get(VERSION_KEY)
    if v is None:
        cache.set(VERSION_KEY, 1, None)  # no expiry
        return 1
    return int(v)


def bump_version() -> None:
    """Invalidate every cached profile-list response in one call."""
    try:
        cache.incr(VERSION_KEY)
    except ValueError:
        # Key not set yet (or evicted from LocMem). Initialize.
        cache.set(VERSION_KEY, 2, None)


def build_cache_key(params: dict, scope: str = "list") -> str:
    """
    scope distinguishes /api/profiles (list) from /api/profiles/search (search).
    They share the same filter shape but they're different intents.
    """
    f = normalize_filters(params)
    s = normalize_sort(params)
    p = normalize_pagination(params)
    base = canonical_key(f, s, p)
    return f"profiles:{scope}:v{_current_version()}:{base}"


def get_cached(key: str):
    return cache.get(key)


def set_cached(key: str, value, ttl: int = CACHE_TTL_SECONDS) -> None:
    cache.set(key, value, ttl)
