# 17 — External Distributor Transactions

**Branch:** `feat/ext-distributor-transactions` · **Date:** 2026-08-13
**Status:** implemented end-to-end and verified against the live source. The source
currently contains **zero transactions** — see §13 Known limitations.

> **Run migration `007_ext_distributor_transactions.sql` before deploying this branch.**
> The read API fails soft if it hasn't run (returns `source_available: false`), so
> deploy order is not strict.

---

## 1. Business purpose

Distributor users (`dm`) need to review the transactions their salesmen recorded.
Those transactions live in an external spreadsheet operated outside STEP, not in
the SFA handheld pipeline. This feature exposes them inside STEP as a **read-only
history** — list, filter, summarise, and drill into the products of one
transaction — scoped so a distributor sees only their own.

## 2. Data source

A Google Spreadsheet with a self-contained SFA-shaped dataset (its own users,
stores, schedules, SKUs, visits). Spreadsheet id lives in `config.py`
(`ext_tx_spreadsheet_id`), not in code paths or the frontend.

| tab | gid | role | rows (2026-08-13) |
|---|---|---|---|
| `visit` | `247800996` | transaction header | **0** |
| `visit_item` | `1151973955` | transaction items | **0** |
| `sku` | `738975456` | product names (enrichment) | 764 |
| users | `0` | — not read by this feature | 12 |
| stores | `1463936485` | — not read by this feature | 1,569 |
| schedules | `1651280713` | — not read by this feature | 12,496 |

Only the three tabs marked "read" are fetched. The workbook is currently
**readable by anyone with the link**, so the CSV-export reader needs no
credentials — see §11 and §14.

### Source schema

`visit`: `visit_id, schedule_id, visit_type, username, store_id, visit_date,
checkin_time, checkin_latitude, checkin_longitude, checkin_distance_meter,
checkin_photo_url, checkout_time, checkout_latitude, checkout_longitude,
checkout_distance_meter, checkout_photo_url, notes, duration_minutes,
total_demand, effective_call, visit_status, created_at, updated_at`

`visit_item`: `visit_item_id, visit_id, sku_id, qty, stp, demand, created_at, updated_at`

### Data conventions (established from the populated tabs of the same workbook)

| aspect | finding | handling |
|---|---|---|
| `visit_date` | day-first `DD/MM/YYYY`, sometimes unpadded (`7/1/2026`). Proven day-first: the first component reaches 31, the second never exceeds 12 | parsed day-first; stored as `DATE` |
| timestamps | ISO-8601 with explicit `Z` (`2026-06-12T05:10:13.452Z`) — already UTC | honoured as given; a *naive* value is read as Asia/Jakarta wall time |
| numbers | comma is a **thousands separator** (`89,320` = 89320 IDR, from `sku.stp`); `.` is the decimal point | `parse_number()` |
| error cells | `#N/A` appears in real data (137 of 1,569 store rows) | mapped to `NULL`, never stored as the literal text |

## 3. Join logic

```sql
visit  LEFT JOIN  visit_item  ON visit_item.visit_id = visit.visit_id
```

`LEFT`, not `INNER`: a transaction with missing detail rows is still a real
transaction and must stay in the history. Items whose parent visit is absent are
**not** loaded (counted as `orphan_items`) — they would otherwise be value with
no owner and no distributor, i.e. unscopable.

**The join never fans out the list.** Items are aggregated into
`item_count` / `computed_qty` / `computed_value` on the header **at sync time**,
so the list query reads `ext_visit` alone. One source visit with 5 items is
always exactly **1 row** in the list and 5 rows in the detail — structurally, not
by a `DISTINCT` that could be forgotten.

## 4. Field mapping

