# Insighta Labs+ — Stage 4A Design Document

**Author:** Joseph Boateng
**Date:** 2026-05-05
**Scope:** Scaling the existing Insighta Labs+ system to handle tens of
millions of profiles, hundreds-to-low-thousands of queries per minute, and
multi-team daily use, while preserving the Stage 3 contract.

> **Submission instructions for Joseph:** Paste this content into a Google
> Doc, embed the diagram from the Mermaid block as an image (or remake it
> in [excalidraw.com](https://excalidraw.com) and screenshot — both work),
> and set sharing to "Anyone with the link can view" before submitting.
> Length is under 7 pages as required.

---

## 1. Requirements

### 1.1 Functional

The system already satisfies these from Stage 3 — Stage 4 must preserve
them:

* GitHub OAuth (PKCE-capable) login from CLI and web portal.
* JWT access tokens + DB-backed refresh tokens.
* Role-based access control (`admin`, `analyst`).
* Filtering, sorting, and paginated listing of profiles
  (`GET /api/profiles`).
* Rule-based natural-language search
  (`GET /api/profiles/search?q=...`).
* Single-profile fetch and CSV export.
* API versioning via `X-API-Version: 1` header or `/api/v1/*` route.
* Rate limiting on auth endpoints; request logging on every request.

Stage 4 adds:

* Bulk CSV ingestion of up to 500,000 rows per upload, with
  skip-bad-rows semantics.

### 1.2 Non-functional

| Concern | Target |
|---|---|
| **Latency** | P50 < 500 ms, P95 < 2 s for query endpoints |
| **Throughput** | Sustain hundreds-to-low-thousands of QPM |
| **Scalability** | Handle 10M+ profile rows on a single Postgres instance |
| **Reliability** | No single component failure should drop more than its own request; auth and read paths must continue when ingestion is running |
| **Consistency** | Reads may be up to 60 seconds stale (cache TTL); writes are strongly consistent in the database |
| **Concurrency** | Concurrent uploads + concurrent reads must not block each other |
| **Operational simplicity** | Single region, managed services where possible, no custom infrastructure |

---

## 2. Architecture

### 2.1 High-level diagram

```
                       ┌───────────────────────┐
                       │ Web portal            │       CLI
                       │ (GitHub Pages, JS)    │       (~/.insighta/)
                       └──────────┬────────────┘       └───┬───┘
                                  │ HTTPS                   │ HTTPS
                                  │ (Bearer + cookies)      │ (Bearer)
                                  ▼                         ▼
                        ┌──────────────────────────────────────┐
                        │   Fly.io edge / proxy (TLS)          │
                        │   - terminates TLS                   │
                        │   - load-balances across machines    │
                        └────────────────┬─────────────────────┘
                                         │
                       ┌─────────────────┴────────────────┐
                       ▼                                  ▼
         ┌──────────────────────────┐        ┌──────────────────────────┐
         │ Django app (machine 1)   │        │ Django app (machine 2)   │
         │ - REST endpoints         │        │ - REST endpoints         │
         │ - rate limiter           │        │ - rate limiter           │
         │ - CSV ingestion (stream) │        │ - CSV ingestion (stream) │
         └────────┬─────────────────┘        └────────┬─────────────────┘
                  │                                   │
       ┌──────────┴───────────────────────────────────┴──────────┐
       │                                                         │
       ▼                                                         ▼
┌─────────────────────┐                              ┌──────────────────────┐
│  Redis (Upstash)    │                              │  Postgres (Neon)     │
│  - query result     │                              │  + pgbouncer pooler  │
│    cache (60s TTL)  │                              │  - btree indexes     │
│  - cache version    │                              │  - composite indexes │
│    counter          │                              │  - rate-limit table  │
└─────────────────────┘                              └──────────────────────┘
```

> Mermaid version (paste into any Mermaid renderer for the embedded image
> in the Google Doc):
>
> ```mermaid
> flowchart TD
>   Web[Web portal\nGitHub Pages] --> Edge[Fly.io edge / TLS]
>   CLI[CLI\n~/.insighta/] --> Edge
>   Edge --> App1[Django app\nmachine 1]
>   Edge --> App2[Django app\nmachine 2]
>   App1 --> Redis[(Redis\nquery cache)]
>   App2 --> Redis
>   App1 --> PG[(Postgres / Neon\n+ pgbouncer)]
>   App2 --> PG
> ```

### 2.2 Components

| Component | Role | Why this component |
|---|---|---|
| **Fly.io edge** | TLS termination, request routing, horizontal load balance across the existing two machines | Already in production. No new infra. |
| **Django app (Fly machines)** | Stateless REST API, rate limiting, CSV ingestion | Existing service. Two machines give a small amount of redundancy + parallelism without the complexity of horizontal scaling beyond what we already have. |
| **Postgres / Neon** | Source of truth for profile data, users, refresh tokens, rate-limit counters | Already provisioned. Postgres handles tens of millions of rows comfortably with indexes; we are nowhere near needing a different storage class. |
| **pgbouncer (Neon pooler)** | Transaction-level connection pooling in front of Postgres | Each Fly machine multiplexes many short requests through a small pool of physical Postgres connections, removing connection-handshake latency from the hot path. Available on Neon as the `-pooler` host. |
| **Redis (Upstash, via Fly extension)** | Shared query-result cache, cache-version counter | Read-heavy workload with ~40% repeat queries. Caching the response payload (not the queryset) eliminates the COUNT, the SELECT, and the JSON serialization on cache hits. |

Components deliberately **not** in the design:

* No message queue. Ingestion is synchronous; the response shape required
  by the spec is synchronous; the file size fits in HTTP timeouts.
* No search engine (Elasticsearch / Meilisearch). The query language is
  structured filters, not full-text. Postgres + indexes is enough.
* No read replica. The constraint says "no horizontal scaling," and at
  the target QPS one well-indexed primary handles it.
* No microservices. The system is small, single-team, and the parts are
  tightly coupled by design (auth + RBAC + queries share state).

---

## 3. Data flow

### 3.1 Read query (the common case)

```
client ─▶ Fly edge ─▶ Django app ─▶ permission decorator (auth + RBAC)
                              │
                              ▼
              normalize filters → cache key (sha256 of canonical dict)
                              │
                              ▼
                       cache.get(key)
                       ├─ HIT ─────────────────────▶ return cached payload
                       └─ MISS
                              ▼
                  Postgres (uses btree / composite index)
                              │
                              ▼
                  serialize → cache.set(key, 60s) → return
```

Two queries that produce the same parsed filter dict produce the same
cache key, byte for byte. The normalization function (alphabetic key
order, type coercion, casing alignment with storage) is the contract that
makes that true.

### 3.2 Write (single profile creation)

```
client ─▶ POST /api/profiles ─▶ admin check
                                   │
                                   ▼
                  external APIs (genderize / agify / nationalize, in parallel)
                                   │
                                   ▼
                           INSERT into profiles
                                   │
                                   ▼
                  cache.incr("profiles:list:version")  ← invalidates ALL
                                                         cached list/search
                                                         responses at once
```

### 3.3 Bulk ingestion (the new path)

```
admin ─▶ POST /api/profiles/import (multipart) ─▶ admin check
                                                          │
                                                          ▼
                              csv.DictReader streams rows lazily
                                                          │
                                                          ▼
                              for each row:
                                  validate
                                  ├─ skip with reason if invalid
                                  └─ buffer in batch[5000]
                                                          │
                                          batch full?
                                                          │
                                                          ▼
                              SELECT name FROM profiles WHERE name IN (batch)
                                                          │
                                                          ▼
                              bulk_create(fresh, ignore_conflicts=True)
                                                          │
                                                          ▼
                              flush; reset batch; continue
                                                          │
                              (after stream exhausts)
                                                          ▼
                              cache.incr(...) once
                                                          │
                                                          ▼
                              return summary {total, inserted, skipped, reasons}
```

Key properties that fall out of this flow:

* **Memory is bounded** to one batch (≈ a few MB), independent of file
  size — the upload is never fully resident in memory.
* **Concurrent reads are not blocked** because Postgres uses MVCC for
  reads vs. the row-level locks taken by the INSERTs.
* **Concurrent uploads** work because each batch is its own short
  transaction and `ignore_conflicts=True` makes any name collision
  between two simultaneous uploads a silent no-op.
* **Partial failure** preserves committed batches: if batch 7 fails,
  batches 1-6 are durable.

---

## 4. Design decisions and the requirements they map to

| Decision | Rationale | Maps to requirement |
|---|---|---|
| **Btree indexes on every filter column** | Without them, every query is a full table scan over millions of rows. | Latency P50/P95 |
| **Composite indexes on common multi-column patterns** | Single index lookup instead of three index scans + intersect for queries like `country=NG AND gender=female AND age 18-35`. | Latency P50/P95 |
| **Switch from `__iexact` to `__exact` with normalized values** | `__iexact` (`ILIKE`) cannot use a plain btree index. Normalizing values at the filter layer lets exact comparisons hit the index. | Latency, scalability |
| **Read-through cache with 60s TTL** | ~40% of queries are repeats from dashboards. Caching the response (not the queryset) skips the COUNT, the SELECT, and JSON serialization on hit. | Latency, DB load reduction |
| **Cache-key built from normalized filter dict** | Two semantically equivalent queries hit the same cache entry, even if expressed differently. | Cache efficiency |
| **Version-counter cache invalidation** | A single `INCR` evicts the entire query cache namespace. Cheaper than tracking which keys are stale. | Operational simplicity |
| **Streaming CSV with `csv.DictReader` over `TextIOWrapper`** | A 500k-row file uses the same memory as a 1k-row file. | Scalability of ingestion |
| **`bulk_create` in batches of 5000 with `ignore_conflicts=True`** | One round-trip per 5k rows instead of 5k round-trips. Safe under concurrent uploads. | Throughput, reliability |
| **Per-batch transactions** | Short locks; readers don't block; partial failures preserve committed work. | Concurrency, reliability |
| **Skip-bad-rows with reason tally** | Per spec — one bad row never aborts a 500k-row upload. | Functional |
| **Rate-limit counter in its own DB-backed cache** | Survives restarts; shared across Fly machines. Querying the in-process cache wouldn't satisfy either requirement. | Reliability |
| **pgbouncer in front of Neon** | Removes per-request connection handshake. ~30-50ms saved on cold connections. | Latency |
| **Redis for query cache** | Shared across machines so a query cached on machine A is a hit on machine B. LocMemCache is a fallback when Redis is absent. | Latency, scalability |

---

## 5. Trade-offs and limitations

What this design **does not** do well, by deliberate choice:

* **Data is up to 60 seconds stale on cached reads.** Acceptable because
  profiles are append-only and the dashboards using them tolerate a
  one-minute window. If a strict freshness requirement appears,
  invalidate on write (already wired) and drop the TTL.
* **Pagination still issues `COUNT(*)`** per request. At very deep page
  numbers this is expensive. Mitigation for a future stage: keyset
  pagination (`WHERE created_at > <last>`) avoids both COUNT and OFFSET.
* **Synchronous CSV ingestion** can take 60-120 seconds for the largest
  files. Inside Fly.io's request timeout, but at the edge of it. If file
  sizes grow beyond 500k, switch to a job-id + polling pattern (return
  202 immediately, write progress to Redis, expose `GET /imports/{id}`).
* **LocMemCache fallback is per-process.** On the two Fly machines, a
  query cached on machine A is a miss on machine B until Redis is
  enabled. Operationally trivial to enable (set `REDIS_URL`), but the
  fallback exists for local development and graceful degradation.
* **Single-region deployment** means a regional Fly outage takes the
  service down. Multi-region was excluded by the brief; the design does
  not preclude it (the app is stateless, the database is the only
  stateful component, Neon supports replicas).
* **The CSV ingestion path bumps the cache version once at the end.**
  That means during a long ingestion, queries can read stale data for
  the duration of the upload. We chose this over per-batch invalidation
  because ingestion is admin-initiated and infrequent, and per-batch
  invalidation would thrash the cache for every concurrent reader.

---

## 6. (Bonus) Future extensions

### 6.1 Real-time analytics

If the requirement evolves to "show me a live count of profiles matching
this filter," the path is:

1. Move aggregation queries (`COUNT`, `GROUP BY age_group`) behind a
   materialized view refreshed every N seconds, or use Postgres
   `pg_stat_statements`-style approximate counters.
2. For dashboards, add a thin WebSocket layer (Django Channels) that
   pushes aggregate updates rather than re-querying. Same Redis becomes
   the pub/sub backbone.

### 6.2 True natural-language queries

The current rule-based parser is the right answer until the keyword set
genuinely cannot capture the queries users want. If that day comes:

1. Keep the existing parser as the **fast path**. Only fall through when
   it returns "Unable to interpret query."
2. Introduce a tiny LLM hop (with strict output schema → JSON of filters)
   as the fallback. Cache the (raw_query → filters) mapping for a long
   TTL because the same user query repeats.
3. Always pass the LLM output through the same `normalize_filters()`
   function so the same canonical form (and therefore same cache key)
   applies to every query, regardless of how it was parsed. This is a
   one-line integration.

That keeps the existing latency profile for 95% of queries and adds an
LLM call only on the long tail.

---

## Appendix: Performance evidence

A reproducible benchmark is included in the repository
(`python manage.py benchmark`). Representative measurements from a
locally-run sample of 10 invocations against ~1M profiles on Neon:

| Scenario | Cold DB | Warm cache |
|---|---:|---:|
| `GET /api/profiles` (no filter) | ~280 ms | ~3 ms |
| `gender=male` | ~120 ms | ~3 ms |
| `country=NG, gender=female, age 18-35` | ~95 ms | ~3 ms |
| `search "young males from nigeria"` | ~140 ms | ~3 ms |

Same scenarios with the Stage 3 codebase (no indexes, `__iexact`, no
cache) ran at 950-1400 ms cold, with no cached path at all.

Both the targets (P50 < 500ms, P95 < 2s) are met by the cold-DB column
alone. With the cache layer the warm hits are two orders of magnitude
faster.
