# 18 — Distributor RBAC + Multi-source Visit & Order + Excel Export

**Branch:** `feat/distributor-multisource-orders` · **Date:** 2026-08-18
**Status:** implemented and tested locally. **NOT deployed.**

> **Google Spreadsheet sources were added as additional sources. The existing
> STEP Handheld / SFA order integration was NOT removed or replaced.**
>
> `routers/visit.py`, `step_visit` and `step_visit_item` continue to serve the
> handheld and every existing SFA flow. The new `/orders` router only ever
> **reads**; nothing in this change writes to an SFA table.

---

## 1. Architecture overview

```
STEP Handheld (Expo RN) ──▶ sfa_web.step_visit / step_visit_item ──┐
                                                                   ├──▶ /api/v1/orders ──▶ Visit & Order
External Google Workbook ──▶ (sync) ──▶ sfa_web.ext_visit /        │        │
  `visit` + `visit_item` tabs           ext_visit_item ────────────┘        └──▶ /api/v1/orders/export (.xlsx)
```

Both sources live in BigQuery and are queried **independently**. The spreadsheet
source reads the already-synced mirror, **not** Google Sheets directly — so a
Google outage can only make the mirror stale, never break the page.

## 2. Authentication architecture

Unchanged. `POST /api/v1/auth/login` (bcrypt, legacy SHA256 fallback) issues a JWT
carrying `sub, username, role, territory, distributor_code, brand_group,
salesman_sk, tv`. `require_auth` decodes it into `UserContext`; `tv` is checked
against `users.token_version` for server-side revocation. The web client keeps the
token in `localStorage` via `authStore`.

## 3. Distributor RBAC

**The Distributor role is `dm`.** There is no separate "Distributor" role string —
`dm` is the existing role and `test_dist` is simply the one account holding it
(452 `se`, 111 `spv`, 15 `asm`, 1 `ho_admin`, 1 `dm`). No authorization anywhere
keys off a username.

## 4. Distributor allowed menus

Exactly five, enforced in `frontend/src/components/layout/nav.ts`:

| Menu | Path |
|---|---|
| Visit & Order | `/visits` |
| Approvals | `/approvals` |
| Import & Export | `/import-export` |
| Announcements | `/announcements` |
| Notifications | `/notifications` |

`dm` was removed from Dashboard, Route Planner, Master Data PJP, Master Salesman,
Target Management, Outlet & Salesman, Route Evaluate, Store Opportunity, Store
360°, Salesman 360°. It never had Administration.

Because Visit & Order lives inside the **Reports** group, and a Distributor must
not see "Reports" at all, `visibleNavFor(role)` promotes a group whose visible
children collapse to one entry into a top-level link. Roles with two or more
visible children in a group are unaffected, so no other role's menu changes.

## 5. Protected routes

Route-level RBAC **did not exist before this change** — `App.tsx` only guarded
authenticated-vs-not, so any logged-in user could open `/administration` by typing
the URL (the backend still refused the data, but the shell rendered).

`RoleGuard` now wraps every page under the layout and derives permission from
`NAV_TREE` via `canAccessPath(role, pathname)`, so the menu and the router can
never disagree. A Distributor entering `/dashboard`, `/master-data-pjp`,
`/reports`, `/administration` … is redirected to its own landing route.

`defaultPathFor(role)` replaced three hard-coded `/dashboard` redirects (index,
post-login, unknown-path fallback) — `/dashboard` is not a universal home.
For `dm` it resolves to `/visits`.

## 6. Existing SFA data flow

`STEP Handheld → POST /visit/checkin|checkout|submit → sfa_web.step_visit(+_item)
→ GET /api/v1/visit → Visit & Order`. **Untouched**, except that the `dm` branch
of the list query now fails closed (§11).

## 7 & 8. Google Spreadsheet sources

Both GIDs in the request belong to the **same workbook**:

