# STEP — End-to-End Manual Testing Scripts

**Date:** 2026-07-13
**Covers:** Full field-to-approval lifecycle for both business groups, exercising every rule touched by this sprint (brand filtering, Order terminology, price template, invoice adjustment, PDF, offline sync).
**Apps under test:** STEP Mobile (Android APK, v1.4.0) + STEP Web (Vite build).

---

## Test accounts

> These must exist in `sfa_web.users`. The repo seeds them via `backend/create_test_users.py` / `create_bulk_users.py` (default password **`STEP@2026`** — change before production). Confirm/adjust with the data team; fill real usernames in the blanks before running.

| Role | Purpose | Username | Password |
|---|---|---|---|
| Salesman (BU 1 / SKT) | Flow 1 field user | `test_se` (alt: `demo`) | `STEP@2026` |
| Salesman (BU 2 / G2G) | Flow 2 field user | *create/assign a G2G SE account* | `STEP@2026` |
| SPV | Approves visits (both flows) | `test_spv` (unmapped → BU-wide scope) | `STEP@2026` |
| DM / Distributor Admin | Final qty, store price, invoice adjustment, PDF | `test_dist` (⚠ normalize role to `dm` first) | `STEP@2026` |
| HO Admin | Administration, unrestricted view | `admin` | `Step@2026!` |

> ⚠ Seeded defaults — rotate before real go-live. Role/BU changes require the user to re-login (JWT carries them).

**Preconditions:** each salesman has a route (PJP) with ≥3 stores for today; SKUs exist for each brand group; device has camera + location permission; a second run should be done with airplane mode toggled to test offline.

---

## FLOW 1 — Skintific Group (SKT)

**Goal:** A Skintific salesman only ever sees SKT brands; the full Login→Route→Visit→Order→Checkout→Submit→Approval→PDF→Sync path works end to end.

### 1.1 Login (Mobile)
| # | Step | Expected |
|---|---|---|
| 1 | Launch APK | Landing page shows **Skintific logo + "SKINTIFIC" wordmark** above "STEP" |
| 2 | Enter SKT salesman creds, tap Masuk | Lands on SE Home; header greeting + today's date |
| 3 | Observe tab bar | 5 tabs: Home, Rute, Riwayat, Info, **Profil** |

### 1.2 Route
| # | Step | Expected |
|---|---|---|
| 4 | Open **Rute** tab | Today's stores listed with status legend (Belum/Terlewat/Check-in/Checkout/Disubmit) |
| 5 | Note a not-yet-visited store | No sync pill shown (nothing to sync yet) |

### 1.3 Visit + Order (brand filtering — critical)
| # | Step | Expected |
|---|---|---|
| 6 | Tap a store → Check-in | GPS fetched (informational), **photo required** before Check-in enables |
| 7 | Take photo, Check-in | Advances to **Input Order** (survey) |
| 8 | Inspect brand tabs & product list | **ONLY Skintific / Timephoria / Facerinna appear. NO G2G/Bodibreze/Nextprime anywhere** (list, tabs, or search) |
| 9 | Search "G2G" | **Zero results** (filtered out) |
| 10 | Set qty on 2–3 SKT products | EC badge flips to "Efektif"; header shows "X SKU · Y pcs" |

### 1.4 Checkout
| # | Step | Expected |
|---|---|---|
| 11 | Lanjut Check-out | Summary card shows **Total SKU, Total Qty, and Total Rupiah** (new) |
| 12 | Inspect "Ringkasan Order" (renamed from Demand Summary) | Grouped by SKT brand; only SKT items |
| 13 | Submit ke SPV | Success; returns to Home; Route store now "Disubmit" |
| 14 | Back on Route list | Store shows **🟢 Tersinkron** pill (online submit) |

### 1.5 Approval (Web — SPV)
| # | Step | Expected |
|---|---|---|
| 15 | Login Web as SPV → **Visit & Order** (renamed) | The submitted visit appears under "Menunggu SPV" |
| 16 | Open it | Header shows store/salesman once (no duplicate salesman rows); table shows **Harga Rekomendasi** (STP/pcs) column |
| 17 | Edit Qty Final on one line, Save | Total Order (Final) updates |
| 18 | Approve | Status → SPV Approved; salesman gets a notification |

