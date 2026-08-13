-- Migration 007: External Distributor Transactions (read-only history)
--
-- Creates a SEPARATE read model for transactions sourced from an external
-- Google Spreadsheet (`visit` + `visit_item` tabs). These tables are NOT part of
-- the SFA transaction pipeline:
--   * step_visit / step_visit_item are written by the handheld app  → untouched.
--   * ext_visit / ext_visit_item are written ONLY by the sync job   → this file.
-- Nothing joins the two. The web UI reads them through different endpoints.
--
-- Run ONCE against BigQuery before deploying the backend build that references
-- them. The read API degrades gracefully if they are absent (returns an empty
-- result plus a "source unavailable" flag), so deploy order is not strict.
--
--   bq query --use_legacy_sql=false < 007_ext_distributor_transactions.sql
--
-- Numbering note: 003/004/005 exist twice across unmerged branches
-- (003_fix_salesman_sk_type + 003_approval_linkage, etc.). 007 is unused on
-- every branch as of 2026-08-13.

-- ---------------------------------------------------------------------------
-- Transaction header — one row per source `visit` row. NEVER one row per item.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `skintific-data-warehouse.sfa_web.ext_visit` (
  ext_visit_id           STRING  NOT NULL OPTIONS(description="Transaction identity = source visit.visit_id. MERGE key; guarantees 1 source visit = 1 transaction."),
  source_schedule_id     STRING           OPTIONS(description="Source visit.schedule_id, as-is"),
  source_visit_type      STRING           OPTIONS(description="Source visit.visit_type, as-is"),
  source_username        STRING           OPTIONS(description="Source visit.username — the sheet's salesman code (e.g. GTIDST2722)"),
  source_store_id        STRING           OPTIONS(description="Source visit.store_id — the sheet's store code (e.g. IWCJ00001)"),

  visit_date             DATE             OPTIONS(description="Source visit.visit_date parsed as an Asia/Jakarta calendar date (source format DD/MM/YYYY)"),
  checkin_time           TIMESTAMP        OPTIONS(description="Source checkin_time interpreted as Asia/Jakarta wall time, stored UTC"),
  checkout_time          TIMESTAMP        OPTIONS(description="Source checkout_time interpreted as Asia/Jakarta wall time, stored UTC"),
  checkin_latitude       FLOAT64,
  checkin_longitude      FLOAT64,
  checkin_distance_meter FLOAT64,
  checkin_photo_url      STRING,
  checkout_latitude      FLOAT64,
  checkout_longitude     FLOAT64,
  checkout_distance_meter FLOAT64,
  checkout_photo_url     STRING,
  notes                  STRING,
  duration_minutes       INT64,

  source_total_demand    FLOAT64          OPTIONS(description="visit.total_demand EXACTLY as the source states it. Never overwritten — kept for reconciliation against computed_value."),
  effective_call         STRING,
  visit_status           STRING,
  source_created_at      TIMESTAMP,
  source_updated_at      TIMESTAMP,

  -- Mapping onto STEP masters, resolved at sync time. NULL = unmapped.
  salesman_sk            STRING           OPTIONS(description="dim_salesman.salesman_sk resolved via source_salesman_code = source_username. NULL when the sheet's salesman is unknown to STEP."),
  salesman_name          STRING           OPTIONS(description="dim_salesman.salesman_name at sync time"),
  outlet_sk              STRING           OPTIONS(description="dim_outlet.outlet_sk resolved via source_outlet_code = source_store_id. NULL when the sheet's store is unknown to STEP."),
  store_name             STRING           OPTIONS(description="dim_outlet.store_name at sync time; falls back to the sheet's store name"),
  distributor_code       STRING           OPTIONS(description="AUTHORIZATION KEY. dim_outlet.distributor_code of the mapped store. NULL rows are invisible to every dm — only ho_admin can see them."),
  brand_group            STRING           OPTIONS(description="dim_outlet.brand_group of the mapped store (SKT/G2G)"),

  -- Derived at sync time so the list query never joins items (no fan-out).
  item_count             INT64            OPTIONS(description="COUNT of ext_visit_item rows for this transaction"),
  computed_qty           FLOAT64          OPTIONS(description="SUM(item.qty) — the authoritative quantity"),
  computed_value         FLOAT64          OPTIONS(description="SUM(item line value) — the authoritative transaction value (see docs 17 §calculation rules)"),
  total_mismatch         BOOL             OPTIONS(description="TRUE when source_total_demand differs from computed_value by more than 1 rupiah. Surfaced in the UI, never silently corrected."),

  -- Sync audit
  batch_id               STRING           OPTIONS(description="ext_transaction_sync_log.batch_id that last wrote this row"),
  synced_at              TIMESTAMP        OPTIONS(description="When this row was last written by the sync job"),
  row_hash               STRING           OPTIONS(description="Hash of the mapped source fields — lets a later sync skip unchanged rows")
)
PARTITION BY visit_date
CLUSTER BY distributor_code, salesman_sk
OPTIONS(description="External distributor transactions (header). Source: Google Spreadsheet `visit` tab. Read-only mirror — never written by the handheld or web app.");

