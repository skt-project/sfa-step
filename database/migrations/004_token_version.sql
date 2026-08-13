-- ============================================================
-- Migration 004 – Server-side session revocation (E2E-14 / E2E-17)
--
-- Adds a monotonically-increasing token_version per user. Every JWT carries the
-- version it was minted at ("tv" claim); the API rejects a token whose tv is below
-- the user's current version. Incrementing token_version therefore invalidates
-- ALL of that user's outstanding tokens at once — used by:
--   - POST /auth/logout        (real server-side logout)
--   - POST /auth/reset-password (old sessions die when the password changes)
--   - admin deactivate         (a disabled account's live tokens stop working)
--
-- SAFE: additive, nullable column. The API treats NULL/absent as 0, and a token
-- with no "tv" claim as 0, so existing sessions keep working until they expire or
-- the user logs out — no forced re-login on deploy.
-- ============================================================

ALTER TABLE `skintific-data-warehouse.sfa_web.users`
  ADD COLUMN IF NOT EXISTS token_version INT64
    OPTIONS(description='Session-revocation counter. JWT "tv" claim must be >= this value. Bumped on logout / password reset / deactivate. NULL = 0.');

-- Optional: baseline existing rows to 0 (NULL already behaves as 0 in the API).
-- UPDATE `skintific-data-warehouse.sfa_web.users`
--   SET token_version = 0 WHERE token_version IS NULL;