| source | canonical (`ext_visit`) | note |
|---|---|---|
| `visit_id` | `ext_visit_id` | transaction identity + MERGE key |
| `username` | `source_username` → `salesman_sk`, `salesman_name` | resolved via `dim_salesman.source_salesman_code` |
| `store_id` | `source_store_id` → `outlet_sk`, `store_name`, `distributor_code`, `brand_group` | resolved via `dim_outlet.source_outlet_code` |
| `visit_date` | `visit_date` | calendar date |
| `total_demand` | `source_total_demand` | **kept verbatim**, never overwritten |
| — | `computed_qty`, `computed_value`, `item_count` | derived from items |
| — | `total_mismatch` | source total vs item sum disagree by > 1 rupiah |

`visit_item` → `ext_visit_item`: `visit_item_id → ext_visit_item_id`,
`visit_id → ext_visit_id`, plus `sku_id, qty, stp, demand`, and `line_value`
(§5). `sku_name`/`brand`/`category` are enriched from the workbook's own `sku` tab.

When the source leaves `visit_item_id` blank, the item key is a deterministic
`sha1(visit_id|sku_id|ordinal)` so re-syncing the same sheet cannot duplicate rows.

## 5. Calculation rules

- **Line value** = the source's own `demand` when it states one, else `qty × stp`.
  The source figure is never silently replaced.
- **Transaction value** = `SUM(line_value)`, and **quantity** = `SUM(qty)`. Both
  come from the items, because the item rows are the evidence.
- `source_total_demand` is stored alongside and compared. A disagreement beyond
  1 rupiah sets `total_mismatch`, which the UI surfaces on the row and explains in
  the detail modal. **Nothing is auto-corrected** — a mismatch is a data-quality
  signal for the source owner, not something this feature should paper over.

## 6. Distributor authorization

`routers/ext_transaction.distributor_scope()` is the single choke point.

| role | scope |
|---|---|
| `ho_admin` | unrestricted (support + data quality) |
| `dm` | `distributor_code = <their own>`, taken from the JWT, never from a parameter |
| `dm` with no `distributor_code` | **sees nothing** (`AND 1=0`) — fails closed |
| anything else | `AND 1=0` (defence in depth; `require_role` already blocks them) |

The scope predicate is ANDed in **first**, and client filters can only narrow the
result — a forged `salesman_sk` or store simply matches fewer rows, never more.
The detail endpoint returns **404, not 403**, for an out-of-scope id so it cannot
be used as an existence oracle (mirrors `dependencies.assert_brand_group_allowed`).

The salesman filter list is derived from the caller's own scoped transactions, so
a distributor cannot enumerate another distributor's team.

**Which distributor owns a transaction?** The *store's* `distributor_code` from
`dim_outlet` — matching STEP's existing precedent for `dm` in `routers/visit.py`.
The sheet's own `branch` column is **not** usable: its distributor names disagree
with STEP's for the same stores (sheet "PT PERDANA ADHI LESTARI - METRO" ↔ STEP
`DST154 PT Catur Sentosa Anugerah - Metro`).

## 7. API

All under `/api/v1`, roles `dm` + `ho_admin` unless noted.

| endpoint | purpose |
|---|---|
| `GET /ext-transaction` | list + pagination + summary. Params: `from_date, to_date, salesman_sk, store, search, sort_by, sort_order, page, page_size` |
| `GET /ext-transaction/summary` | summary only, same filters |
| `GET /ext-transaction/salesmen` | salesman options within the caller's scope |
| `GET /ext-transaction/{id}` | one transaction + its items |
| `GET /ext-transaction/sync/status` | recent sync runs (**ho_admin**) |
| `POST /ext-transaction/sync` | trigger a sync (**ho_admin**) |

`sort_by` is whitelisted (`visit_date|value|quantity|items|store|salesman`) and
`sort_order` is coerced to `ASC`/`DESC` — neither reaches SQL as free text.
Everything else is a bound query parameter.

Response shape: `{ data, pagination: {page, page_size, total, total_pages,
has_next}, summary: {transactions, total_quantity, total_value, unique_stores,
unique_products, unmapped_stores}, source_available }`.

The detail route is declared **last** in the router: FastAPI matches in
declaration order, so a dynamic segment placed earlier would swallow `/summary`,
`/salesmen` and `/sync`.

