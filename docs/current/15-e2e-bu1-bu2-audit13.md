# 15 — BU-1 (SKT) & BU-2 (G2G) E2E Test Script — audit-13 branch

**Under test:** `sfa-step @ fix/authz-consistency-audit13`, `sfa-mobile @ fix/sync-issues` (canary Cloud Run revision).
**Builds on:** [08-e2e-test-scripts](08-e2e-test-scripts.md) (the base BU-1/BU-2 lifecycle). This doc keeps that lifecycle and adds the audit-13 behaviors, per BU.
**Precondition:** migrations `003_approval_linkage.sql` + `004_token_version.sql` applied ✅.

> **What's new for BU testing:** brand isolation used to be **UI-only** (the product list hid other-BU SKUs). Audit-13 makes it **server-enforced** — an SKT user hitting a G2G store/salesman/target by ID now gets **404/403**, not leaked data (E2E-03/04). So each BU flow now includes a "try to reach the *other* BU" negative check.

---

## 0. Accounts

| Role | BU-1 (SKT) | BU-2 (G2G) | Password |
|---|---|---|---|
| Salesman (SE) | `test_se` (or `demo`) | **needs a G2G SE — see below** | `STEP@2026` |
| SPV | `test_spv` (unmapped → BU-wide) | `test_spv` works for both, or a G2G-scoped SPV | `STEP@2026` |
| DM | `test_dist` | `test_dist` | `STEP@2026` |
| HO Admin | `admin` | `admin` | `Step@2026!` |

**Get a G2G salesman account** (the rotated creds only ship SKT ones). As `admin`, either:
- **Administration UI** → create user with **Brand Group = G2G** and link a G2G `salesman_sk`; or
- API: `POST /api/v1/auth/users` `{ "username":"test_se_g2g", "password":"STEP@2026", "role":"salesman", "brand_group":"G2G", "salesman_sk":"<a G2G salesman_sk>" }`.
- Find a G2G `salesman_sk`: `GET /api/v1/salesman/list?limit=200` as admin → pick a row with `brand_group":"G2G"`.

**API base (canary):** `https://audit13---step-api-141828905128.asia-southeast1.run.app/api/v1`

---

## PART A — BU-1: Skintific (SKT)

Brands in scope: **Skintific, Timephoria, Facerinna**. Out of scope: G2G, Bodibreze, Nextprime.

### A1. Login & session (mobile)
| # | Step | Expected |
|---|---|---|
| A1.1 | Login `test_se` | Lands on SE Home; SKINTIFIC branding. |
| A1.2 | **Airplane mode → force-quit → relaunch** | **Still logged in** (offline session restored, E2E-25) — not bounced to Login. |
| A1.3 | Back online → Profil → **Logout**, then relaunch | At Login; the old session is dead server-side (E2E-14). |

### A2. Route → Visit → Order (brand isolation, UI)
| # | Step | Expected |
|---|---|---|
| A2.1 | Rute → open a store → photo → Check-in | Advances to Input Order. |
| A2.2 | Brand tabs / product list / search "G2G" | **Only SKT brands; zero G2G results** (UI filter). |
| A2.3 | Set qty on 2–3 SKT SKUs | EC flips to "Efektif"; header "X SKU · Y pcs". |
| A2.4 | Lanjut Check-out | Summary shows Total SKU / Qty / **Total Rupiah**. |

### A3. Consistency: final-qty flows to totals (E2E-06) ⚑ key data check
| # | Step | Expected |
|---|---|---|
| A3.1 | Submit the visit (e.g. 10 pcs × Rp 89.000 = **890.000**) | Route store → "Disubmit" → 🟢 Tersinkron. |
| A3.2 | **Note the handheld "Total Rupiah"** and later the web/PDF total | **Identical to the rupiah** (rounding parity, E2E-33). |
| A3.3 | Web SPV → open visit → set **Qty Final = 4** on that line → Save & Approve | Total Order (Final) = **356.000**. |
| A3.4 | Web → Salesman 360 / Dashboard for that SE | Sell-in reflects **356.000**, *not* 890.000 (previously it stayed 890.000). |

