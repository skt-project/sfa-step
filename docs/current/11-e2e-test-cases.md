# 11 — End-to-End Test Cases (formal)

**Date:** 2026-07-21 · **Applies to:** STEP Web (`sfa-step`) + STEP Mobile (`sfa-mobile`) + STEP API + BigQuery `sfa_web` + Power BI

This is the **formal, structured** E2E suite (each case: Objective / Precondition / Steps / Expected / Validation Method / Pass / Fail / Priority). It is the executable checklist for a release sign-off. For the *detailed click-by-click* SKT and G2G walkthroughs, use [08-e2e-test-scripts](08-e2e-test-scripts.md); this document is the coverage matrix over the full business process and does not restate every tap.

**Business process under test:**
`Login → Dashboard → Master Data → Route → Visit → Order → Checkout → Approval (SPV→DM) → PDF → BigQuery → Power BI → Notification → Logout`

**Priority:** `P1` critical (blocks go-live) · `P2` high · `P3` medium.

**Accounts / BU / environments:** see [08 §Test accounts](08-e2e-test-scripts.md#test-accounts) and [06-operations-runbook](06-operations-runbook.md). Roles: `se`(salesman) · `spv` · `asm` · `dm` · `ho_admin`. Business Units: **SKT** (Skintific/Timephoria/Facerinna) · **G2G** (Glad2Glow/Bodibreze/Nextprime). Brand values in `gt_schema.master_product` are **UPPERCASE** — all brand comparisons must be case-insensitive.

> **SQL note:** table/column names below follow [04-database-guide](04-database-guide.md); confirm before running. `sfa_web` is the only writable dataset. Replace `@visit_id`, `@username`, `<today>` etc. with the run's values.

---

## TC-AUTH — Authentication & session

### TC-AUTH-01 — Web login with valid credentials `P1`
- **Objective:** A valid user can authenticate on the web app and receive a scoped JWT.
- **Precondition:** `admin` (or any web role) exists and is active in `sfa_web.users`; API healthy (`GET /health` → `{"status":"ok"}`).
- **Steps:** 1) Open `https://sfa-step.vercel.app`. 2) Enter valid credentials, submit.
- **Expected Result:** Redirect to Dashboard; JWT stored; sidebar reflects the role.
- **Validation Method:** `POST /api/v1/auth/login` returns `200` + `access_token`; decode token → `role`, `business_unit`, `salesman_sk` claims present. Browser `localStorage.step_jwt` set.
- **Pass Criteria:** 200 + token with correct role/BU claims; dashboard renders.
- **Fail Criteria:** Non-200, missing/incorrect claims, or no redirect.

### TC-AUTH-02 — Invalid credentials rejected `P1`
- **Objective:** Wrong password/unknown user cannot authenticate.
- **Precondition:** Known username, deliberately wrong password.
- **Steps:** 1) Submit `{username: admin, password: wrong}`. 2) Submit `{username: nobody, password: x}`.
- **Expected Result:** Both rejected with an error message; no token issued.
- **Validation Method:** `POST /auth/login` → `401` for both.
- **Pass Criteria:** 401, no token, generic error (no user-enumeration leak).
- **Fail Criteria:** Any 200/token, or error reveals which field was wrong.

### TC-AUTH-03 — Protected endpoint requires auth `P1`
- **Objective:** Unauthenticated requests to protected resources are denied.
- **Precondition:** None.
- **Steps:** 1) `GET /api/v1/auth/me` with no token. 2) With an expired token.
- **Expected Result:** Denied; web client redirects to `/login` and clears the token on 401.
- **Validation Method:** No token → `403`; expired token → `401`; web interceptor clears `step_jwt` and routes to `/login`.
- **Pass Criteria:** 403/401 as above; session cleared on 401.
- **Fail Criteria:** Protected data returned without a valid token.

---

## TC-RBAC — Role-based access (see also [10 §5 web RBAC matrix](10-production-readiness-audit.md#5-web-rbac-matrix-as-built))

### TC-RBAC-01 — Menu visibility per role `P1`
- **Objective:** Each role sees only its authorized navigation.
- **Precondition:** One account per role (`spv`, `asm`, `dm`, `ho_admin`).
- **Steps:** Log in as each role; inspect sidebar.
- **Expected Result:** `Administration` only for `ho_admin`; `Import & Export` only for `dm`/`ho_admin`; `Master Data PJP/Salesman` hidden from `spv`; `salesman`/`demo` see no web nav.
- **Validation Method:** Compare against the RBAC matrix; unit-tested in `frontend/src/components/layout/nav.test.ts`.
- **Pass Criteria:** Menus match the matrix exactly.
- **Fail Criteria:** Any unauthorized menu appears.

