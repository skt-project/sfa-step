-- ============================================================
-- Migration 003 – Approval linkage & scope (E2E-07 / E2E-04)
-- Run order: execute each ALTER individually in the BigQuery console
--   (BigQuery allows one ADD COLUMN per ALTER statement).
--
-- Makes the generic approval_request queue an ENFORCEABLE control instead of a
-- decorative inbox: each request can now name the exact row it changes
-- (entity_type + entity_id) so approve can apply proposed_value, and carries a
-- brand_group so approvers only see/decide requests within their scope.
--
-- SAFE: additive, nullable columns only. Existing (unlinked) rows keep working —
-- the backend treats a NULL entity_type as advisory (records the decision, applies
-- nothing) and a NULL brand_group as visible to every approver.
-- ============================================================

ALTER TABLE `skintific-data-warehouse.sfa_web.approval_request`
  ADD COLUMN IF NOT EXISTS entity_type STRING
    OPTIONS(description='Enactable target type: "spv_target" | "outlet_tier". NULL = advisory/free-text request (no auto-apply).');

ALTER TABLE `skintific-data-warehouse.sfa_web.approval_request`
  ADD COLUMN IF NOT EXISTS entity_id STRING
    OPTIONS(description='Primary key of the row proposed_value applies to (e.g. spv_target.spv_target_id, or CAST(dim_outlet.outlet_sk AS STRING)).');

ALTER TABLE `skintific-data-warehouse.sfa_web.approval_request`
  ADD COLUMN IF NOT EXISTS field_name STRING
    OPTIONS(description='Informational: which field changes, e.g. "spv_target" or "store_grade".');

ALTER TABLE `skintific-data-warehouse.sfa_web.approval_request`
  ADD COLUMN IF NOT EXISTS brand_group STRING
    OPTIONS(description='Scope key derived server-side from the linked entity at create time (SKT|G2G). NULL = unscoped/legacy → visible to all approvers.');

-- Verification (run after):
-- SELECT column_name, data_type FROM `skintific-data-warehouse.sfa_web.INFORMATION_SCHEMA.COLUMNS`
--   WHERE table_name = 'approval_request' ORDER BY ordinal_position;
