# ANSWERS.md

## Part B — Diagnose three broken snippets

### Snippet 1 — overdue report view

**1. What is wrong?**
- **N+1 queries**: `c.asset.name`, `c.asset.asset_tag`, and `c.employee.full_name` are each accessed inside the loop without `select_related`. For N open checkouts this issues roughly `1 + 2N` queries instead of 1.
- **Filtering and sorting happen in Python, not the database**: the `if c.due_at < timezone.now()` check and `rows.sort(...)` both run after loading every open checkout into memory. This doesn't scale — the whole open-checkout table is pulled into the app process every time.
- **No pagination**: for tens of thousands of overdue rows, the entire result set is serialized into one `JsonResponse` payload.
- **No authentication**: this is a plain Django view with no permission check, inconsistent with the rest of the API requiring auth.
- **`timezone.now()` is called multiple times** across the loop rather than captured once — a minor correctness/consistency issue at scale (rows near the boundary could be evaluated against slightly different "now" values).

**2. Why does it look correct in local testing?**
With a handful of test rows, N+1 queries are invisible (sub-millisecond either way), the full result fits trivially in memory, and a developer manually hitting the view during dev typically isn't testing the auth boundary or generating thousands of rows.

**3. How would you fix it?**
```python
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone

@api_view(["GET"])
def overdue_report(request):
    now = timezone.now()
    checkouts = (
        CheckOut.objects.filter(returned_at__isnull=True, due_at__lt=now)
        .select_related("asset", "employee")
        .order_by("due_at")
    )
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(checkouts, request)
    rows = [
        {
            "asset": c.asset.name,
            "asset_tag": c.asset.asset_tag,
            "employee": c.employee.full_name,
            "days_overdue": (now - c.due_at).days,
        }
        for c in page
    ]
    return paginator.get_paginated_response(rows)
```

**4. What test or tooling would have caught this before it shipped?**
`django.test.utils.assertNumQueries` in a unit test with 3+ seeded rows would immediately catch the N+1 (query count would scale with row count instead of staying constant). Django Debug Toolbar in local dev makes N+1s visually obvious. A test asserting a 401 for an unauthenticated request catches the missing permission check.

---

### Snippet 2 — check-out endpoint

**1. What is wrong?**
- **No transaction wrapping the create + status update** — violates rule 5 (both must succeed or both must fail atomically).
- **No row locking** — the read-then-write on `asset.status` is a check-then-act race; two simultaneous requests can both pass the `status != "AVAILABLE"` check before either commits, double-checking-out the same asset. This is exactly the race rule 7 requires closing at the DB level.
- **No handling of `DoesNotExist`** — an unknown `asset_tag` or `employee_code` raises an unhandled exception, producing a 500 instead of the required 404 (rule 8).
- **No active-employee check** — missing entirely (rule 2).
- **No `due_at` validation** — no future/30-day-window check (rule 4), and `request.data["due_at"]` is passed straight into `CheckOut.objects.create` without parsing/validation.
- **The 3-open-checkout count check has the same race condition** as the asset status check — two simultaneous requests for the same employee (different assets) can both pass `open_count >= 3` before either commits.
- **Direct dict access (`request.data["asset_tag"]`)** raises `KeyError` → 500 on a missing field, instead of a 400.

**2. Why does it look correct in local testing?**
Manual single-request testing with known-good data (an existing asset, an active employee, a valid `due_at`) never exercises the 404/400 paths or the race conditions, which only surface under concurrent load or malformed input — neither of which shows up in casual "does the happy path work" testing.

**3. How would you fix it?**
```python
from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, ValidationError
from datetime import timedelta
from django.utils import timezone

@api_view(["POST"])
def check_out_asset(request):
    asset_tag = request.data.get("asset_tag")
    employee_code = request.data.get("employee_code")
    due_at_raw = request.data.get("due_at")
    if not all([asset_tag, employee_code, due_at_raw]):
        raise ValidationError("asset_tag, employee_code, and due_at are required.")

    # due_at arrives as a JSON string, not a datetime -- must parse before
    # comparing it against timezone.now(), otherwise this raises TypeError.
    due_at = parse_datetime(due_at_raw)
    if due_at is None:
        raise ValidationError("due_at must be a valid ISO 8601 datetime.")

    try:
        asset = Asset.objects.get(asset_tag=asset_tag)
    except Asset.DoesNotExist:
        raise NotFound("Asset not found.")
    try:
        employee = Employee.objects.get(employee_code=employee_code)
    except Employee.DoesNotExist:
        raise NotFound("Employee not found.")

    if not employee.is_active:
        raise ValidationError("Employee is not active.")

    now = timezone.now()
    if due_at <= now or due_at > now + timedelta(days=30):
        raise ValidationError("due_at must be within the next 30 days.")

    with transaction.atomic():
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        employee = Employee.objects.select_for_update().get(pk=employee.pk)

        if asset.status != "AVAILABLE":
            return Response({"detail": "not available"}, status=409)

        if CheckOut.objects.filter(employee=employee, returned_at__isnull=True).count() >= 3:
            return Response({"detail": "limit reached"}, status=409)

        checkout = CheckOut.objects.create(asset=asset, employee=employee, due_at=due_at)
        asset.status = "CHECKED_OUT"
        asset.save(update_fields=["status"])

    return Response({"id": checkout.id}, status=201)
```