### TC-RBAC-02 — Server-side authorization is enforced (not just menu) `P1`
- **Objective:** Hiding a menu is not the control — the API rejects unauthorized calls.
- **Precondition:** `se`/`spv` token that should NOT reach an admin route.
- **Steps:** With an `se` token, call an admin endpoint (e.g. `POST /api/v1/admin/users/<id>/reset-token`).
- **Expected Result:** Rejected server-side.
- **Validation Method:** Response `403` (see `backend/tests/test_auth.py::test_reset_token_requires_admin`).
- **Pass Criteria:** 403 regardless of UI state.
- **Fail Criteria:** 2xx / action performed for an unauthorized role.

### TC-RBAC-03 — SPV One-Line-Management scope `P2`
- **Objective:** An SPV only sees/acts on visits of their own salesmen (`dim_salesman.spv_name`).
- **Precondition:** SPV mapped to a subset of salesmen; visits exist for in-scope and out-of-scope salesmen.
- **Steps:** As SPV, open Visit & Order list; attempt to approve an out-of-scope visit via API.
- **Expected Result:** Only in-scope salesmen's visits listed; cross-line action blocked.
- **Validation Method:** List endpoint returns only in-scope rows; cross-line approve → `403`. (Unmapped SPV → BU-wide fallback per changelog.)
- **Pass Criteria:** Scope enforced; cross-line = 403.
- **Fail Criteria:** Out-of-scope visit visible or approvable.

---

## TC-DASH / TC-MD / TC-ROUTE — Landing, master data, route

### TC-DASH-01 — Role-scoped dashboard `P2`
- **Objective:** Dashboard KPIs load and are scoped to the user's territory/BU.
- **Precondition:** Data exists for the user's scope.
- **Steps:** Log in; land on Dashboard.
- **Expected Result:** KPI tiles + charts render with non-empty, scope-correct data; no console/CORS errors.
- **Validation Method:** `GET /api/v1/dashboard_web/...` → 200 with rows; spot-check a KPI against a BigQuery aggregate.
- **Pass Criteria:** Data renders, matches BQ within tolerance, no errors.
- **Fail Criteria:** Empty/error tiles or cross-scope data leakage.

### TC-MD-01 — Master data scoping `P2`
- **Objective:** PJP and Salesman master lists respect role/BU scope.
- **Precondition:** `asm`/`dm`/`ho_admin` account.
- **Steps:** Open Master Data → PJP and Salesman.
- **Expected Result:** Lists load, searchable/paginated, scoped to the user.
- **Validation Method:** `GET /salesman/list`, `GET /route_planner/...` return scoped rows; SPV cannot reach these (TC-RBAC-01).
- **Pass Criteria:** Correct rows, pagination + search work.
- **Fail Criteria:** Unscoped data or broken paging.

### TC-ROUTE-01 — Salesman route (PJP) for today `P1`
- **Objective:** A salesman sees today's planned route with ≥1 store.
- **Precondition:** Salesman has a PJP for `<today>` with ≥3 stores.
- **Steps:** Mobile → Rute tab.
- **Expected Result:** Today's stores listed with status legend (Belum/Terlewat/Check-in/Checkout/Disubmit).
- **Validation Method:** `GET /schedule/...` (or route endpoint) returns today's stores; matches `sfa_web` schedule for the salesman.
- **Pass Criteria:** All planned stores shown with correct status.
- **Fail Criteria:** Missing/extra stores or wrong statuses.

---

## TC-VISIT / TC-ORDER / TC-CHECKOUT — Field execution

### TC-VISIT-01 — Check-in (photo required, GPS informational) `P1`
- **Objective:** Check-in requires a photo; GPS is recorded but never blocks.
- **Precondition:** Camera + location permission granted.
- **Steps:** Open a store → Check-in; try without photo, then with photo.
- **Expected Result:** Check-in disabled until a photo is taken; GPS distance recorded, >200 m shows a warning but still allows check-in.
- **Validation Method:** `POST /visit/checkin` → `visit_id`; row in `sfa_web.step_visit` with `checkin_latitude/longitude`; `gps_warning` flag when far.
- **Pass Criteria:** No check-in without photo; visit row created; GPS non-blocking.
- **Fail Criteria:** Check-in without photo, or GPS blocks a valid visit.