### 1.6 Distributor Admin — price, adjustment, PDF (Web — DM)
| # | Step | Expected |
|---|---|---|
| 19 | Login as DM → open the SPV-approved visit | "Edit Qty & Harga" available |
| 20 | Enter Edit; check **Harga Toko / PCS** column | Pre-filled from **Harga Rekomendasi (STP)**; editable |
| 21 | Change one price, Save | Total Harga recomputes |
| 22 | **Penyesuaian Invoice** card → Tambah | Enter e.g. `+50000` note "Ongkos kirim" → Save |
| 23 | Observe summary | Subtotal / Adjustment (+Rp 50.000) / **Final Invoice** shown |
| 24 | Try negative adj (e.g. `-25000` "Diskon") | Final Invoice reduces; adjustment shows in red |
| 25 | Approve to COMPLETED | Status COMPLETED |
| 26 | **Unduh PDF** | File downloads named **`{Store}_{ddMMyyyy}.pdf`** (e.g. `Guardian_Bandung_13072026.pdf`) |
| 27 | Open PDF | Header "SURAT PENAWARAN ORDER"; "DETAIL PRODUK ORDER"; **Subtotal / Adjustment / Final Invoice** block; Harga Toko/PCS column |

### 1.7 Offline sync (repeat 1.3–1.4 in airplane mode)
| # | Step | Expected |
|---|---|---|
| 28 | Enable airplane mode, do a full visit + submit | "Data tersimpan lokal" message |
| 29 | Route list | Store shows **🟡 Local** pill |
| 30 | Disable airplane mode, pull-to-refresh Home | Sync runs; pill flips to **🟢 Tersinkron** |
| 31 | Web SPV view | The offline visit now appears server-side, items intact |

**Flow 1 pass criteria:** no G2G brand ever visible to SKT user; Total Rupiah shown; Order terminology everywhere; price template pre-fills; adjustment math correct; PDF filename + content correct; offline→online sync lands items in BigQuery via web.

---

## FLOW 2 — G2G Group

**Goal:** Same lifecycle with a G2G salesman; verify the mirror-image brand isolation and that G2G orders reach Web (the previously-reported "unsupported brands not synced" issue).

Repeat **all steps 1–31** with the G2G salesman account, asserting:

| Check | Expected |
|---|---|
| Product list / tabs / search (step 8–9) | **ONLY G2G / Bodibreze / Nextprime**. NO Skintific/Timephoria/Facerinna |
| Search "Skintific" | Zero results |
| Checkout Ringkasan Order | Only G2G-group items |
| Submit → Web SPV | **G2G visit + items appear on Web** (confirms brand-group orders now synchronize correctly) |
| Approval → DM price/adjustment/PDF | PDF header + Final Invoice correct; `Grup Brand` field = G2G |
| Offline run | 🟡 Local → 🟢 Tersinkron as in Flow 1 |

**Flow 2 pass criteria:** perfect brand isolation for G2G; G2G orders fully visible and approvable on Web; PDF/adjustment identical behavior.

---

## Cross-cutting regression checks (both flows)

| Area | Check |
|---|---|
| RBAC | Salesman cannot see Web admin pages; ASM "Approve" button behavior noted (see Known Issues re: ASM in approval chain) |
| Notifications | Submit → SPV notified; Approve → salesman notified; unread badge on Profil tab |
| Revision | SPV rejects → salesman sees "Perlu Revisi" → RevisionEdit → resubmit works |
| Skipped store | Mark store "Terlewat" → "Kirim ke SPV" → appears in SPV queue |
| Terminology | Grep the UI: no visible "Demand" remains where "Order" is intended (labels, headers, PDF, checkout) |
| Migration gate | If migration 005 NOT yet run: adjustment silently no-ops (Final Invoice = Subtotal), app does not error |

---

## Result log template

| Flow | Step range | Tester | Date | Result (Pass/Fail) | Notes |
|---|---|---|---|---|---|
| 1 (SKT) | 1–31 | | | | |
| 2 (G2G) | 1–31 | | | | |
| Regression | all | | | | |