**4. What test or tooling would have caught this before it shipped?**
A concurrency test (two threads checking out the same asset simultaneously, asserting exactly one 201) would directly catch the race. Unit tests for each 4xx/404 path — unknown asset, inactive employee, past `due_at`, missing field — would catch the rest. A code review checklist item ("does this read-then-write flow use `transaction.atomic` + `select_for_update`?") catches this pattern before merge.

---

### Snippet 3 — nightly notice task

**1. What is wrong?**
- **No idempotency guard** — `OverdueNotice.objects.create()` runs unconditionally for every overdue checkout, every time the task runs. Re-running it (retries, a Beat misfire) creates duplicate notices per checkout.
- **Passing Django model instances into a Celery task's arguments** (`deliver_email.delay(c.employee, c)`) — Celery serializes task arguments (typically JSON by default); a model instance isn't JSON-serializable and this will either fail at call time or require the far less safe `pickle` serializer.
- **Loading the full queryset into memory without chunking** (`for c in overdue`) — at tens of thousands of rows this is a large memory footprint and a long-running, unbroken loop.
- **No per-row error isolation** — one row's failure (e.g. an `IntegrityError` from a duplicate) aborts the whole loop, leaving the remaining overdue rows unprocessed for that run.
- **The return value is misleading**: `overdue.count()` re-queries the database (separate from the already-iterated queryset) and reports the count of *overdue checkouts processed*, not notices actually created — worse, the label "sent" is inaccurate since nothing was actually sent synchronously, only queued.

**2. Why does it look correct in local testing?**
A single manual run against a small dataset creates the expected notices and looks fine. Duplicate-notice risk only appears on a *second* run, which isn't something a developer typically tests for by default. Local Celery setups often run in eager/synchronous mode with permissive serialization during dev, which can mask the model-instance-serialization problem until it hits a real worker with the production `JSON` serializer.

**3. How would you fix it?**
```python
from celery import shared_task
from django.utils import timezone
from django.db import IntegrityError

@shared_task
def send_overdue_notices():
    today = timezone.localdate()
    overdue = CheckOut.objects.filter(
        returned_at__isnull=True, due_at__lt=timezone.now()
    )
    created = 0
    for c in overdue.iterator(chunk_size=500):
        try:
            _, was_created = OverdueNotice.objects.get_or_create(
                checkout=c, notice_date=today
            )
        except IntegrityError:
            was_created = False
        if was_created:
            created += 1
            deliver_email.delay(c.employee_id, c.id)
    return f"created {created} notices"
```
`get_or_create` against the `(checkout, notice_date)` unique constraint makes re-runs idempotent by construction. `.iterator(chunk_size=...)` avoids loading the entire queryset at once. Only IDs are passed to `deliver_email`, which re-fetches inside its own task body.