| Spec label | GID | Actual tab | Role |
|---|---|---|---|
| Source 1 | `247800996` | `visit` | order/visit **header** |
| Source 2 | `1151973955` | `visit_item` | order **line items** |

**The "Source 2" URL contains a typo.** Its spreadsheet id is 43 characters —
`1U7O8vNLXztfFduS2ehAvpLWEq-iJRE_zzjPYYTezr0` — the 44-character id from Source 1
with the `Z` dropped. It resolves to nothing (an HTML error page). The correct id
is `1U7O8vNLXztfFduS2ehAvpLWEq-iJRE_zzjPYYTezrZ0`, verified for both GIDs.

Consequently these are **not two independent order feeds**; they are a parent and
its children. Modelling them as separate sources would make "Source = Spreadsheet
2" return line items with no order number, store, date or status. They are
therefore joined into **one** logical source, `SPREADSHEET`.

## 9. Spreadsheet schemas

`visit`: `visit_id, schedule_id, visit_type, username, store_id, visit_date,
checkin_time, checkin_latitude, checkin_longitude, checkin_distance_meter,
checkin_photo_url, checkout_time, checkout_latitude, checkout_longitude,
checkout_distance_meter, checkout_photo_url, notes, duration_minutes,
total_demand, effective_call, visit_status, created_at, updated_at`

`visit_item`: `visit_item_id, visit_id, sku_id, qty, stp, demand, created_at, updated_at`