### A4. Approval chain
| # | Step | Expected |
|---|---|---|
| A4.1 | SPV approves (A3.3) | Status → SPV Approved; SE notified. **Only this SE's SPV is paged**, not all SPVs (E2E-11). |
| A4.2 | DM opens SPV-approved visit → price + `+50000` adjustment → Approve to COMPLETED → **Unduh PDF** | Final Invoice math correct; PDF `{Store}_{ddMMyyyy}.pdf`. |
| A4.3 | SE (mobile) **resubmit a COMPLETED visit** (shouldn't be offered, but via any stale path) | Rejected — resubmit only allowed from "Perlu Revisi" (E2E-01). |

### A5. Target approval — create → approve → **enact** (E2E-07/04) ⚑ new feature
| # | Step | Expected |
|---|---|---|
| A5.1 | Get an **SKT** `spv_target_id` + current value (`GET /target/spv?brand=Skintific&period_month=<1st>` as admin) | note ID + amount. |
| A5.2 | As `test_spv` file a linked request (`POST /approvals`, `entity_type:spv_target`, that ID, `proposed_value:"12345"`) | 201, `enactable:true`, `brand_group:"SKT"`. |
| A5.3 | As `admin` → Approvals → open it → **Setujui** | Toast "disetujui & **diterapkan**"; `applied:true`. |
| A5.4 | Re-read the target | value = **12345**, `approval_status = approved`. |
| A5.5 | Approve the **same** request again | **409/400** (already decided, E2E-13 — no double-apply). |
| A5.6 | File another, then **Minta Revisi** (comment required) | Moves to History as **Revisi** (E2E-28). |

### A6. Cross-BU negative checks (SKT user must NOT reach G2G) ⚑ headline BU check
Run as `test_se`/`test_spv` (SKT) against the API (URL-level, since the UI hides these):
| # | Call | Expected |
|---|---|---|
| A6.1 | `GET /salesman/360/<a G2G salesman_sk>` | **404** (was: leaked profile). |
| A6.2 | `GET /store/360/<a G2G outlet_id>` | **404**. |
| A6.3 | `GET /evaluate/salesman/<G2G sk>` | **404**. |
| A6.4 | `GET /outlet/list` / `GET /pjp/list` | **No G2G-brand outlets** in results (NULL-brand shared stores still appear). |
| A6.5 | As an SKT approver, approve a **G2G-linked** target request | **403** out-of-scope (E2E-04). |

---

## PART B — BU-2: Glad2Glow (G2G)

Brands in scope: **G2G, Bodibreze, Nextprime**. Out of scope: Skintific, Timephoria, Facerinna.

Repeat **A1–A5 with the G2G SE / G2G target**, asserting the mirror image:

| Check | Expected |
|---|---|
| B2 (brand UI) | Product list/tabs/search show **only G2G group**; search "Skintific" → zero. |
| B3 (consistency) | Same final-qty → total_demand propagation; handheld total == web/PDF. |
| B3 (sync) | **G2G visit + items appear on Web** (confirms brand-group orders sync — the old "unsupported brands not synced" bug). |
| B4 (approval) | PDF `Grup Brand = G2G`; Final Invoice correct; only the G2G SE's SPV paged. |
| B5 (target enact) | Use `GET /target/spv?brand=Glad2Glow` → file `spv_target` request → approve → value applied, `approved`; request `brand_group:"G2G"`. |

### B6. Cross-BU negative checks (G2G user must NOT reach SKT) — mirror of A6
| # | Call (as the G2G SE/SPV) | Expected |
|---|---|---|
| B6.1 | `GET /salesman/360/<an SKT salesman_sk>` | **404**. |
| B6.2 | `GET /store/360/<an SKT outlet_id>` | **404**. |
| B6.3 | `GET /outlet/list` / `pjp/list` | No Skintific/Timephoria/Facerinna outlets. |
| B6.4 | Approve an **SKT-linked** target request | **403**. |

---

## PART C — Shared security / robustness (run once, either BU)

| # | Check | Expected |
|---|---|---|
| C1 | **Session revocation:** login → `GET /auth/me` (200) → `POST /auth/logout` → reuse same token | **401** (E2E-14). |
| C2 | **Password reset kills sessions:** admin resets a user → that user's existing token | **401**. |
| C3 | **Visit IDOR:** as `test_se`, `GET`/`checkout`/`submit` a visit owned by `demo` | **403** (E2E-01). |
| C4 | **Check-in spoof:** `POST /visit/checkin` with a different `salesman_sk` → then `GET` the created visit | `salesman_sk` = **your own** token's, not the spoofed one (E2E-02). Future-dated `visit_date` → **422**. |
| C5 | **Negative qty:** submit an item `qty:-5` | **422** (E2E-10). |
| C6 | **Approval race:** two web tabs approve the same request | one succeeds, the other toasts a **409** reason (E2E-13). |
| C7 | **Outlet assign:** `POST /outlet/assign` `salesman_sk:"abc"` | **422**, not 500 (E2E-29). |
| C8 | **Import guard:** upload a `.txt` to `/import/salesman` | **422**; an >8 MB file → **413** (E2E-15/31). |
| C9 | **Offline sync (both BUs):** airplane-mode a full visit → back online → pull-to-refresh | 🟡 Local → 🟢 Tersinkron, no duplicate; a mixed-brand offline visit still syncs (E2E-26). |

---

## Result log

| Part | Scope | Tester | Date | Pass/Fail | Notes |
|---|---|---|---|---|---|
| A (SKT) | A1–A6 | | | | |
| B (G2G) | B1–B6 | | | | |
| C (shared) | C1–C9 | | | | |

**Overall pass criteria:** each BU completes the full lifecycle seeing only its own brands *both in UI and via API*; final-qty adjustments reconcile across visit detail / PDF / dashboards / 360; target requests approve-and-apply within-BU and are blocked cross-BU; sessions revoke on logout; no cross-user visit tampering; offline→online sync lands items with no duplicates.