**4. What test or tooling would have caught this before it shipped?**
Running the task twice in a test and asserting exactly one notice per checkout catches the idempotency bug directly (this is the exact test built for Part A's `flag_overdue_checkouts`). A test asserting task arguments are JSON-serializable (or simply running it through a real worker with `CELERY_TASK_SERIALIZER=json` in CI, not eager mode) would catch the model-instance-argument bug before production.

---

## Part C — Optimise a slow PostgreSQL query

**1. Rewritten query**
```sql
SELECT c.*
FROM checkouts c
JOIN employees e ON e.id = c.employee_id
WHERE c.checked_out_at >= '2026-01-01 00:00:00+00'
  AND c.checked_out_at <  '2026-07-01 00:00:00+00'
  AND c.returned_at IS NULL
  AND e.is_active = true
ORDER BY c.due_at ASC;
```
Changes and why:
- **`DATE(c.checked_out_at) BETWEEN ...` → a half-open range on the raw `timestamptz` column.** Wrapping a column in a function makes it non-sargable — Postgres can't use a plain b-tree index on `checked_out_at` when the column is transformed for every row; it effectively forces evaluating `DATE()` per row. A native range comparison lets a standard index be used directly, and the half-open form (`>=` start, `<` day-after-end) avoids the subtle ambiguity of comparing a truncated date against date-string boundaries.
- **`employee_id IN (subquery)` → `JOIN`.** Semantically equivalent here (`employees.id` is a primary key, so no duplication risk), and gives the planner more freedom over join strategy. Modern Postgres often flattens `IN` subqueries into an equivalent semi-join automatically, so the performance gain may be marginal — but the rewrite removes reliance on that optimization and is more transparent to a future reader.
- **`SELECT *` narrowed to `c.*`** — avoids unintentionally pulling `employees` columns; worth further narrowing if the actual report screen doesn't need every `checkouts` column (e.g. `condition_note` is a `TEXT` field that may be unused on this screen).

**2. Indexes**
```sql
-- Supports the WHERE-clause filter on open checkouts within a date range.
-- Partial (WHERE returned_at IS NULL) because open checkouts are presumably
-- a small, relatively stable fraction of the 4.2M rows -- a partial index
-- only stores entries for that subset, staying far smaller and cheaper to
-- maintain than a full index across every row.
CREATE INDEX idx_checkouts_open_checked_out_at
ON checkouts (checked_out_at)
WHERE returned_at IS NULL;

-- Alternative/complementary: supports ORDER BY due_at directly (avoiding a
-- separate sort step) at the cost of scanning by due_at order and filtering
-- checked_out_at as a row filter rather than an index condition.
CREATE INDEX idx_checkouts_open_due_at
ON checkouts (due_at)
WHERE returned_at IS NULL;
```
I would **not** add an index on `employees.is_active`: the table is only ~12,000 rows, so a sequential scan there is already cheap (sub-millisecond), and a low-cardinality boolean column is a poor index candidate regardless of table size — it wouldn't meaningfully narrow the row set.

Whether the first or second index (or both) actually earns its place — specifically whether the planner prefers scanning by `checked_out_at` and sorting afterward, versus scanning by `due_at` in order and filtering the date range inline — depends on the actual selectivity of the date range and the open/returned ratio, which I can't determine from the schema alone. See point 5.

**3. Expected `EXPLAIN (ANALYZE, BUFFERS)` before/after**
Before: I'd expect a **Seq Scan** on `checkouts` (4.2M rows) as the base node, with a large **"Rows Removed by Filter"** count, since `DATE()` prevents any index use and there's no index supporting `returned_at IS NULL` either. I'd also expect a **Sort** node above it for `ORDER BY due_at`, likely with significant time/memory if `work_mem` is exceeded (spilling to disk as an external sort). Total execution time near or over the observed ~8s.

After: I'd expect a **Bitmap Index Scan** or **Index Scan** on the new partial index feeding the rest of the plan, with **"Rows Removed by Filter"** close to zero at that node (most filtering now happens via the index condition, not a post-scan filter). The line that tells you definitively whether it worked is the **`Execution Time`** at the very bottom of the `ANALYZE` output, cross-checked against **`Buffers: shared hit=X read=Y`** showing far fewer block reads than before.

**4. What breaks first as the table grows (+8,000 rows/day)?**
Unfixed, the current query degrades linearly forever since it's a full sequential scan — it will keep getting slower and the 10-second timeout will be hit permanently, not intermittently. Fixed, the partial index should stay small as long as the *proportion* of open checkouts stays roughly constant (most equipment eventually gets returned) — but if that ratio ever drifts (slower turnaround, process changes), the partial index grows with it. Longer-term, at millions of rows and thousands of daily writes, **autovacuum/analyze falling behind** is the more likely first failure: stale planner statistics after a burst of writes can cause the planner to silently abandon the index and revert to a sequential scan, reproducing the original problem with no code change. I'd proactively monitor `pg_stat_user_tables` (`last_autovacuum`, `last_analyze`, `n_dead_tup`) and consider more aggressive `autovacuum_analyze_scale_factor` tuning on this specific table. If growth continues for years, monthly/quarterly partitioning on `checked_out_at` would let date-range queries prune entire partitions.

**5. What would I want to measure on the real database first?**
Real `EXPLAIN (ANALYZE, BUFFERS)` output against production data, plus `pg_stats` for the actual selectivity of `returned_at IS NULL` and the size of the `checked_out_at` date range relative to the whole table. Index and composite-ordering decisions on a 4.2M-row table are genuinely guesses without this — I can't know from the schema alone whether the `checked_out_at`-led or `due_at`-led index wins, or whether both are worth the write overhead of maintaining two indexes.

---

## Part D — Production reasoning

### D1. Zero-downtime migration

I'd stage this across three or four deploys, never combining "add the constraint" with "change what app code writes" in the same step:

1. **Deploy N**: add `location_id` as a nullable FK, no default. This is a fast, metadata-only change in Postgres (no table rewrite) — old app code, unaware of the column, keeps working unchanged.
2. **Deploy N+1**: app code starts *writing* `location_id` on every new/updated checkout, while the column stays nullable. During the rolling restart across the 4 instances, some requests hit old code (doesn't write it) and some hit new code (does) — this is safe precisely because the column still allows null.
3. **Backfill**: once all 4 instances confirm running N+1 (so no new nulls are being created), backfill historical rows in small batches (e.g. by primary-key range, with brief pauses between batches) rather than one large `UPDATE`, to avoid long lock waits, WAL bloat, and replication lag spikes.
4. **Deploy N+2**: add the `NOT NULL` constraint via `ADD CONSTRAINT ... CHECK (location_id IS NOT NULL) NOT VALID`, then `VALIDATE CONSTRAINT` — this validates without holding a long exclusive lock for the whole scan. Postgres 12+ can then use this validated constraint to add `NOT NULL` itself without a second full-table scan.

The specific thing that would lock the table if done wrong: a single, naive `ALTER TABLE checkouts ALTER COLUMN location_id SET NOT NULL` without a pre-validated constraint takes an `ACCESS EXCLUSIVE` lock for the duration of a full-table scan verifying no nulls exist — on 4.2M rows, with 4 live app instances, this would block all reads and writes for the scan's duration, effectively an outage.

### D2. Latency triage

I'd check things in order of cost and how quickly each rules something in or out:
1. **Request volume/error-rate dashboard** — rules in/out a traffic spike versus a genuine per-query slowdown at normal load.
2. **`EXPLAIN ANALYZE` the live query against production** — the single most informative check; tells me directly whether the query plan changed (e.g., an index scan replaced by a sequential scan).
3. **Table/row growth trend for `checkouts`** — since the table grows daily, I'd check whether the "open+overdue" row count recently crossed a threshold where Postgres's planner flips its cost estimate from index scan to sequential scan (a well-known behavior around roughly 5–10% of a table).
4. **`pg_stat_user_tables` for `last_analyze`/`last_autovacuum`** — stale statistics after a write burst can cause a bad plan choice independent of data volume; a quick `ANALYZE checkouts` and re-testing tells me immediately if this was it.
5. **Table bloat / dead tuples** — heavy write activity without adequate vacuuming degrades scan performance even without row-count growth.
6. **Infra-level**: connection pool saturation, replica lag, or an unrelated scheduled job (backup, batch import) competing for resources at this time of day.

Given no deploy in 9 days, the two most likely causes: **(a)** the open/overdue row count crossed a planner threshold causing an index-to-seq-scan plan flip — confirmed by comparing today's `EXPLAIN` output against a known-good baseline; **(b)** stale planner statistics after normal write volume outpaced autovacuum — confirmed by manually running `ANALYZE checkouts` and re-testing immediately; if latency drops right after, that's strong confirmation.

### D3. CI/CD and safety

**On pull request**: lint/format check, `makemigrations --check --dry-run` to catch missing migrations, and the full test suite run against a real Postgres service container (not SQLite) so migration and query behavior is representative of production.

**On merge to main**: re-run the same suite (protects against a race between two PRs merging close together), then build and tag the Docker image (commit SHA, optionally a semantic version) and push to a registry. A slower integration suite that's too costly for every PR can run here instead.

**Gating a production deploy**: require the build+test pipeline to have passed on main, plus a manual (or strictly automated) approval step. Migrations are applied as their own distinct step, using the backward-compatible staging discipline from D1, *before* the new app version receives any traffic — so at every point during the rollout, whichever app version is currently running (old or new) is compatible with whatever schema state currently exists. Post-deploy, automated health checks (hitting `/health/` and a smoke-test suite) gate whether the rollout is considered successful, with an automatic rollback trigger on failure.

**Rollback story once the schema has already migrated**: rolling back application code is cheap — redeploy the previous image — but this only works because migrations were required to be additive/backward-compatible in the first place. Reversing an already-applied migration in production (e.g. dropping a column just added) is generally *not* the rollback plan; it risks data loss and reintroduces the same locking risk the careful forward migration was designed to avoid. In practice, "rollback" almost always means "redeploy the previous good app image" while leaving the schema in its new superset state — which is exactly why D1's staged approach matters: it guarantees old code can coexist safely with the new schema for as long as a rollback might be needed.
