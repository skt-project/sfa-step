-- Migration 008: Distributor adjustment on external (spreadsheet) transactions
--
-- Mirrors migration 005 (SFA's step_visit adjustment_amount/adjustment_note) for
-- the external source, so a Distributor can apply a delivery-fee/discount/promo
-- adjustment on top of a Spreadsheet order the same way they already can for an
-- SFA order.
--
-- CRITICAL: these two columns are NOT written by services.ext_transactions
-- (the sync's MERGE ... WHEN MATCHED THEN UPDATE SET list never references them),
-- so a re-sync of the source spreadsheet can never overwrite a distributor's
-- adjustment. They are exclusively written by PUT /orders/adjustment.
--
--   bq query --use_legacy_sql=false < 008_ext_visit_adjustment.sql

ALTER TABLE `skintific-data-warehouse.sfa_web.ext_visit`
  ADD COLUMN IF NOT EXISTS adjustment_amount FLOAT64
    OPTIONS(description="Distributor Admin invoice adjustment (delivery fee/discount/promo). Positive = surcharge, negative = reduction. STEP-owned — the sync never writes this column, so it survives every re-sync of the source spreadsheet untouched."),
  ADD COLUMN IF NOT EXISTS adjustment_note STRING
    OPTIONS(description="Free-text reason for adjustment_amount. STEP-owned, never touched by the sync.");