-- ---------------------------------------------------------------------------
-- Transaction items — one row per source `visit_item` row.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `skintific-data-warehouse.sfa_web.ext_visit_item` (
  ext_visit_item_id  STRING NOT NULL OPTIONS(description="Item identity = source visit_item.visit_item_id, or a deterministic hash of (visit_id, sku_id, ordinal) when the source leaves it blank"),
  ext_visit_id       STRING NOT NULL OPTIONS(description="FK to ext_visit.ext_visit_id — the source's own visit_id. Items whose parent is missing are NOT loaded (counted as orphan_items)."),
  sku_id             STRING,
  sku_name           STRING          OPTIONS(description="Resolved from the spreadsheet's own sku tab at sync time; falls back to sku_id"),
  brand              STRING,
  category           STRING,
  qty                FLOAT64,
  stp                FLOAT64         OPTIONS(description="Source unit price (standard trade price)"),
  demand             FLOAT64         OPTIONS(description="visit_item.demand EXACTLY as the source states it"),
  line_value         FLOAT64         OPTIONS(description="Authoritative line value: demand when present and non-zero, else qty * stp"),
  source_created_at  TIMESTAMP,
  source_updated_at  TIMESTAMP,
  batch_id           STRING,
  synced_at          TIMESTAMP
)
CLUSTER BY ext_visit_id
OPTIONS(description="External distributor transaction items. Source: Google Spreadsheet `visit_item` tab.");

-- ---------------------------------------------------------------------------
-- Sync run log — powers the admin status endpoint and the data-quality report.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `skintific-data-warehouse.sfa_web.ext_transaction_sync_log` (
  batch_id           STRING NOT NULL,
  started_at         TIMESTAMP,
  finished_at        TIMESTAMP,
  status             STRING OPTIONS(description="RUNNING | SUCCESS | PARTIAL | FAILED"),
  triggered_by       STRING OPTIONS(description="username, or 'scheduler'"),
  visits_read        INT64,
  items_read         INT64,
  visits_written     INT64,
  items_written      INT64,
  invalid_visits     INT64  OPTIONS(description="Source rows rejected by validation (no visit_id, unparseable date, …)"),
  duplicate_visits   INT64  OPTIONS(description="Repeated visit_id in the source — last occurrence wins, earlier ones counted here"),
  orphan_items       INT64  OPTIONS(description="visit_item rows whose visit_id matches no visit row"),
  unmapped_stores    INT64  OPTIONS(description="Distinct source store_ids with no dim_outlet match — these transactions have no distributor and are invisible to dm users"),
  unmapped_salesmen  INT64  OPTIONS(description="Distinct source usernames with no dim_salesman match"),
  total_mismatches   INT64  OPTIONS(description="Transactions where source_total_demand != computed_value"),
  error              STRING
)
OPTIONS(description="One row per external-transaction sync run.");