### TC-ORDER-01 — Business-Unit brand isolation (critical) `P1`
- **Objective:** A salesman only ever sees their own BU's brands — anywhere.
- **Precondition:** SKT salesman (repeat for G2G). Products priced for the BU.
- **Steps:** In Input Order, inspect brand tabs, product list, and search for a cross-BU brand.
- **Expected Result:** SKT user sees only Skintific/Timephoria/Facerinna; searching "G2G" → 0 results (and mirror for G2G user).
- **Validation Method:** `GET /product` returns only in-BU SKUs; case-insensitive brand match against `master_product` (UPPERCASE). No cross-BU SKU in any response.
- **Pass Criteria:** Perfect BU isolation in list, tabs, and search.
- **Fail Criteria:** Any cross-BU brand visible or returned by the API.

### TC-ORDER-02 — Effective Call & unpriced-SKU handling `P2`
- **Objective:** Setting qty flips EC to effective; SKUs with no valid price are excluded.
- **Precondition:** Mix of priced and unpriced SKUs.
- **Steps:** Add qty to 2–3 priced SKUs; look for any unpriced SKU.
- **Expected Result:** EC badge → "Efektif"; header shows "X SKU · Y pcs"; unpriced SKUs never appear (list/search/tabs/totals consistent).
- **Validation Method:** `/product` excludes SKUs lacking a valid price; totals equal Σ(qty×price).
- **Pass Criteria:** EC logic correct; no unpriced SKU anywhere.
- **Fail Criteria:** Unpriced SKU shown or EC mislabeled.

### TC-CHECKOUT-01 — Checkout totals & submit `P1`
- **Objective:** Checkout shows correct totals and submits to the SPV.
- **Precondition:** Completed order from TC-ORDER-01.
- **Steps:** Lanjut Check-out → review Ringkasan Order → Submit ke SPV.
- **Expected Result:** Summary shows Total SKU / Total Qty / **Total Rupiah**; on submit, store status → "Disubmit", online pill **🟢 Tersinkron**.
- **Validation Method:** `POST /visit/{id}/checkout` then submit → `SUBMITTED`; `sfa_web.step_visit` status + `step_visit_item` rows present with correct totals.
- **Pass Criteria:** Totals correct; visit `SUBMITTED`; items persisted.
- **Fail Criteria:** Wrong totals, submit fails, or items missing.

---

## TC-APPROVAL / TC-PDF — Approval chain

### TC-APPR-01 — SPV review & approve `P1`
- **Objective:** SPV can review a submitted visit, adjust final qty, and approve.
- **Precondition:** A `SUBMITTED` visit from an in-scope salesman.
- **Steps:** Web as SPV → Visit & Order → open the visit → edit Qty Final → Approve.
- **Expected Result:** Header shows store/salesman once; "Harga Rekomendasi (STP/pcs)" column; Total Order (Final) updates; status → SPV Approved; salesman notified.
- **Validation Method:** `POST /approval/...` → `sfa_web.approval_request` status advances; notification row created (TC-NOTIF-01).
- **Pass Criteria:** Status advances; totals recompute; notification fired.
- **Fail Criteria:** Duplicate salesman rows, approval fails, or no notification.

### TC-APPR-02 — DM price, invoice adjustment, complete `P1`
- **Objective:** DM sets store price, applies an invoice adjustment, and completes.
- **Precondition:** SPV-approved visit; migration 005 applied (else adjustment no-ops — see TC-APPR-03).
- **Steps:** DM → open visit → Edit Qty & Harga → confirm Harga Toko/PCS pre-filled from Harga Rekomendasi → change one price → add adjustment `+50000` "Ongkos kirim", then a negative `-25000` "Diskon" → Approve to COMPLETED.
- **Expected Result:** Totals recompute; summary shows Subtotal / Adjustment (+/-) / **Final Invoice**; negative adjustment shown in red; status COMPLETED.
- **Validation Method:** `sfa_web.approval_request` = COMPLETED; adjustment fields persisted; Final = Subtotal + Σ(adjustments).
- **Pass Criteria:** Adjustment math correct; status COMPLETED.
- **Fail Criteria:** Wrong Final Invoice or completion blocked.

### TC-APPR-03 — Migration gate (graceful) `P3`
- **Objective:** If migration 005 is not applied, adjustment silently no-ops without error.
- **Precondition:** Environment without migration 005.
- **Steps:** Attempt an invoice adjustment.
- **Expected Result:** Final Invoice = Subtotal; app does not error.
- **Validation Method:** No 5xx; adjustment ignored.
- **Pass Criteria:** No crash; graceful degrade.
- **Fail Criteria:** Error/crash on adjustment.