## 8. Refresh / sync architecture

```
Google Spreadsheet (visit, visit_item, sku)
        │  httpx CSV export — read-only, never writes back
        ▼
services/ext_transactions.run_sync()
        │  map → validate → dedupe → attach items → derive totals
        ▼
BigQuery  sfa_web.ext_visit + ext_visit_item     (MERGE on identity, then prune stale)
        │  UPDATE … FROM dim_outlet / dim_salesman  (mapping resolved SQL-side)
        ▼
routers/ext_transaction  →  STEP web
```

Sync is triggered by `POST /ext-transaction/sync` (ho_admin) or by calling
`run_sync(triggered_by="scheduler")` from a Cloud Scheduler → Cloud Run job. Every
run writes one `ext_transaction_sync_log` row.

Mapping is re-resolved on **every** sync, so a master-data correction is picked up
without a backfill. Rows not touched by the current batch are pruned — the sheet
is a full mirror, so an untouched row was deleted upstream.

`reader` is injectable: `run_sync(reader=...)` swaps in a credentialed Sheets-API
reader later without touching mapping, dedup, or write logic (and lets tests pass
rows inline).

## 9. Caching strategy

The UI never triggers a Google request. Page interactions read BigQuery only;
Sheets is touched **once per sync run**, so there is no N+1 path by construction.
React Query holds the list 60 s and the salesman options 5 min. Sync invalidates
the `ext_tx:` cache prefix.

## 10. Error handling

| condition | behaviour |
|---|---|
| sheet unreadable / not shared | `SheetUnavailable`; sync logs a FAILED run; `POST /sync` → 503 with a generic message |
| read model missing (migration 007 not run) | list/summary return empty with `source_available: false`; UI shows "sumber sedang tidak tersedia" |
| BigQuery error on read | 503, generic message |
| out-of-scope or unknown transaction id | 404 |
| invalid source row | rejected, counted, run marked `PARTIAL`; the rest still loads |

Raw Google/BigQuery errors are never returned to the browser — they are logged
server-side with the exception *class*, never a URL, token, or credential.

## 11. Data quality

`python -m scripts.ops.validate_ext_transactions [--with-bq]` runs every check and
exits non-zero on a blocking failure, so it can gate a deploy: total rows, unique
ids, duplicates, orphan items, visits without items, null dates, negative
quantities and values, source-vs-computed mismatches, missing salesman/store ids,
and (with `--with-bq`) mapping coverage against STEP masters.

**Run of 2026-08-13:** 0 blocking, 2 warnings — the two warnings are `total visit
rows = 0` and `total visit_item rows = 0`.

Measured mapping coverage of the workbook's *store master* against `dim_outlet`:
**678 / 1,559 (43.5%)**. Salesman codes: **13 / 18**, all G2G; the five SKT
`SES02010x` codes do not resolve.

## 12. Logging

`services.ext_transactions` and `routers.ext_transaction` log: sync start/finish
with counts, source-fetch failures (exception class + gid only), parse rejections,
orphan and duplicate counts, unmapped stores/salesmen, read-model unavailability,
and denied/missing detail lookups (id + username). Credentials, tokens, and the
sheet URL are never logged.

## 13. Known limitations

1. **The source has no transactions.** Both `visit` and `visit_item` are
   header-only. Corroborating: all 12,496 schedule rows are `MISSED` or `PLANNED`,
   never completed. The feature is complete and verified, but until the source is
   populated every screen legitimately shows its empty state. The join key, date
   format, and totals rule were therefore derived from the *headers plus the
   populated sibling tabs*, not from live transaction rows — the first real sync
   should be checked against §11 before distributors are told about the page.
2. **43.5% store-mapping coverage** — a transaction whose store does not resolve
   to a STEP outlet has no `distributor_code` and is invisible to every `dm`
   (visible to `ho_admin`, and counted as `unmapped_stores` in the summary). This
   is a deliberate fail-closed choice: an unmapped store cannot be *proven* to
   belong to the distributor asking for it.