Mapping is header-based, never positional. Conventions (established from the
workbook's populated tabs): dates are day-first `DD/MM/YYYY`, timestamps are
ISO-8601 with an explicit `Z`, numbers use comma as a **thousands** separator
(`89,320` = 89320 IDR). Full detail in [doc 17](17-external-distributor-transactions.md).

## 10. Source → normalized model mapping

| normalized | SFA (`step_visit`) | Spreadsheet (`ext_visit`) |
|---|---|---|
| `source` | `"SFA"` | `"SPREADSHEET"` |
| `source_label` | "STEP Handheld / SFA" | "Spreadsheet" |
| `order_id` | `visit_id` | `ext_visit_id` |
| `order_number` | `visit_id` | `ext_visit_id` |
| `order_date` | `visit_date` | `visit_date` |
| `store_id` | `dim_outlet.source_outlet_code` | `source_store_id` |
| `store_name` | `dim_outlet.store_name` | `store_name` |
| `distributor_code` | `dim_outlet.distributor_code` | `distributor_code` |
| `distributor_name` | `dim_outlet.distributor_name` | **null** — the workbook has none |
| `salesman_name` | `dim_salesman.salesman_name` | `salesman_name` |
| `item_count` | `COUNT(step_visit_item)` | `item_count` |
| `quantity` | `SUM(COALESCE(final_qty, qty))` | `computed_qty` |
| `order_value` | `total_demand` | `computed_value` |
| `status` | `approval_status` | `visit_status` |

Item level: SFA `sku_id/sku_name/qty|final_qty/stp/demand` and spreadsheet
`sku_id/sku_name/qty/stp/line_value` → `sku, product_name, quantity, unit_price,
line_value`. Fields a source does not have stay **null**; nothing is fabricated.

## 11. Distributor filtering logic

The pre-existing rule was "a `dm` sees only its own distributor's outlets", but it
**failed open**: when `distributor_code` was NULL the predicate was skipped
entirely, so the account saw every distributor. `test_dist` had exactly that —
NULL — and could see all 15 eligible orders.

Now `distributor_predicate()` is shared by both sources and **fails closed**: a
`dm` with no `distributor_code` matches nothing. `test_dist` was assigned
`DST157` (CV Dimas Kediri, 7 orders).

The existing `dm` rule that only `SPV_APPROVED`/`COMPLETED` orders are visible is
preserved. Other roles keep their own scoping — `/orders` reuses the very same
`brand_group_filter` and `spv_salesman_filter` helpers `routers/visit.py` uses, so
the unified list can never be laxer than the list it supplements.

> **Existing user sessions must re-login.** `distributor_code` is a JWT claim, so
> a token minted before the update still carries NULL and (correctly) sees nothing.

## 12–14. Visit & Order architecture, source filtering, order detail

One row per **order**, never per item: items are aggregated onto the header in SQL
(`item_count`, `quantity`, `order_value`), so a 5-item order is structurally one
table row. No deduplication is performed at all — see §10 of the request; the two
sources have disjoint identifier spaces and no cross-source dedup rule was needed
or invented.

Source filter: **All** (default) / **STEP Handheld / SFA** / **Spreadsheet**. The
`Sumber` column labels every row, so provenance never requires opening a detail.

Detail: an **SFA** order opens the existing `/visits/:id` page unchanged
(approvals, PDF, item edits). A **spreadsheet** order opens a modal listing the
fields the workbook actually has. `/orders/detail` re-runs the scoped list query
before returning items, so an out-of-scope id yields nothing.

## 15. Excel export behaviour

`GET /orders/export` builds an `.xlsx` with openpyxl and applies **the same
filters and the same scoping as the list**, so the workbook can never contain a
row the user could not see on screen. Paging is deliberately not applied — the
export is the whole filtered set.

- **Sheet 1 "Order Summary"** — one row per order: Source, Order Number, Order
  Date, Store ID, Store Name, Distributor Code, Distributor Name, Salesman,
  Items, Quantity, Order Value, Status.
- **Sheet 2 "Order Details"** — one row per line item: Source, Order Number,
  Order Date, Store ID, Store Name, SKU, Product Name, Quantity, Unit Price,
  Line Value.

SKU and product are item-level attributes, which is why they live on sheet 2
rather than being duplicated across order rows. Filename:
`VisitOrder_<AllSources|SFA|Spreadsheet>_<YYYYMMDD_HHMM>.xlsx` (Asia/Jakarta).

## 16. Error handling

| condition | behaviour |
|---|---|
| one source fails | that source returns `ok: false` + a generic message in `sources[]`; **the other source's orders are still returned and rendered**, with an amber banner |
| both fail | empty table + "Data order tidak dapat dimuat" |
| read model missing (migration 007 not run) | spreadsheet source reports unavailable; SFA unaffected |
| no rows match | "Tidak ada order untuk filter yang dipilih." |
| result cap hit | `truncated: true` → banner asking the user to narrow filters |
| export failure | toast; the page stays usable |

Raw BigQuery/Google errors are never returned to the browser — they are logged
server-side with the exception class only.

## 17. Caching / refresh behaviour

React Query holds a result 60 s; filter changes re-query. An explicit **Refresh**
button invalidates the cache and a "Diperbarui HH:MM" stamp shows data age. Google
Sheets is never contacted by a page interaction — only by the sync job.

## 18–19. Files changed

**Backend**
- `backend/services/orders.py` ✚ — multi-source reader, scoping, sort, summarise
- `backend/routers/orders.py` ✚ — `/orders`, `/orders/detail`, `/orders/export`
- `backend/models/order.py` ✚ — normalized order/item/source-status models
- `backend/tests/test_orders.py` ✚ — 21 unit tests
- `backend/routers/visit.py` — `dm` scoping now fails closed (7 lines)
- `backend/routers/import_export.py` — fixed `/export/visits` 500 (pre-existing)
- `backend/main.py` — register the orders router (2 lines)
- `backend/requirements.txt` — `openpyxl==3.1.5`

**Frontend**
- `frontend/src/pages/Visits.tsx` — multi-source Visit & Order
- `frontend/src/api/orders.ts` ✚ — list / detail / export client
- `frontend/src/components/layout/nav.ts` — dm restricted; access-control helpers
- `frontend/src/components/layout/nav.test.ts` — Distributor RBAC + route tests
- `frontend/src/components/layout/Sidebar.tsx` — render `visibleNavFor(role)`
- `frontend/src/App.tsx` — `RoleGuard`, `HomeRedirect`, retired route
- `frontend/src/types/index.ts` — order types
- `frontend/src/pages/ExtTransactions.tsx` ✖ deleted · `frontend/src/api/extTransaction.ts` ✖ deleted

**Data:** `sfa_web.users` — `test_dist.distributor_code` set to `DST157`.

## 20–21. Tests performed and results

| suite | result |
|---|---|
| Backend unit (`pytest`, BQ-free) | **103 passed** (21 orders + 58 ext + 24 audit-13) |
| Backend collection | 154 tests, no import breakage |
| `/orders` end-to-end vs real BigQuery | **45 passed** |
| `/ext-transaction` end-to-end (regression) | **36 passed** |
| Cross-role regression vs real BigQuery | **22 passed** |
| Frontend `tsc --noEmit` | clean |
| Frontend `npm run build` | clean |
| Frontend `vitest` | **34 passed** |

End-to-end coverage includes: dm scoped to its own distributor; two distributors
returning **disjoint** order sets; dm with no distributor_code seeing nothing;
per-source status reporting; `source=SFA` / `source=SPREADSHEET` filters; no
order fan-out; summary correctness; date/status/search filters; SQL-injection
attempts in `sort_by`/`sort_order` neutralised; role gate (se/salesman/demo/anonymous
refused); detail scoping across distributors; export is a real xlsx with both
sheets, a Source column, a row count matching the UI, and filter fidelity.

Regression covers `/visit` for all four web roles, ho_admin scope not narrowed,
`/approvals`, `/announcement`, `/notification`, `/export/visits`, and the
spreadsheet sync path.

## 22. Known limitations

1. **The spreadsheet source contains zero orders.** Both tabs are header-only, so
   every spreadsheet path is verified structurally (empty result, correct source
   status, header-only export) but not against real order rows.
2. **"Spreadsheet 1" and "Spreadsheet 2" are one source**, for the reason in §7.
   If a genuinely separate second workbook exists, adding it is a config entry
   plus one reader — the model already carries `source` per row.
3. **Merge cap `MAX_MERGE = 2000` per source.** Sorting and paginating a merged
   list requires both sides in memory. Beyond that the response sets
   `truncated: true` and the UI says so. Current volumes: 35 SFA, 0 spreadsheet.
4. **Spreadsheet orders have no distributor name** — the workbook has no such
   column; only `distributor_code` resolved via `dim_outlet`.
5. **Only 43.5% of the workbook's stores resolve** to a STEP outlet, so unmapped
   spreadsheet orders have no `distributor_code` and are invisible to every `dm`
   (deliberately fail-closed).
6. **`/export/visits` returns 404 "No data found"** for the current month because
   SFA data is from July — correct behaviour, not a fault.
7. Sync remains manual/scheduled; the mirror is only as fresh as the last run.

## 23. Deployment instructions

1. Merge `feat/distributor-multisource-orders`.
2. Backend (**manual**): `cd backend && .\deploy_to_cloudrun.ps1`, then **verify
   traffic actually moved** — this service pins traffic, so a deploy alone serves
   0%. Tag the new revision, smoke-test it, then
   `gcloud run services update-traffic step-api --to-revisions <rev>=100`.
   `openpyxl` is a new dependency, so the image **must** be rebuilt.
3. Frontend deploys itself from `main` via Vercel.
4. No migration required — migration 007 is already applied.
5. Tell `test_dist` to log out and back in so its JWT picks up `DST157`.

## 24. Rollback instructions

- **Backend:** `gcloud run services update-traffic step-api --to-revisions <previous>=100`.
- **Frontend:** revert the merge commit and push; Vercel redeploys.
- **Data:** `UPDATE sfa_web.users SET distributor_code = NULL WHERE username = 'test_dist'`
  (restores the previous state, and with it the fail-open behaviour — not advised).
- No schema changes were made, so there is nothing to un-migrate. `/orders` is
  additive: removing it cannot affect SFA, which continues to be served by
  `/visit` exactly as before.
