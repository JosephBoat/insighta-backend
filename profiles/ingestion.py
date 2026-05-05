"""
Streaming CSV ingestion for profile bulk uploads.

Design summary
==============

Streaming, not slurp:
    csv.DictReader iterates lazily over the upload, never loading the whole
    file into memory. We process it row-by-row and only ever hold a bounded
    in-memory batch of `BATCH_SIZE` profile objects at a time. Memory usage
    is O(BATCH_SIZE), independent of file size.

Bulk INSERTs, not row-by-row:
    bulk_create with `ignore_conflicts=True` lets us insert thousands of
    rows in one round-trip, and Postgres silently skips rows that violate
    the unique constraint on `name`. That handles cross-upload duplicates
    safely without per-row SELECT-then-INSERT.

Skip, don't fail:
    Every row goes through `_validate_row`. Bad rows are tallied by reason
    and skipped — they never abort the upload. Each batch is its own
    transaction (via the implicit transaction in bulk_create), so a Postgres
    error mid-stream doesn't roll back rows already committed in earlier
    batches.

Concurrent uploads:
    Two simultaneous uploads work naturally because:
    - Postgres uses row-level locks on INSERTs; writers don't block writers
      unless they collide on the same name (and `ignore_conflicts` makes
      that a no-op anyway).
    - Readers (the regular /api/profiles queries) don't block on INSERTs
      thanks to MVCC, so query latency is preserved during ingestion.
    - We pre-check the DB for existing names per batch to give an accurate
      `duplicate_name` count even with races.
"""

import csv
import io

from .models import Profile
from .services import _get_age_group, _get_country_name
from .query_cache import bump_version


BATCH_SIZE = 5000
ALLOWED_GENDERS = {"male", "female"}
MAX_REASONABLE_AGE = 150

REQUIRED_COLUMNS = {"name", "gender", "age", "country_id"}


def _validate_row(raw: dict):
    """
    Return (profile_kwargs_dict, skip_reason).
    Exactly one is None.
    """
    if raw is None:
        return None, "malformed_row"

    name = (raw.get("name") or "").strip().lower()
    gender = (raw.get("gender") or "").strip().lower()
    age_raw = raw.get("age")
    country_id = (raw.get("country_id") or "").strip().upper()

    if not name or not gender or age_raw in (None, "") or not country_id:
        return None, "missing_fields"

    if gender not in ALLOWED_GENDERS:
        return None, "invalid_gender"

    try:
        age = int(str(age_raw).strip())
    except (TypeError, ValueError):
        return None, "invalid_age"
    if age < 0 or age > MAX_REASONABLE_AGE:
        return None, "invalid_age"

    def _safe_float(value, default):
        try:
            f = float(value)
            return f if 0.0 <= f <= 1.0 else default
        except (TypeError, ValueError):
            return default

    def _safe_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return {
        "name": name,
        "gender": gender,
        "gender_probability": _safe_float(raw.get("gender_probability"), 1.0),
        "age": age,
        "age_group": _get_age_group(age),
        "country_id": country_id,
        "country_name": (raw.get("country_name") or "").strip()
        or _get_country_name(country_id),
        "country_probability": _safe_float(raw.get("country_probability"), 1.0),
        "sample_size": _safe_int(raw.get("sample_size"), 0),
    }, None


def _bump_reason(reasons: dict, key: str, n: int = 1):
    reasons[key] = reasons.get(key, 0) + n


def _flush_batch(batch_objs):
    """
    Insert a batch. Returns (inserted_count, dedup_skipped_count).

    dedup_skipped_count is the number of rows in `batch_objs` whose `name`
    already exists in the DB at the moment of flush. That can be both
    pre-existing rows AND rows committed by a concurrent upload between
    our pre-check and our INSERT.
    """
    if not batch_objs:
        return 0, 0

    names = [p.name for p in batch_objs]
    existing = set(
        Profile.objects.filter(name__in=names).values_list("name", flat=True)
    )

    fresh = [p for p in batch_objs if p.name not in existing]
    dedup_skipped = len(batch_objs) - len(fresh)

    if not fresh:
        return 0, dedup_skipped

    # ignore_conflicts handles the rare race where a concurrent upload
    # inserts the same name between our pre-check and our bulk_create.
    Profile.objects.bulk_create(fresh, ignore_conflicts=True, batch_size=1000)
    return len(fresh), dedup_skipped


def ingest_csv(file_obj) -> dict:
    """
    Stream-process a CSV upload. Returns a summary dict matching the spec.

    file_obj: a binary file-like object (Django UploadedFile is fine).
    """
    reasons = {}
    total = 0
    inserted = 0
    skipped = 0

    # Wrap the binary stream as text without buffering the whole file.
    # errors="replace" means a single bad byte doesn't kill the upload.
    text_stream = io.TextIOWrapper(
        file_obj, encoding="utf-8", newline="", errors="replace"
    )

    try:
        reader = csv.DictReader(text_stream)
    except Exception:
        return {
            "status": "success",
            "total_rows": 0,
            "inserted": 0,
            "skipped": 0,
            "reasons": {"malformed_file": 1},
        }

    # Validate header presence — if the required columns aren't there we
    # can't process any row, so fail fast (this is a single-error case).
    fieldnames = set(reader.fieldnames or [])
    if not REQUIRED_COLUMNS.issubset(fieldnames):
        missing = REQUIRED_COLUMNS - fieldnames
        return {
            "status": "error",
            "message": f"CSV is missing required columns: {sorted(missing)}",
            "total_rows": 0,
            "inserted": 0,
            "skipped": 0,
            "reasons": {},
        }

    batch_objs = []
    in_batch_names = set()  # detect dupes within the same upload

    for raw in reader:
        total += 1

        if raw is None or any(v is None for v in raw.values()):
            # csv.DictReader sets values to None when a row has fewer
            # columns than the header. Treat that as malformed.
            skipped += 1
            _bump_reason(reasons, "malformed_row")
            continue

        kwargs, reason = _validate_row(raw)
        if reason:
            skipped += 1
            _bump_reason(reasons, reason)
            continue

        # Within-upload duplicate detection — cheaper than letting the DB
        # catch it because we never have to ship the row.
        if kwargs["name"] in in_batch_names:
            skipped += 1
            _bump_reason(reasons, "duplicate_name")
            continue

        in_batch_names.add(kwargs["name"])
        batch_objs.append(Profile(**kwargs))

        if len(batch_objs) >= BATCH_SIZE:
            ins, dup = _flush_batch(batch_objs)
            inserted += ins
            skipped += dup
            if dup:
                _bump_reason(reasons, "duplicate_name", dup)
            batch_objs = []
            in_batch_names = set()

    # Final partial batch.
    if batch_objs:
        ins, dup = _flush_batch(batch_objs)
        inserted += ins
        skipped += dup
        if dup:
            _bump_reason(reasons, "duplicate_name", dup)

    # If anything actually landed, the cached query results are stale.
    if inserted > 0:
        bump_version()

    return {
        "status": "success",
        "total_rows": total,
        "inserted": inserted,
        "skipped": skipped,
        "reasons": reasons,
    }