### TC-PDF-01 — Offering-letter PDF `P1`
- **Objective:** A correct offering-letter PDF is generated on completion.
- **Precondition:** COMPLETED visit (TC-APPR-02).
- **Steps:** Unduh PDF; open it.
- **Expected Result:** Filename `{Store}_{ddMMyyyy}.pdf`; header "SURAT PENAWARAN ORDER"; "DETAIL PRODUK ORDER"; Subtotal/Adjustment/Final Invoice block; Harga Toko/PCS column; "Business Unit" label; pack size shown.
- **Validation Method:** Inspect downloaded file name + rendered content.
- **Pass Criteria:** Filename + all blocks correct.
- **Fail Criteria:** Wrong filename or missing/incorrect content.

---

## TC-BQ — Data persistence (SQL validation)

### TC-BQ-01 — Visit + items land in BigQuery `P1`
- **Objective:** A submitted visit and its items are persisted in `sfa_web`.
- **Precondition:** Completed TC-CHECKOUT-01 for a known `@visit_id`.
- **Steps:** Run the validation SQL after submit.
- **Expected Result:** One visit row; item count = number of ordered SKUs; totals match the app.
- **Validation Method:**
  ```sql
  -- header exists, correct status/BU/salesman
  SELECT visit_id, status, business_unit, salesman_sk, total_demand, effective_call
  FROM `skintific-data-warehouse.sfa_web.step_visit`
  WHERE visit_id = @visit_id;

  -- items match the order, no cross-BU brand leaked
  SELECT i.sku_id, i.qty, p.brand
  FROM `skintific-data-warehouse.sfa_web.step_visit_item` i
  JOIN `skintific-data-warehouse.gt_schema.master_product` p
    ON UPPER(p.sku_id) = UPPER(i.sku_id)
  WHERE i.visit_id = @visit_id;

  -- header total reconciles to items
  SELECT s.total_demand AS header_total,
         (SELECT SUM(qty*price) FROM `...sfa_web.step_visit_item` WHERE visit_id=@visit_id) AS item_total
  FROM `skintific-data-warehouse.sfa_web.step_visit` s
  WHERE s.visit_id = @visit_id;
  ```
- **Pass Criteria:** Exactly one header; item count correct; all item brands within the salesman's BU; header_total = item_total.
- **Fail Criteria:** Missing rows, cross-BU brand, or totals mismatch.

### TC-BQ-02 — No duplicate visits (idempotency) `P1`
- **Objective:** Retried/offline syncs never create duplicate server visits.
- **Precondition:** One logical visit that was synced (incl. a retried offline sync — see TC-OFFLINE-02).
- **Steps:** Run the duplicate-detection SQL.
- **Expected Result:** No duplicate `(schedule_id, salesman_sk, visit_date)` beyond 1.
- **Validation Method:**
  ```sql
  SELECT schedule_id, salesman_sk, visit_date, COUNT(*) c
  FROM `skintific-data-warehouse.sfa_web.step_visit`
  WHERE visit_date = '<today>'
  GROUP BY 1,2,3 HAVING c > 1;
  ```
- **Pass Criteria:** Zero rows returned.
- **Fail Criteria:** Any group with count > 1.

---

## TC-NOTIF — Notifications

### TC-NOTIF-01 — Lifecycle notifications `P2`
- **Objective:** Submit/approve/reject generate the right notifications.
- **Precondition:** A visit moving through the chain.
- **Steps:** Submit (SE→SPV), approve (SPV), reject-then-resubmit.
- **Expected Result:** SPV notified on submit; salesman notified on approve and on reject ("Perlu Revisi"); unread badge on Profil tab.
- **Validation Method:** `GET /notification/...` returns the new items; row(s) in `sfa_web.notification`; unread count matches badge.
- **Pass Criteria:** Correct recipient + type for each event; badge count accurate.
- **Fail Criteria:** Missing notification, wrong recipient, or silent-fail on insert.

---

## TC-OFFLINE — Offline-first (mobile)

### TC-OFFLINE-01 — Capture & sync `P1`
- **Objective:** A full visit captured offline syncs when connectivity returns.
- **Precondition:** Airplane mode on.
- **Steps:** Do a full check-in→order→checkout→submit offline; observe "Data tersimpan lokal" + 🟡 Local; disable airplane mode; pull-to-refresh Home.
- **Expected Result:** Sync runs; pill → 🟢 Tersinkron; visit + items appear server-side.
- **Validation Method:** After sync, TC-BQ-01 SQL returns the visit; web SPV list shows it.
- **Pass Criteria:** Offline visit fully lands in BigQuery with items intact.
- **Fail Criteria:** Lost data, stuck 🟡 Local, or missing items.

