# 02 — Business Rules (As-Built)

## Roles

| Role value | Who | Mobile | Web |
|---|---|---|---|
| `salesman` (legacy alias: `se`) | Field sales (SE) | Full SE flow | no access to admin pages |
| `spv` | Supervisor | SPV dashboard, approval queue, team | Visit & Order, approvals, targets, route planner |
| `asm` | Area Sales Manager | — | View access; **no working approve transition (known issue R1)** |
| `dm` | Distributor Manager / Distributor Admin | — | SPV-approved visits only, final qty/price, invoice adjustment, PDF, final approval |
| `ho_admin` | Head Office admin | — | Everything incl. Administration, Import/Export; final approval |
| `demo` | Demo | Unrestricted views | limited nav |

Legacy role values still present in `users`: `se` (treated as `salesman` by the backend), `distributor_admin` (NOT recognized — must be normalized to `dm`).

## Business Units (formerly "brand group")

| Code (stored) | Display | Brands (as stored in master_product — UPPERCASE) |
|---|---|---|
| `SKT` | Business Unit 1 | SKINTIFIC, TIMEPHORIA, FACERINNA |
| `G2G` | Business Unit 2 | G2G (Glad2Glow), BODIBREZE, NEXTPRIME |
| `DEMO` / NULL | unrestricted | all |

Rules:
- A BU-scoped salesman sees/orders **only their BU's brands** — enforced server-side (`/product` filter + checkout/submit guards) **and** client-side (mobile `groupSkus`).
- **All brand comparisons are case-insensitive** (uppercase both sides). This is mandatory: `master_product.brand` is UPPERCASE while other tables (`spv_target`) hold mixed case. Violating this reintroduces the empty-product-list / checkout-403 bug fixed 2026-07-15.
- SKUs **without a valid price** (`COALESCE(price_for_store, srp, 0) <= 0`) are excluded from ordering everywhere.
- Data values `SKT`/`G2G` are never migrated — only display labels say "Business Unit".

## Visit lifecycle

```
CHECK-IN ──▶ ORDER ENTRY (survey) ──▶ CHECK-OUT ──▶ SUBMIT
   │              │                       │            │
 photo WAJIB   qty per SKU            Total Rupiah   items land in BigQuery
 GPS recorded  (BU-filtered,          summary        status → PENDING_SPV
 (info only)   priced SKUs only)
```

- `visit_status`: `CHECKED_IN → CHECKED_OUT → SUBMITTED`
- **Items are only written to BigQuery at SUBMIT** (not at checkout) — a checked-out-but-unsubmitted visit has 0 server items by design.
- **Effective Call = any item with qty > 0** (quantity-based, not monetary).
- `total_demand` is recomputed server-side from submitted items (client value not trusted).
- A submitted (or later) visit is **read-only** on mobile — reopening the store shows the summary; no re-check-in, no edit.
- Skipped stores: SE marks "Terlewat" → batch-sent to SPV → SPV returns to salesman or executes themselves.

## Approval flow (One-Line-Management)

```
SE submits ──▶ PENDING_SPV ──(spv approves)──▶ SPV_APPROVED ──(dm | ho_admin)──▶ COMPLETED
                    │                                │
                    └──(spv rejects)──▶ REVISION_REQUIRED ──(SE resubmits)──▶ PENDING_SPV
```

State machine (backend `_next_approval_status`): only `spv` can do the first approval; only `dm`/`ho_admin` can complete. **ASM has no transition** (known issue R1 — the web button 403s).

One-Line-Management (since 2026-07-15):
- An SPV's **visit list, approve, and reject are scoped to their own salesmen**, resolved via `dim_salesman.spv_name = users.full_name` (case-insensitive, cached 5 min).
- Cross-line action → `403 "Kunjungan ini milik salesman SPV lain"`.
- **Graceful fallback:** an SPV with zero mapped salesmen falls back to BU-wide scoping (keeps test/unmapped accounts working). Fixing an SPV's team = fixing `dim_salesman.spv_name` rows; takes effect ≤5 min, no deploy.
- DM scope: own `distributor_code` outlets, `SPV_APPROVED`/`COMPLETED` statuses only.
- SPV↔Distributor-Admin many-to-many mapping: **no data model exists yet** — backlog, needs product definition.

## Distributor admin economics (web Visit Detail)
- **Harga Rekomendasi** = STP (per-PCS recommended price) — display only.
- **Harga Toko / PCS** = actual selling price; **pre-filled from STP**, editable by DM/HO while status allows.
- Qty Final: SPV may adjust while `PENDING_SPV`; DM/HO after `SPV_APPROVED`.
- **Invoice adjustment** (delivery fee/discount/promo, ±Rp with note): DM/HO only. Display: Subtotal → Adjustment → **Final Invoice**. Persists in `step_visit.adjustment_amount/_note` (requires migration 005).
- PDF: filename `{StoreName}_{ddMMyyyy}.pdf`; includes pack size, Business Unit label, and the Final Invoice block. Downloads are audit-logged (`step_visit_download_log`).

## Offline & synchronization rules (mobile)
- Full visit flow works offline; data persists in SQLite (`local_visits`) with `sync_status: local → syncing → synced | failed`.
- Sync replays: (checkin if no `server_visit_id`) → checkout → submit; server timestamps honor `captured_at`.
- **Idempotency:** checkin dedupes by `schedule_id`; submit returns existing state if already `SUBMITTED`; failed partial item inserts are wiped and rewritten on retry.
- **Single-flight:** only one flush runs at a time (mutex); network-restore triggers are debounced 2 s; connectivity is re-checked between visits; rows stuck in `syncing` (app killed mid-flush) auto-reset to `local` on next launch.
- Route List shows per-store sync state: 🟡 **Local** (on device only) / 🟢 **Tersinkron** (on server).
- GPS: recorded and distance-warned (>200 m), never blocks any operation.
- Check-in **photo is mandatory**; camera on device, gallery on web build.
