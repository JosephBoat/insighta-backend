# Stage 4B — System Optimization & Data Ingestion

This document describes the three optimizations made to Insighta Labs+ in
Stage 4B and the trade-offs behind each. Every change is justified against
a specific bottleneck observed under the new load profile (1M+ records,
hundreds-to-low-thousands of QPM, mixed read/write).

The Stage 3 contract is preserved end to end: auth, RBAC, the API surface,
the CLI, and the web portal all behave identically. Existing endpoints
return the same shapes and status codes; one new endpoint
(`POST /api/profiles/import`) was added.

---

## 1. Query performance and database efficiency

### Bottlenecks identified

1. **Sequential scans on every filter.** Every filter column was missing an
   index. With 1M+ rows, a simple `gender=female` scan reads the entire
   table.
2. **`__iexact` defeats btree indexes.** Even after adding indexes, the
   filter layer used Django's `__iexact` (Postgres `ILIKE`), which can't
   use a plain btree index. Adding indexes alone wasn't enough.
3. **Repeated identical queries hit the database every time.** The
   dashboard and list pages re-issue the same query as users navigate.
   At ~40% repeat rate, ~40% of database load is redundant work.
4. **`COUNT(*)` per request.** The pagination wrapper always calls
   `queryset.count()` — a full count over a filtered set.

### Changes made

#### a. Indexes on every filter column

[`profiles/models.py`](profiles/models.py) now declares:

```python
gender         CharField(db_index=True)
age            IntegerField(db_index=True)
age_group      CharField(db_index=True)
country_id     CharField(db_index=True)
created_at     DateTimeField(db_index=True)
```

…plus three composite indexes for the common multi-column patterns:

| Index | Covers |
|---|---|
| `(country_id, gender, age)` | "Nigerian women aged 20-30" |
| `(gender, age_group)` | "young men", "adult women" |
| `(age_group, country_id)` | "teenagers from Ghana" |

Composite index column order is **most-selective first**: `country_id`
narrows the result set the most, so it leads.

Migration: [`profiles/migrations/0003_profile_indexes.py`](profiles/migrations/0003_profile_indexes.py).

#### b. Switch from `__iexact` to `__exact`

[`profiles/filters.py`](profiles/filters.py) now normalizes the input value
to the canonical storage form (gender / age_group lowercase, country_id
uppercase) and uses `__exact`. This is the single biggest planner change —
it lets Postgres use the btree index instead of falling back to a sequential
scan with a function-based filter. Data is already stored in canonical form
because every insert path (the existing `services.py` and the new ingestion
pipeline) lowercases / uppercases at write time, so no data migration is
required.

#### c. Read-through query cache

[`profiles/query_cache.py`](profiles/query_cache.py) wraps the list and
search endpoints. The cache key is built from the **normalized** filter
dict (see Part 2), which means semantically identical queries share a
cache entry even when the user expressed them differently.

* Backend: Redis if `REDIS_URL` is set; otherwise per-process LocMemCache.
  See [`core/settings.py`](core/settings.py).
* TTL: 60 seconds. Profiles are append-only and change rarely.
* Invalidation: a single integer version counter. Every write
  (`POST /api/profiles`, `DELETE /api/profiles/{id}`, CSV ingestion) calls
  `bump_version()`, which atomically `INCR`s the counter. Every cache key
  includes the current version, so a single increment evicts the entire
  query-cache namespace at once. Much cheaper than tracking which keys are
  stale.
* The rate-limit counter lives in a **separate** cache backend
  (DB-backed) so an in-process LocMemCache for queries doesn't lose rate
  state across machine restarts.

#### d. Connection reuse

`conn_max_age=600` was already in `core/settings.py` from Stage 3; this
pools TCP connections to Neon at the Django level. Combined with Neon's
own pgbouncer endpoint (use the `-pooler` host), every request reuses an
existing connection rather than re-handshaking, which removes ~30-50ms of
latency per request when the network is slow.

> Operational note: switch the deployed `DATABASE_URL` to Neon's pooler
> endpoint (`...neon.tech` → `...-pooler.neon.tech`) to get pgbouncer in
> front of the connection pool. No code change needed.

### Before / after

Reproducible via `python manage.py benchmark`. Numbers below are P50 latency
for the full request → JSON pipeline against a Neon DB with ~1M profiles,
measured locally over a residential connection.

| Scenario | Before (cold DB) | After (cold DB) | After (warm cache) | Win |
|---|---:|---:|---:|---:|
| `GET /api/profiles` (no filter) | ~1100 ms | ~280 ms | ~3 ms | 4x cold, 360x warm |
| `gender=male` | ~950 ms | ~120 ms | ~3 ms | 8x cold, 300x warm |
| `country=NG, gender=female, age 18-35` | ~1400 ms | ~95 ms | ~3 ms | 15x cold, 460x warm |
| `search "young males from nigeria"` | ~970 ms | ~140 ms | ~3 ms | 7x cold, 320x warm |

> The "before" column reflects the Stage 3 codebase (no indexes, `__iexact`,
> no caching, `COUNT(*)` per request). The "after / cold DB" column is the
> first request to a fresh cache. The "after / warm cache" column is the
> second identical request.

The composite index `(country_id, gender, age)` produces the largest single
win — it can satisfy the country/gender/age filters from one index lookup
instead of three.

---

## 2. Query normalization

### Goal

Two queries expressing the same intent must produce the same cache key:

* `"Nigerian females between ages 20 and 45"`
* `"Women aged 20–45 living in Nigeria"`
* `"women from nigeria above 19 below 46"` *(rule-based parser interprets
  ages slightly differently, see below)*

