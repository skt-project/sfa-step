# 04 — Database Guide (As-Built)

Project: `skintific-data-warehouse` · All app access goes through the backend service account. **The browser and the mobile app never touch BigQuery directly.**

## Datasets

| Dataset | Access | Used for |
|---|---|---|
| **`sfa_web`** | **READ/WRITE — the only writable dataset** | All STEP transactional tables |
| `gt_schema` | READ ONLY | Product catalog, store master, distributor stock |
| others (mt_schema, dms, …) | READ ONLY | Not used by STEP runtime |

## Key tables in `sfa_web`

| Table | Purpose | Notes |
|---|---|---|
| `users` | App accounts | `user_id` (UUID), `username`, `password_hash` (bcrypt; legacy `salt:sha256` auto-upgraded on login), `role`, `brand_group`, `salesman_sk` (link to dim_salesman), `push_token`. ⚠ legacy role values exist: `se` (backend treats as salesman), `distributor_admin` (**not recognized — normalize to `dm`**) |
| `dim_salesman` | Salesman master (synced) | `salesman_sk`, `salesman_name`, `spv_name` ← **drives One-Line-Management**, `asm_name`, `distributor_code`, `region`, `brand_group`, `is_active` |
| `dim_outlet` | Store master (synced) | `outlet_sk`, `store_name`, `source_outlet_code`, GPS, `distributor_code` (drives DM scoping) |
| `step_visit` (logical `fact_visit`) | Visit header | statuses, GPS, approver columns, `adjustment_amount/_note` (migration 005) |
| `step_visit_item` (logical `fact_visit_item`) | Order lines | written **only at submit**; `final_qty` (SPV), `price_for_store` (DM) |
| `step_visit_revision` | Revision audit | |
| `step_visit_download_log` | PDF download audit | |
| `route_plan` | Weekly PJP assignments | `schedule_id` is checkin's idempotency key |
| `spv_target` | Targets per salesman/brand/month | ⚠ `brand` values are **mixed case** — always compare with `UPPER()` |
| `notification` | In-app notifications | keyed by `users.user_id` |
| `skipped_store` | Skipped-store workflow | |
| `announcement`, `audit_log`, import/export job tables | supporting | |

Logical→physical aliasing lives in `backend/config.py` (`fact_visit → step_visit`, etc.) — always use `settings.table("fact_visit")` in backend code.

## Read-only sources in `gt_schema`

| Table | Used for | ⚠ Gotchas |
|---|---|---|
| `master_product` | `/product` catalog | **`brand` is UPPERCASE** (SKINTIFIC, G2G, BODIBREZE…). Price = `COALESCE(price_for_store, srp)` — rows where that's ≤ 0 are excluded from ordering. `pack_size` (STRING) feeds UI + PDF. `sku` is the id |
| `master_store_database_basis` | store↔distributor ids (`dst_id_skt/_g2g/_tph`) | dedupe by latest `input_date` |
| `dist_stock_all_v` | warehouse stock per distributor/product | dedupe by latest `date`; joined into visit detail for stock warnings |

## THE case-sensitivity rule (root cause of the 2026-07-15 fix)
Brand casing is inconsistent across tables (`master_product` UPPERCASE, `spv_target` mixed). Every brand comparison — SQL `IN`, Python membership, TS `includes` — must uppercase both sides. `BRAND_GROUPS` in `backend/dependencies.py` and the mobile mirror in `VisitSurveyScreen.tsx` store UPPERCASE lists; `brand_list_filter` wraps the column in `UPPER()`. **Never** add a Title-case brand literal.

## Migrations
Location: `database/migrations/`, applied manually:
```bash
bq query --use_legacy_sql=false < database/migrations/00X_name.sql
```
| # | File | Status |
|---|---|---|
| 001–004 | initial tables, approval enhancements, salesman_sk type fixes | applied |
| **005** | `005_visit_adjustment.sql` — adds `adjustment_amount FLOAT64`, `adjustment_note STRING` to `step_visit` (`ADD COLUMN IF NOT EXISTS`, additive/safe) | **run once before relying on invoice adjustment** — backend degrades gracefully (nulls) until then |

## Data-quality watch-list
1. `users.role` legacy values (`se`, `distributor_admin`) — normalize when convenient; only `distributor_admin` actually breaks (no nav, approve 403s).
2. `users.brand_group` NULL on a salesman ⇒ their visits get `brand_group NULL` ⇒ invisible to BU-scoped SPVs. Assign a BU to every real salesman account (and have them re-login).
3. `dim_salesman.spv_name` must match the SPV's `users.full_name` (case-insensitive) for One-Line-Management to engage; unmatched SPVs silently fall back to BU-wide visibility.
4. Visits stuck at `CHECKED_IN` with 0 items = checkout/submit still on the device (offline) — not data loss; the phone will flush them.

## Performance notes
- Writes are BigQuery DML jobs (~1–3 s each). Hot paths batch (final-qty, store-price, notify-SPVs use single statements). **Submit still inserts items one-per-DML — known issue R2**, mitigated by idempotent retry; batch it if large baskets become common.
- List queries paginate and dedupe joins via `QUALIFY ROW_NUMBER()`.
- In-process TTL caches (`services/bq.py`): products 5 min/BU, dashboard 2 min, notifications 60 s, SPV team map 5 min. Restarting Cloud Run clears them.
