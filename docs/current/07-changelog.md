# 07 — Changelog

## v1.4.2 / web-backend `17582fb` — 2026-07-15 "Business Unit case-fix & One-Line-Management"

### 🔴 Root-cause fix: SFA data not appearing in STEP Web
`gt_schema.master_product.brand` values are **UPPERCASE**, but every `BRAND_GROUPS` list was Title-case. For BU-scoped salesmen this caused (a) empty product lists (case-sensitive SQL `IN`) and (b) 403 on checkout/submit (brand guard) — so orders never reached the server. Accounts with `brand_group NULL` bypassed both, which masked the bug during early testing and *also* made their visits invisible to BU-scoped SPVs. **All brand comparisons are now case-insensitive** across backend (`dependencies`, `product`, `visit`, `target_web`) and mobile.

### Backend
- **One-Line-Management**: new `spv_salesman_filter` — SPV visit list, approve, and reject scoped to own salesmen via `dim_salesman.spv_name` (5-min cache; graceful BU-wide fallback for unmapped SPVs). Cross-line action → 403.
- `/product`: returns `pack_size`; excludes SKUs with no valid price; case-safe BU derivation.
- Visit detail: items now join `master_product` → `sku_size` (pack size) for web table + PDF.
- Legacy role `se` scoped like `salesman` in visit list.
- PDF: product names show pack size; label "Business Unit".

### Mobile (v1.4.2, versionCode 11)
- Hide unpriced SKUs at the single filtered source (list/search/tabs/totals stay consistent).
- Pack-size badges on product list; pack size on checkout summary + visit detail.
- Submitted/checked-out visits open a **read-only summary** (no re-check-in).
- Sync hardening: in-flight mutex, 2 s debounced network-restore, per-visit connectivity re-check, stuck-`syncing` crash recovery, global cache invalidation after flush.
- Home KPI auto-refreshes on focus and after sync.
- Business Unit brand lists uppercase (mirror of backend).
- Tests: 12/12 (new mid-flush-drop case).

### Terminology
"Brand Group / Grup Bisnis / Grup Brand" → **Business Unit** (labels only; stored values remain `SKT`/`G2G`). BU 1 = SKINTIFIC, TIMEPHORIA, FACERINNA · BU 2 = G2G (Glad2Glow), BODIBREZE, NEXTPRIME.

---

## web-backend `09de89b` — 2026-07-13/14 "UAT hotfixes"
- **Visit Detail crash fixed (React #310)**: 8 `useMemo` hooks sat below the loading/error early returns → success render ran more hooks than loading render → crash on every cold navigation. Memos hoisted above returns over a null-safe memoized `items`. **ESLint `react-hooks/rules-of-hooks=error` added** (the plugin didn't exist in the project — why this shipped silently). Fixed in both repos during the `sfa-step` repo cutover.
- Test-account data fixes (`demo`/`test_spv` BU, `test_dist` role) diagnosed via BigQuery.

## v1.4.1 / `2f8dd14` — 2026-07-13 "Order terminology & distributor economics"
- Demand → **Order** across web UI, mobile, and PDF.
- Visit detail: "Harga Rekomendasi" (= STP/pcs) pre-fills editable "Harga Toko / PCS".
- **Invoice adjustment** (±Rp + note; Subtotal/Adjustment/Final Invoice) — web card, endpoint, PDF block, migration 005.
- PDF filename `{StoreName}_{ddMMyyyy}.pdf`.
- Mobile: BU filtering (first pass), checkout Total Rupiah, Route List 🟡 Local/🟢 Tersinkron pills, "Logout" text labels, Skintific login branding.
- Salesman info de-duplicated on visit detail.

## v1.4.0 — 2026-07-13 morning
- Mobile: Profile & Notifications screens, Profil tab with unread badge; SPV home crash fix (`VisitDetail` param shape); TeamOverview progress bars; checkin button disabled-state fix.
- Web: dead "Revisi & Submit Ulang" button replaced with guidance notice.

## Earlier
Original platform build: visit lifecycle, approval chain, offline sync, route planner, dashboards, PDF v1 — see design docs `docs/01…10`.