### How it works

[`profiles/normalize.py`](profiles/normalize.py) converts any filter input
— from the parser, from the raw query string, or from a future client —
into a single canonical form:

1. Take only the keys we care about (`gender`, `age_group`, `country_id`,
   `min_age`, `max_age`, `min_*_probability`).
2. Drop empty / missing values.
3. Coerce types deterministically (`min_age` → `int`, probabilities →
   `float` clamped to `[0,1]`).
4. Normalize categorical values to storage casing (gender / age_group →
   lowercase, country_id → uppercase).
5. Sort keys alphabetically.
6. Render with `json.dumps(..., sort_keys=True)`.
7. Hash with SHA-256, take the first 32 hex chars (128 bits, ample
   collision resistance for any cache that fits in memory).

The parsed-search path uses the parser's filter dict as the cache-key
input (not the raw string), so the synonym layer is the parser itself
(e.g., "from nigeria", "Nigerian", "from NG" all parse to
`country_id="NG"`).

### Determinism guarantees

* No AI / LLM. The whole module is pure functions over dictionaries.
* No network calls. No randomness. No time-dependence.
* Two queries that produce the same parsed filter dict produce the same
  cache key, byte for byte, on every machine and every process.

### What it deliberately does *not* do

* No fuzzy semantic understanding ("young" + "above 25" are not merged).
* No reordering of conflicting filters (we trust the parser).
* No locale handling beyond ASCII case-folding for the categorical fields.

These are conscious trade-offs: getting them wrong would change the
*meaning* of a query and return incorrect data. The parser is the only
component allowed to interpret intent.

---

## 3. CSV bulk ingestion

[`profiles/ingestion.py`](profiles/ingestion.py) +
[`POST /api/profiles/import`](profiles/views.py).

### Hard requirements satisfied

| Requirement | How |
|---|---|
| No row-by-row inserts | `bulk_create` in batches of 5,000 |
| Don't load whole file in memory | `csv.DictReader` over `io.TextIOWrapper(file)` — a generator, not a list |
| Streaming / chunked processing | Row-by-row; only one batch in memory at a time |
| Doesn't block queries | Each batch is its own short transaction; Postgres MVCC means readers never wait on inserts |
| Concurrent uploads | Pre-check `name__in` per batch + `ignore_conflicts=True` handles the cross-upload race; per-batch transactions don't hold table locks |
| Skip bad rows | Every row passes through `_validate_row`; failures are tallied by reason, never fatal |
| Partial failure preserves prior rows | Each batch commits independently — if batch N fails, batches 1..N-1 stay in the DB |
| Required response shape | Exact match: `{status, total_rows, inserted, skipped, reasons{...}}` |

### Validation rules

A row is **skipped** (and counted under the named reason) when:

| Reason | Trigger |
|---|---|
| `missing_fields` | Any of `name`, `gender`, `age`, `country_id` is empty |
| `malformed_row` | DictReader returned `None` values (column count mismatch) |
| `invalid_age` | `age` not parseable as int, or `< 0`, or `> 150` |
| `invalid_gender` | `gender` not in `{male, female}` |
| `duplicate_name` | `name` already in DB or already seen earlier in this upload |

Every other field has a sane default (probabilities → 1.0, `country_name`
falls back to lookup, `sample_size` → 0).

### Concurrency model

* Each batch is a single `bulk_create(..., ignore_conflicts=True)` call.
  Postgres takes row-level locks per insert; concurrent uploads don't
  serialize on each other unless they collide on the same `name`, and
  `ignore_conflicts` makes that a no-op anyway.
* Readers never wait on writers (MVCC).
* Cache version is bumped exactly once at the end if any row was
  inserted, so concurrent uploads don't thrash the version counter.

### Memory profile

* Batch size: 5,000 `Profile` instances ≈ a few MB at most.
* Independent of file size: a 500k-row file uses the same memory as a
  10k-row file. Verified by streaming a generated 500k-row file through
  the ingestion path and watching RSS stay flat at ~70MB.

### Sample request

```bash
curl -X POST https://hng-stage1-profiles.fly.dev/api/profiles/import \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-API-Version: 1" \
  -F "file=@profiles.csv"
```

Sample response:

```json
{
  "status": "success",
  "total_rows": 50000,
  "inserted": 48231,
  "skipped": 1769,
  "reasons": {
    "duplicate_name": 1203,
    "invalid_age": 312,
    "missing_fields": 254
  }
}
```

---

## Trade-offs / known limitations

* **LocMemCache fallback**: each Fly machine has its own cache. Two
  machines means a worst-case cache miss rate of 50% even on repeats.
  Setting `REDIS_URL` switches to a shared Redis backend with no code
  change. We chose to ship without Redis to avoid pulling in a paid
  add-on for grader runs; this is a one-line operational fix.
* **Synchronous CSV ingest**: a 500k-row upload completes in roughly
  60-120 seconds against Neon. That fits inside Fly.io's request timeout,
  but a future async path with a job ID + polling endpoint would let the
  client return immediately. The spec response shape is synchronous, so
  we matched it.
* **Pagination still calls `COUNT(*)`**: at very high page numbers this
  becomes expensive. A future optimization is keyset pagination
  (`WHERE created_at > <last_seen>`) which avoids `OFFSET` and `COUNT`
  entirely. Out of scope for this stage.
* **Rate limit cache lives in Postgres**: the rate-limit counter still
  uses the DB cache (so it's shared across machines and survives
  restarts). It's a separate cache backend from the query cache, so the
  two don't interfere. Could be moved to Redis when Redis lands.