### TC-OFFLINE-02 — Retry after mid-sync failure = no duplicate `P1`
- **Objective:** A check-out/submit failure after a successful check-in does not create a duplicate on retry (regression guard for the offline-sync fix).
- **Precondition:** Ability to interrupt the network mid-sync (or simulate a checkout failure).
- **Steps:** Start a sync; force failure after check-in but before submit; restore network; sync again.
- **Expected Result:** The retry reuses the existing `server_visit_id` (skips check-in); exactly one server visit results.
- **Validation Method:** TC-BQ-02 SQL returns zero duplicates; covered by `sfa-mobile __tests__/unit/sync.engine.test.ts` ("persists the server visit id right after check-in…").
- **Pass Criteria:** One visit only; no duplicate check-in.
- **Fail Criteria:** Two visit rows for one logical visit.

### TC-OFFLINE-03 — Offline app launch keeps session `P2`
- **Objective:** Launching the app offline with a valid token does not log the user out (regression guard for the auth fix).
- **Precondition:** Logged-in device, valid stored JWT, then go offline and relaunch.
- **Steps:** Kill and relaunch the app while offline.
- **Expected Result:** Session preserved (token not cleared on network error); user reaches the app, not the login screen.
- **Validation Method:** Token still present in secure store after relaunch; only a real 401 clears it.
- **Pass Criteria:** No offline logout.
- **Fail Criteria:** User forced to a login screen they cannot submit offline.

---

## TC-PBI — Power BI

### TC-PBI-01 — Refresh & Row-Level Security `P2`
- **Objective:** The Power BI report refreshes from `sfa_web` and enforces RLS by BU/territory.
- **Precondition:** Published report + configured dataset refresh + RLS roles.
- **Steps:** Trigger/observe a scheduled refresh; open the report as users mapped to different BUs/territories.
- **Expected Result:** Refresh succeeds within its window; each viewer sees only their BU/territory; totals reconcile to BigQuery.
- **Validation Method:** Refresh history = success; RLS role test ("View as") per BU; spot-check a measure against a BigQuery aggregate.
- **Pass Criteria:** Fresh data, correct RLS isolation, measures reconcile.
- **Fail Criteria:** Stale/failed refresh, cross-BU leakage, or measure mismatch.

---

## TC-LOGOUT — Session teardown

### TC-LOGOUT-01 — Logout & role/BU re-login `P2`
- **Objective:** Logout clears the session; role/BU changes take effect only after re-login (JWT carries them).
- **Precondition:** Logged-in user; a pending role/BU change in `sfa_web.users`.
- **Steps:** 1) Log out (web + mobile). 2) Change the user's role/BU in the DB. 3) Log back in.
- **Expected Result:** Logout clears token + query cache and returns to login; after DB change the *old* session still reflects old role until re-login; new login reflects the new role/BU.
- **Validation Method:** Post-logout, `step_jwt` absent and protected calls 401/403; new token claims show updated role/BU.
- **Pass Criteria:** Clean teardown; role/BU refresh on re-login only.
- **Fail Criteria:** Stale session usable after logout, or role change applied without re-login.

---

## Traceability & sign-off

| Stage | Test cases | Priority |
|---|---|---|
| Auth / session | TC-AUTH-01..03, TC-LOGOUT-01 | P1/P2 |
| Authorization (RBAC) | TC-RBAC-01..03 | P1/P2 |
| Dashboard / master data / route | TC-DASH-01, TC-MD-01, TC-ROUTE-01 | P1/P2 |
| Field execution | TC-VISIT-01, TC-ORDER-01..02, TC-CHECKOUT-01 | P1/P2 |
| Approval / PDF | TC-APPR-01..03, TC-PDF-01 | P1/P3 |
| Data / BigQuery | TC-BQ-01..02 | P1 |
| Notifications | TC-NOTIF-01 | P2 |
| Offline (mobile) | TC-OFFLINE-01..03 | P1/P2 |
| Power BI | TC-PBI-01 | P2 |

**Release sign-off rule:** all **P1** cases Pass, no open **P1** defect. P2/P3 failures require a logged, triaged waiver (see [14 bug management] once authored, and [10 audit](10-production-readiness-audit.md)).

### Result log
| Test Case ID | Env | Tester | Date | Result (Pass/Fail) | Defect ref | Notes |
|---|---|---|---|---|---|---|
| | | | | | | |