3. **Store-derived and salesman-derived distributor codes disagree.** Stores map
   to DST105/111/112/113/122/151/154; the sheet's salesmen map to
   DST268–272/326/327 — disjoint sets. Scoping follows the store, per STEP
   precedent. Worth resolving with the master-data owner.
4. **The spreadsheet is world-readable by link** and its `users` tab contains a
   `password` column. That is a finding about the *source system*, outside this
   feature's remit, but it should be escalated: anyone with the link can read the
   store master, 12k schedules, and those credentials. If the sheet is locked
   down, swap in a credentialed reader (§8) — no other code changes.
5. `dim_outlet.is_active` is NULL for every matched row, so the mapping join
   deliberately does not filter on it.
6. Sync is manual/scheduled, not real-time; the UI shows data as of the last run.

## 14. Testing

`backend/tests/test_ext_transactions.py` — **58 BQ-free unit tests**: number/date/
timestamp parsing (including the day-first regression and the naive-timestamp
timezone rule), row mapping and rejection, deterministic item identity, the
1-visit-N-items guarantee, duplicate collapse, orphan handling, visits without
items, totals and mismatch tolerance, invalid-row accounting, CSV header
normalization, header-only sheets, and the full authorization matrix (including
`dm` with no distributor and forged-parameter narrowing).

`frontend/src/components/layout/nav.test.ts` — menu RBAC for the new entry.

Verified: `py_compile` clean · app imports with 103 routes, dynamic segment last ·
58 backend tests pass · frontend `tsc --noEmit` clean · `npm run build` clean ·
25 frontend tests pass · validation script runs green against the live source.

## 15. Deployment requirements

1. Run `database/migrations/007_ext_distributor_transactions.sql`.
2. Deploy the backend (**manual** — `deploy_to_cloudrun.ps1`). Frontend
   auto-deploys to Vercel on merge to `main`.
3. Optional config: `EXT_TX_SPREADSHEET_ID`, `EXT_TX_VISIT_GID`,
   `EXT_TX_VISIT_ITEM_GID`, `EXT_TX_SKU_GID`, `EXT_TX_TIMEOUT_S`,
   `EXT_TX_SYNC_ENABLED`. Defaults are baked in; no secret is required while the
   sheet is link-readable.
4. Run `POST /ext-transaction/sync` once as ho_admin, then
   `python -m scripts.ops.validate_ext_transactions --with-bq`.
5. Schedule the sync (Cloud Scheduler → Cloud Run job calling `run_sync`).

## Source separation — what makes this independent

- Its own tables (`ext_*`), written **only** by `run_sync`. `step_visit` /
  `step_visit_item` are never read or written by this feature, and no query joins
  the two datasets.
- Its own service, router, models, types, and API client. No SFA module imports
  anything from here; this feature imports only shared infrastructure
  (`BQClient`, `require_role`, `UserContext`, `log_event`).
- Its own UI route and menu entry, with an explicit banner telling the user the
  data is external and read-only.
- **Existing SFA transaction functionality: UNCHANGED.** The only edits to
  pre-existing files are additive: two lines in `main.py` (import + router
  registration), one nav leaf, one lazy import + one route in `App.tsx`, a config
  block, and appended type definitions.

## Files

**Backend:** `services/ext_transactions.py`✚, `routers/ext_transaction.py`✚,
`models/ext_transaction.py`✚, `scripts/ops/validate_ext_transactions.py`✚,
`tests/test_ext_transactions.py`✚, `config.py`, `main.py`.
**Web:** `pages/ExtTransactions.tsx`✚, `api/extTransaction.ts`✚, `types/index.ts`,
`components/layout/nav.ts`, `components/layout/nav.test.ts`, `App.tsx`.
**DB:** `migrations/007_ext_distributor_transactions.sql`✚.
**Docs:** this file. (✚ = new)
