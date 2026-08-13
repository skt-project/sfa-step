# 13 — STEP Ecosystem End-to-End Audit (Web + Handheld)

**Date:** 2026-07-23 · **Scope:** `sfa-step` (FastAPI backend + React/Vite web + BigQuery) and `sfa-mobile` (Expo/React Native handheld)
**Method:** Static, code-level audit of the repositories as checked out (backend ≈11.3k LOC, web ≈7.6k LOC, mobile ≈7.5k LOC, plus SQL/DDL). Builds on [10-production-readiness-audit](10-production-readiness-audit.md) (F-01…F-11) and [ADR-0001](adr-0001-bigquery-as-transactional-store.md).

> **Verification boundary (read this first).** This is a *code* audit. I did **not** run the apps, execute against live BigQuery, hit the deployed API, drive the mobile build on a device/emulator, or measure real latency/bundle size. Findings are derived from reading the source and are labelled **CONFIRMED** (unambiguous in code) or **NEEDS-DYNAMIC-CHECK** (strongly indicated by code, but final severity depends on runtime data or an out-of-repo process). Performance numbers are structural inferences, not measurements. Treat the roadmap in §20 as the safe order to *validate then fix*.

---

## 1. Executive Summary

STEP is a well-structured, already-in-production system: clean FastAPI layering, bcrypt+JWT auth with legacy-hash migration, an offline-first mobile sync engine with a mutex and crash recovery, and an unusually strong as-built doc set. The prior hardening pass (F-01…F-11) closed the deploy/secrets/test-gap issues. Secrets hygiene remains clean — `.env` and `*-credentials.local.txt` are gitignored and **not** tracked.

This deeper pass finds the residual risk has moved from *ops* to **authorization, data-consistency, and workflow-enactment** — the classes that the "BigQuery-as-OLTP, integrity enforced in the app layer" decision (ADR-0001) makes the application solely responsible for, and which the app does not yet fully cover:

- **Object-level authorization is largely absent on the visit lifecycle.** `checkin` trusts the client-supplied `salesman_sk`; `checkout`/`submit`/`resubmit`/`GET /visit/{id}` perform **no ownership check** at all. Random unguessable visit IDs are the only thing preventing cross-user tampering. `resubmit` can even drive a `COMPLETED` visit back to `PENDING_SPV`.
- **Two core numbers can silently disagree with each other.** After an SPV adjusts final quantities, the visit *detail/PDF* recomputes from `final_qty`, but the `total_demand` column that every dashboard, report, and 360 reads is **never updated** — so operational totals and management reports diverge for the same visit.
- **The generic web Approvals workflow does not enact anything.** No backend endpoint inserts `approval_request` rows except the demo seed, and approving/rejecting only flips the request's own status — it never writes the `proposed_value` back to the target/master record.
- **Several "detail" endpoints skip the brand/territory scoping their sibling list endpoints apply** (Store 360, Salesman 360, Route-Evaluate detail, outlet/PJP lists), and a few cache keys omit the tenant scope, allowing cross-brand/cross-territory reads.

None of these are anonymous-exploitable (all require a valid login), and the ID-based ones are mitigated by unguessable UUIDs — but each is a real defect against the audit's own bar ("no invalid state transition," "stored values exactly match what is displayed," "identical business logic across platforms"). **Recommended posture: not a rollback, but a focused authorization + data-consistency remediation sprint before onboarding more distributors/brands, because every gap widens with tenant count.**

Counts: **2 Critical, 5 High, 12 Medium, 8 Low** (33 findings). Full register in §4; the 20 requested report sections follow.

---

## 2. Readiness scorecard (delta vs. audit 10)

| Domain | Status | Note |
|---|---|---|
| Architecture | 🟡 | Clean layering, but two datasets carry duplicate `dim_*`/visit tables with divergent schemas (E2E-21); approval queue not wired to a real source (E2E-07). |
| Security — authN | 🟢 | bcrypt+JWT, legacy migration, generic login errors. |
| Security — authZ | 🔴 | Broken object-level & function-level authz on the visit lifecycle and detail endpoints (E2E-01/02/03/04). |
| Data consistency | 🔴 | `final_qty`→`total_demand` divergence (E2E-06); resubmit trusts client totals (E2E-08); approval never applied (E2E-07). |
| Concurrency | 🟡 | TOCTOU on approvals, last-write-wins (E2E-13) — accepted class per ADR-0001 but surfaces in approvals. |
| Caching/Perf | 🟡 | Per-instance cache incoherence across Cloud Run instances (E2E-18); N-round-trip detail endpoints (E2E-19). Unmeasured. |
| Pipeline | 🟡 | PJP reload is non-atomic TRUNCATE+INSERT (E2E-22); name-based joins ~78% (E2E-23). |
| Mobile offline | 🟡 | Strong engine; offline relaunch still doesn't restore session (E2E-25). |
| Secrets | 🟢 | Clean — nothing sensitive tracked. |

---

## 3. System map (as-built)

```
Handheld (Expo RN)            Web (React/Vite, Vercel)
  SecureStore/localStorage JWT   localStorage JWT
        │  axios (20s; 45s submit/checkout)   │ axios (20s)
        └──────────────┬───────────────────────┘
                       ▼
        FastAPI on Cloud Run (asia-southeast1)
   slowapi rate-limit · CORS allowlist · JWT bearer
   dependencies.py: role + brand_group + SPV-team filters
                       ▼
        BigQuery  ── OLTP store (ADR-0001) ──
   sfa_web:  users, step_visit(+_item), approval_request,
             notification, dim_salesman(+brand_group), dim_outlet,
             fact_route_plan_pjp, spv_target, announcement …
   sfa_step: dim_salesman/dim_outlet/fact_visit (ANALYTICS roster,
             sadata/repsly-sourced) + sp_refresh_* procedures
   gt_schema: master_product, dist_stock_all_v, master_store_database…
```

The app's transactional reads/writes target **`sfa_web`** (config `bq_dataset=sfa_web`, with `fact_visit→step_visit` aliasing). The DDL in `database/schema/sfa_step_ddl.sql` describes the **`sfa_step`** analytics layer — a *different* set of same-named tables. See E2E-21.

---

## 4. Findings register

Severity: **Critical** (corrupts data / cross-user action in normal use) · **High** · **Medium** · **Low**. Status: all **Open** unless noted.

> **Remediation status — branch `fix/authz-consistency-audit13` (not merged).**
>
> **Batch 1 (authz + consistency):** **E2E-01, E2E-02** (visit ownership guard on checkout/submit/resubmit/final-qty/get + resubmit `REVISION_REQUIRED` guard + checkin forces `salesman_sk` from token & blocks future dates), **E2E-06** (`total_demand` recomputed from effective qty on final-qty adjust), **E2E-08** (resubmit recomputes `total_demand`+`effective_call` server-side), **E2E-10** (`ge=0` on qty/final_qty/stp/price/total_demand), **E2E-05** (`/route/salesmen` cache key carries full scope).
>
> **Batch 2 (approval enactment + full brand scoping):** **E2E-07** (Critical) — `approval_request` gains linkage/scope columns (**migration `003_approval_linkage.sql`**); new `POST /approvals` creates typed, entity-linked requests with server-derived `brand_group`; approve now **enacts** `proposed_value` via a guarded, idempotent dispatcher (`spv_target` → sets amount + `approval_status='approved'`; `outlet_tier` → sets `store_grade`), applied *before* the status flip so a bad value can't leave "approved-but-not-applied". **E2E-04** — list/approve/reject are brand-scoped (unscoped/legacy rows stay visible to all). **E2E-03 complete** — `/salesman/360`, `/evaluate/salesman` (group code) + `/store/360`, `/outlet/list`, `/outlet/search`, `/pjp/list` (brand *name* via new `brand_to_group`/`brand_name_filter`, which blocks only *known* other-BU rows so unclassified stores aren't hidden). All linkage access is defensive (works pre-migration).
>
> **Verified:** `py_compile` clean; app imports (4 approval routes, no dupes); **24 BQ-free unit tests pass** (`tests/test_authz_consistency.py`, `tests/test_approval_enactment.py`). Full `pytest` still needs live BQ creds.
>
> **Batch 3 (hardening sweep):** **E2E-13** (compare-and-set on generic + visit approve → 409 on a lost race, claim-before-enact so no double-apply), **E2E-14/17** (server-side session revocation — **migration `004_token_version.sql`**; `tv` JWT claim checked in `require_auth` cached 30s & fail-open; real `POST /auth/logout`; reset/password-change bump the version; web + mobile logout now call it), **E2E-11** (submit notifies only the owning SPV team), **E2E-28** (generic-approval `revise` action + web button), **E2E-15/31** (import filename guard + 8 MB upload cap), **E2E-16** (rate limiter keys on real client IP via X-Forwarded-For), **E2E-22** (PJP reload is now atomic `CREATE OR REPLACE TABLE … AS SELECT`), **E2E-26** (offline syncs skip the brand guard, per contract), **E2E-29** (`/outlet/assign` → 422 not 500), **E2E-25** (mobile caches the user and restores the session on an offline relaunch), **E2E-33** (mobile rounds per-item to match the server total), **E2E-27** (mobile retries idempotent GETs once on a network blip).
>
> **Verified (batch 3):** backend `py_compile` + import + 24 unit tests; mobile `tsc --noEmit` clean; web `tsc` + 24 vitest + production `build` all clean.
>
> **Run before E2E testing:** migrations **`003_approval_linkage.sql`** and **`004_token_version.sql`** (both additive/backward-compatible — the code fails open until they run).
>
> **Remaining E2E-07 UI wiring:** approve/reject/revise + enactment now work end-to-end from the Approvals page; the one remaining piece is having the Target/Tier **edit screens create linked requests** (`POST /approvals` with `entity_type`/`entity_id`) instead of writing directly, so those edits are *gated* by approval rather than only enactable when a request already exists.
>
> **Deferred by design (need a product/infra decision, not a code fix):** E2E-09 (GPS geofence policy — informational by design; future-dating now blocked), E2E-18 (per-instance cache coherence — needs shared cache/Memorystore), E2E-19/20 (detail-endpoint query fan-in / async push — perf, measure first), E2E-21 (dual `dim_*` dataset convergence — architecture migration), E2E-23 (name-join data quality — MDM), E2E-24 (BQ has no multi-row txn — mitigated by idempotency), E2E-30 (unmapped-SPV fallback — mitigated by brand scoping), E2E-32 (notification outbox — needs retry infra).

| ID | Sev | Module | Finding | Evidence | Verify |
|---|---|---|---|---|---|
| E2E-01 | High | Visit / API | No object-ownership check on `checkout`/`submit`/`resubmit`/`GET /visit/{id}`; `resubmit` has no status guard (can revert `COMPLETED`→`PENDING_SPV`). | `routers/visit.py` L251,320,576,752 | CONFIRMED |
| E2E-02 | High | Visit / API | `checkin` uses client `salesman_sk` (no equality to token) and client `visit_date` → visit attribution spoofing / backdating. | `routers/visit.py` L160-245 | CONFIRMED |
| E2E-03 | High | Reports / Master | Detail endpoints skip brand/territory scoping their siblings apply: `/store/360`, `/salesman/360`, `/evaluate/salesman/{sk}`, `/outlet/list`, `/outlet/search`, `/pjp/list`. | `outlet_web.py`, `salesman_web.py` L93, `evaluate_web.py` L63 | CONFIRMED |
| E2E-04 | Med | Approval | `approve`/`reject` have no territory/brand scoping (any `asm/dm/ho_admin` decides any request); SPV can't act despite documented flow. | `routers/approval.py` L160-173 | CONFIRMED |
| E2E-05 | Med | Route / Cache | Cache key omits tenant scope while SQL filters by it → cross-territory/brand leak on `/route/salesmen` (key uses role only). | `routers/route.py` L44-83 | CONFIRMED |
| E2E-06 | **Critical** | Visit / Reports | SPV `final_qty` adjustment updates `fact_visit_item.final_qty` only; `fact_visit.total_demand` is never recomputed → detail/PDF vs dashboards/360/reports diverge. | `routers/visit.py` L764-824 vs L1445-1451 | CONFIRMED |
| E2E-07 | **Critical** | Approval | Generic approval never enacts the change: `_update_approval` only flips status/comments; no code applies `proposed_value`; `approval_request` inserted only by the demo seed. | `routers/approval.py` L100-157; grep `approval_request` | CONFIRMED (repo); NEEDS-DYNAMIC-CHECK if enacted out-of-repo |
| E2E-08 | Med | Visit / X-platform | `resubmit` stores client `total_demand` verbatim (unlike `submit`, which recomputes) and never updates `effective_call` → revision can desync totals/EC from items. | `routers/visit.py` L576-641 | CONFIRMED |
| E2E-09 | Med | Visit / GPS | GPS never blocks; `offline_mode` skips checks; `visit_date`/timestamps client-set; duration clamps negatives to 0 (no geofence, no server time-sanity). | `routers/visit.py` L15,193,274 | CONFIRMED |
| E2E-10 | Med | Validation | No lower bound on `qty`/`final_qty`/`stp`/`price_for_store` (negatives accepted); `total_demand` client-set; no max. | `models/visit.py` L28-102 | CONFIRMED |
| E2E-11 | Med | Notification | `submit` notifies **all** `spv` users, not the owning team; deterministic `notification_id` on submit can duplicate on re-submit. | `routers/visit.py` L411-436 | CONFIRMED |
| E2E-12 | Low | Visit / Offline | Server dedup only when `schedule_id` present → ad-hoc offline visits rely solely on client `server_visit_id` persistence; narrow duplicate window remains. | `routers/visit.py` L166-181; `sync/engine.ts` L92-96 | CONFIRMED |
| E2E-13 | Med | Approval / Concurrency | Check-then-act (TOCTOU) + last-write-wins on approvals (BQ, no txn): two approvers can both "succeed"; comments can be lost. | `routers/approval.py` L100-140; `visit.py` L444-488 | CONFIRMED |
| E2E-14 | Med | Security / Session | JWT in `localStorage` (web + mobile-web); no revocation/blocklist; logout client-only; reset/deactivate don't invalidate live 24h tokens; no refresh/idle timeout. | `frontend/src/api/client.ts` L15,31; `services/auth.py` | CONFIRMED |
| E2E-15 | Med | Import / Security | Import builds SQL via hand-rolled `_str_lit` escaping (not parameterized) — injection-shaped, admin-gated; CSV fully buffered (no size cap). | `routers/import_export.py` L37-58 | CONFIRMED |
| E2E-16 | Low | Security / Rate-limit | slowapi keyed on `get_remote_address`; behind Cloud Run the peer is the front-end → per-client throttle ineffective or effectively global. | `main.py` L23; `auth.py` L29 | NEEDS-DYNAMIC-CHECK |
| E2E-17 | Low | Security | Reset token reusable until 24h expiry (no single-use/jti); `allow_credentials=True` unused by bearer API. | `routers/auth.py` L130-154; `main.py` L37-47 | CONFIRMED |
| E2E-18 | Med | Perf / Cache | In-process TTL cache is per Cloud Run instance; `cache.invalidate` affects only the local instance → other instances serve stale data up to TTL after writes. | `services/bq.py` L19-43 | CONFIRMED (design) |
| E2E-19 | Low | Perf | `store_360`/`salesman_360` fire many sequential BQ queries per request (each ~1–3s DML/query latency) → slow detail p95. | `outlet_web.py` L125-214; `salesman_web.py` L93-215 | NEEDS-DYNAMIC-CHECK |
| E2E-20 | Low | Perf / Notif | Per-approval synchronous `httpx` push (10s timeout) in request path adds latency during Expo outages. | `services/push.py` L33; `visit.py` L490-515 | CONFIRMED |
| E2E-21 | Med | Database | Duplicate `dim_salesman`/`dim_outlet`/visit tables across `sfa_web` (operational) and `sfa_step` (analytics) with divergent schemas (`brand_group` only in `sfa_web`); `dim_salesman` has duplicate `salesman_sk` rows (queries `QUALIFY`-dedupe). | `salesman_web.py` L17-20; `visit.py` L708-720; `sfa_step_ddl.sql` | CONFIRMED |
| E2E-22 | Med | Pipeline | `sp_reload_fact_route_plan_pjp` = `TRUNCATE` + `INSERT` (non-atomic). Failure after TRUNCATE leaves PJP empty → route plans vanish app-wide until next success. | `sfa_step_ddl.sql` L783-800 | CONFIRMED |
| E2E-23 | Low | Pipeline / Data | Name-based enrichment joins (`nama_salesman`=`salesman`) at ~78% → ~22% NULL `salesman_sk`/`outlet_sk` (missing region/SPV/route rows). | `sfa_step_ddl.sql` L476-477, 796-799 | CONFIRMED (documented) |
| E2E-24 | Low | Database | No FK/unique constraints (BQ); `submit` does `DELETE`+`INSERT` items non-atomically → orphan/partial `visit_item` window on failure. | `visit.py` L350-407 | CONFIRMED |
| E2E-25 | Med | Mobile / Offline | Offline relaunch doesn't restore session: `rehydrate` keeps the token but sets `isAuthenticated=false`/`user=null` on network error → field user lands on a login screen they can't submit offline. | `store/authStore.ts` L30-50 | CONFIRMED |
| E2E-26 | Low | Mobile / Sync | Comment says `offline_mode` "skips all server-side blocking checks," but the brand guard still runs on checkout/submit → a mixed-brand offline visit can get permanently stuck `failed`. | `visit.py` L279-286; `sync/engine.ts` | CONFIRMED |
| E2E-27 | Low | Mobile / API | No axios retry/backoff (relies on flush loop); `submit`/`checkout` 45s timeout vs 20s default — a slow BQ submit past 45s marks `failed` then re-submits (idempotent, but user sees an error). | `api/client.ts` L50-54; `api/visit.ts` L36-51 | CONFIRMED |
| E2E-28 | Low | Approval / Feature | "Revise/revision" state is queried and rendered but **no endpoint sets it** — the documented Revise action is unimplemented in the generic approval module. | `routers/approval.py` L46-49 | CONFIRMED |
| E2E-29 | Low | Outlet / Validation | `/outlet/assign` does `int(body.salesman_sk)` unguarded → `ValueError`→500 on non-numeric; no check the salesman shares the outlet's brand/territory. | `outlet_web.py` L101-120 | CONFIRMED |
| E2E-30 | Low | Master / Scoping | Unmapped SPV (`spv_salesman_filter` count=0) falls back to **no** salesman filter; if an endpoint relies on it alone (no brand filter), that SPV sees all salesmen. | `dependencies.py` L106-151 | NEEDS-DYNAMIC-CHECK |
| E2E-31 | Low | Import | `file.filename.lower()` assumes non-null filename → 500 on some multipart clients; Excel-only guard is extension-based. | `import_export.py` L118 | CONFIRMED |
| E2E-32 | Low | Notif/Consistency | In-app notif insert and push are best-effort (`except: pass`) — a visit can be approved with no notification and no error surfaced (silent notification loss). | `visit.py` L44-80 | CONFIRMED |
| E2E-33 | Low | X-platform | Demand rounding differs: backend `sum(round(qty*stp,2))` per item; mobile `sum(qty*stp)` unrounded → cent-level drift for non-integer `stp`. | `visit.py` L388; `db/visits.ts` L179 | CONFIRMED |

---

## 5. Critical Issues (detail)

### E2E-06 — SPV final-quantity adjustment does not propagate to `total_demand` *(Critical, data consistency)*
- **Module / Feature:** Visit → SPV "Final Qty" adjustment; every consumer of `fact_visit.total_demand`.
- **Steps to reproduce:** SE submits a visit (items → `total_demand` computed server-side). SPV calls `PUT /visit/{id}/final-qty` reducing a SKU's `final_qty`. Open the visit detail/PDF (uses `final_qty`) vs the Dashboard/Store 360/Salesman 360/Route-Evaluate/Achievement export (use `total_demand`).
- **Expected:** All surfaces reflect the SPV-approved final order.
- **Actual:** Detail/PDF show the adjusted total; all aggregates show the pre-adjustment total. `update_final_qty` writes `fact_visit_item.final_qty` + `fact_visit.updated_at` only (`visit.py:807-822`); `total_demand` is set once at submit (`visit.py:391-407`) and never recomputed. `_get_visit_detail` computes `final_demand` on the fly (`visit.py:1445-1451`) but doesn't persist it.
- **Root cause:** Two sources of truth for the visit total; the write path that changes the effective quantity doesn't update the denormalized aggregate the read paths use.
- **Files:** `routers/visit.py` (`update_final_qty`, `submit_visit`, `_get_visit_detail`).
- **Fix:** In `update_final_qty` (and `store-price`/`adjustment` where relevant), recompute and `UPDATE fact_visit.total_demand = SUM(final_qty*stp)` in the same call; OR make all readers use a single view that COALESCEs `final_qty`. Prefer the view to avoid another denormalized copy.
- **Complexity:** S–M. **Regression risk:** Medium (touches the number every KPI reads — snapshot key reports before/after).

### E2E-07 — Generic Approval decisions are recorded but never enacted *(Critical, business logic)*
- **Module / Feature:** Web **Approvals** page (target/master/announcement change requests).
- **Steps to reproduce:** From code: search the backend for writers of `approval_request` — only `scripts/seed/seed_demo_data.py` inserts. `_update_approval` (`approval.py:100`) updates `status/decided_by/comments_json` and pushes a notification; there is **no** code that writes `proposed_value` back to `spv_target`/`users`/`dim_*`.
- **Expected:** Approving a change request applies the proposed value to the target record; rejecting leaves it unchanged.
- **Actual:** Approve/Reject only mutates the request row. The queue is populated solely by seed data, so in a clean prod dataset the page is empty; if seeded, decisions have no downstream effect.
- **Root cause:** The enactment half of the workflow (create-request from user action + apply-on-approve) was never wired for the generic queue. (The *visit* approval path in `visit.py` **is** wired and works — this finding is only the generic `approval_request` queue.)
- **Files:** `routers/approval.py`; absence across `target_web.py`, `salesman_web.py`, `admin_web.py`.
- **Fix:** Decide the intended scope. If the generic queue is meant to gate target/master edits: (a) have those edit endpoints insert a `pending` `approval_request` instead of writing directly; (b) in `_update_approval`, on `approve`, dispatch by `type` to apply `proposed_value`. If it's not meant to gate anything, remove the page to avoid a false control. **Confirm first** whether an out-of-repo process (e.g., the separate Streamlit `salesman_pjp` app) enacts these.
- **Complexity:** M–L. **Regression risk:** Medium.

---

## 6. High Priority Issues (detail)

### E2E-01 — Missing object-level authorization across the visit lifecycle *(High, security/business logic)*
- **Feature:** `POST /visit/{id}/checkout`, `POST /visit/{id}/submit`, `PUT /visit/{id}/resubmit`, `GET /visit/{id}`.
- **Reproduce:** Authenticate as any user; call `checkout`/`submit`/`resubmit`/`GET` with a visit_id you don't own. The handlers fetch by ID and act; none compare `visit.salesman_sk` to the caller, and only the two visit-*approve/reject* paths call `_assert_spv_owns_visit`. `resubmit` additionally has **no status guard**, so `COMPLETED`→`PENDING_SPV` is reachable, re-opening a closed visit and re-writing its items.
- **Expected:** A user may only mutate/read visits within their scope; no backward state transition from `COMPLETED`.
- **Actual:** Any authenticated user with a valid visit_id can act. Practical exploitation is bounded only by IDs being random `VST-<16 hex>` (unguessable) — that's obscurity, not authorization.
- **Root cause:** Ownership/scoping enforced on *list* queries but not on *by-ID* mutations; `resubmit` lacks a state machine guard.
- **Fix:** Add a shared `_assert_can_act_on_visit(user, visit)` (salesman==self; SPV team via `_assert_spv_owns_visit`; dm by distributor; ho_admin all) and call it in every by-ID handler including `GET`. Add a `resubmit` guard: only `REVISION_REQUIRED` may resubmit.
- **Complexity:** M. **Regression risk:** Medium (tighten carefully so legitimate SPV/DM actions still pass).

### E2E-02 — Check-in trusts client `salesman_sk` and `visit_date` *(High, integrity/spoofing)*
- **Reproduce:** `POST /visit/checkin` with `salesman_sk` ≠ your own and/or a past/future `visit_date`. The row is created as-is (`visit.py:196-237`).
- **Impact:** Visit attribution to another salesman; backdated/forward-dated visits skewing route-compliance and KPIs. `salesman_sk`s are effectively known (surfaced by Route Planner/lists), so this is more reachable than the ID-gated writes above.
- **Fix:** For role `salesman`, force `salesman_sk = token.salesman_sk` (ignore body); validate `visit_date` within an allowed window (e.g., today ± small skew) unless an explicit backfill role. **Complexity:** S. **Regression:** Low–Med.

### E2E-03 — Detail endpoints omit the brand/territory scope their list siblings enforce *(High, cross-tenant read)*
- **Reproduce:** As an asm/spv scoped to brand SKT, call `/store/360/{outlet_id}`, `/salesman/360/{sk}`, or `/evaluate/salesman/{sk}` for a G2G entity, or `/outlet/list` / `/pjp/list` (no scoping) — data returns regardless of brand/territory. `/salesman/list` & `/salesman/search` *do* apply `brand_group_filter`; the `/360` detail does not.
- **Impact:** Cross-brand/cross-territory visibility of store performance, sell-in, salesman KPIs.
- **Fix:** Apply the same `brand_group_filter`/territory/SPV-team predicate on the profile lookup of each detail endpoint; 404 if out of scope. **Complexity:** M. **Regression:** Med (ensure admins/DM still see all).

### E2E-05 — Tenant-blind cache key leaks scoped lists *(High→Med, cross-tenant read)*
- **Reproduce:** SPV-A (territory X) and SPV-B (territory Y) both call `/route/salesmen` with no query params within 120s. Cache key is `route:salesmen:None:None:spv` (role only), but the SQL filters by `current_user.territory`. Second caller gets the first caller's territory list.
- **Fix:** Include every scope that affects the SQL (`brand_group`, `territory`/`distributor_code`, `user_id` for SPV-team) in the cache key — or don't cache scoped results. Audit all keys in §11 table. **Complexity:** S. **Regression:** Low.

---

## 7. Medium Priority Issues (summary)

E2E-04 (approval scoping), E2E-08 (resubmit trusts client total / no EC recompute), E2E-09 (no GPS/time enforcement), E2E-10 (no negative/max validation), E2E-11 (notify-all-SPVs), E2E-13 (approval TOCTOU / last-write-wins), E2E-14 (JWT storage + no revocation), E2E-15 (import string-built SQL + unbounded CSV), E2E-18 (per-instance cache incoherence), E2E-21 (duplicate cross-dataset dims), E2E-22 (non-atomic PJP reload), E2E-25 (offline relaunch doesn't restore session). Detail for each is in §4 and the section-specific sections below.

## 8. Low Priority Issues (summary)

E2E-12, E2E-16, E2E-17, E2E-19, E2E-20, E2E-23, E2E-24, E2E-26, E2E-27, E2E-28, E2E-29, E2E-30, E2E-31, E2E-32, E2E-33 — see §4.

---

## 9. Functional Bugs

- **Revert of completed visits** (E2E-01, `resubmit` no guard) — invalid state transition.
- **`final_qty` not reflected in totals** (E2E-06) — displayed vs stored mismatch.
- **Approve/Reject no-op** on generic queue (E2E-07).
- **Resubmit desync** — total_demand from client, `effective_call` never updated (E2E-08); a revision that zeroes all items still reads `effective_call='YES'`.
- **Notify-all-SPVs** on every submit (E2E-11) — every SPV is paged for every field visit company-wide.
- **Revise action missing** (E2E-28) — UI can display a `revision` status the backend can never set.
- **`/outlet/assign` 500** on non-numeric salesman_sk (E2E-29).

## 10. UI / UX Bugs & Gaps

- **Offline relaunch → login wall** (E2E-25): the highest-impact UX defect for field users; the token is preserved but the session isn't restored offline.
- **Silent notification loss** (E2E-32): approvals/submits swallow notif failures — correct for not blocking the write, but no retry/outbox, so users may never learn a decision happened.
- **Cross-platform display drift** (E2E-33): rupiah totals can differ by cents between handheld and web/PDF for non-integer STP.
- Web `localStorage` token means a new browser tab is silently authenticated; there's no "log out everywhere" (ties to E2E-14).
- (Not verified dynamically: skeletons/empty/error states, responsive layout, a11y — the components exist (`ui/Skeleton`, `ui/EmptyState`, `ErrorBoundary`) but were not exercised. See §20 testing checklist.)

## 11. API Issues

- **AuthZ gaps:** E2E-01, E2E-02, E2E-03, E2E-04 (above).
- **Cache correctness:** cache keys that must include scope — audited:

  | Endpoint | Key includes scope? | Risk |
  |---|---|---|
  | `/route/salesmen` | role only (missing brand/territory) | **Leak (E2E-05)** |
  | `/route/outlets` | no user scope | OK only because SQL has no user filter (broad-access by design) |
  | `/store/360`, `/salesman/360` | resource id + date | OK for caching, but endpoint itself unscoped (E2E-03) |
  | `/dashboard/*`, `/evaluate/team`, `/target/*`, `/report/*`, `/sku`, `/product`, `/salesman/list` | includes `brand_group`/`sk` | OK |
  | `/skipped-stores/summary` | `week` only | verify SPV-team scoping applied pre-cache |

- **Duplicate/legacy surface:** `create_user` (`/auth/users`) is marked legacy alongside `admin_web` user CRUD — two user-creation paths (dedupe).
- **Status codes:** validation failures that should be 422 surface as 500 in a few spots (`/outlet/assign` int cast E2E-29; import null filename E2E-31).
- **Idempotency:** check-in/submit are idempotent (good); resubmit/checkout are not guarded and overwrite (E2E-01/08).
- **Rate limiting** likely ineffective per-client behind the proxy (E2E-16).
- **Dead/unused:** the generic approval enact path (E2E-07) and the `revision` action (E2E-28) are referenced but unwired.

## 12. Database Issues

- **No FK/unique/PK enforcement** (BQ; `NOT ENFORCED` PKs) — every integrity rule is app-side (ADR-0001). Consequences observed: `dim_salesman` carries duplicate `salesman_sk` rows (queries defensively `QUALIFY ROW_NUMBER()`), and item writes are `DELETE`+`INSERT` with an orphan window (E2E-24).
- **Duplicate dimensions across datasets** (E2E-21): `sfa_web.dim_salesman` (has `brand_group`) vs `sfa_step.dim_salesman` (no `brand_group`); same for `dim_outlet` and `fact_visit`/`step_visit`. A code comment already warns `brand_group_filter` "would fail silently against" the `sfa_step` copy. High drift risk.
- **Soft-delete everywhere** (`is_deleted`) with app-side filtering — correct, but any query that forgets `AND is_deleted=FALSE` returns tombstones. Spot-checked queries are consistent.
- **Indexing/perf:** BQ uses partition+cluster, not indexes; hot operational tables (`step_visit`, `step_visit_item`) are small and DML-latency-bound, not scan-bound — watch DML p95 per ADR-0001.

## 13. BigQuery Pipeline / Airflow Issues

- **`sp_reload_fact_route_plan_pjp` is non-atomic** (E2E-22): `TRUNCATE`+`INSERT`. A mid-run failure empties PJP → the app's Route Planner/route plans/route-compliance go blank until the next good run. **Fix:** load into a staging table then `CREATE OR REPLACE`/partition-swap, or MERGE instead of truncate.
- **Ordering dependencies** are correct in comments (`dim_sadata_entities` before `fact_visit_sadata` before `dim_outlet_location`) but rely on DAG ordering, not guards — a mis-ordered/partial DAG produces NULL FKs.
- **Name-based joins ~78%** (E2E-23) — ~22% of PJP/salesman rows lose region/SPV/route linkage. Track match-rate as a data-quality metric.
- **Soft-delete via per-row correlated subqueries** in `sp_refresh_fact_visit_sadata` — expensive and brittle if a `salesman_sk` maps to >1 source code.
- **Watermark = `CURRENT_DATE()`** after each run — a run that partially fails but still updates the watermark could skip a day. Verify watermark is only advanced on full success.
- (`docker-airflow` DAG *definitions* were not in scope of this read — validate idempotency/retry/alerting there per audit-10 §7.6.)

## 14. Performance Issues

- **Per-instance cache incoherence** (E2E-18): the TTL cache lives in process memory; `cache.invalidate()` only clears the instance that served the write. With ≥2 Cloud Run instances, other instances serve stale dashboards/approvals/masters until TTL. Also means cache hit-rate drops as instances scale out. **Fix:** short TTLs are the current mitigation; for correctness-sensitive reads (approvals) consider a shared cache (Memorystore) or skip-cache-after-write via a version token.
- **N-round-trip detail endpoints** (E2E-19): `store_360` issues ~5 and `salesman_360` ~5 sequential BQ queries; at ~0.5–2s each these pages can run multi-second. **Fix:** combine into fewer queries / `WITH` CTEs, or parallelize.
- **Synchronous push in request path** (E2E-20).
- **Unbounded CSV import buffer** (E2E-15) — memory spike on large uploads.
- No measurements taken — commission the load/soak test called out in audit-10 §7.

## 15. Security Issues

- **Broken authorization** (E2E-01/02/03/04) — the headline security items.
- **Session/token** (E2E-14): `localStorage` JWT (XSS-exfiltratable; React auto-escaping is the main mitigation — audit any `dangerouslySetInnerHTML`), no revocation/blocklist, client-only logout, 24h fixed expiry, no refresh, no idle timeout, reset tokens reusable (E2E-17).
- **Injection surface** (E2E-15): import uses hand-escaped string literals; all other queries use parameterized `bq.p()` (good). No `eval`/template SQL with request params found elsewhere.
- **Rate limiting** (E2E-16) likely mis-keyed behind the proxy — brute-force/login throttle may not work as intended; verify with `X-Forwarded-For` handling.
- **CSRF:** N/A for a bearer-token API with no cookie auth (the `allow_credentials=True` is vestigial — E2E-17).
- **Secrets:** ✅ clean — `.env`, `bq-*.json`, `*-credentials.local.txt` all gitignored and untracked. (Rotate seeded `STEP@2026` per audit-10 F-06 — still open.)
- **PII/data exposure:** cross-brand detail reads (E2E-03) expose store/salesman performance across business units.

## 16. Data Consistency Issues

- E2E-06 (final_qty vs total_demand) — **the most important**.
- E2E-08 (resubmit client total / EC not recomputed).
- E2E-33 (rounding drift handheld vs web/PDF).
- E2E-24 (item DELETE+INSERT orphan window).
- E2E-21 (two dim datasets can drift).
- Effective-call semantics differ by path: `checkout` takes client `effective_call`; `submit` derives it as `YES if any qty>0`; `resubmit` leaves it untouched — three rules for one field.

## 17. Root Cause Analysis (themes)

1. **ADR-0001 makes the app the sole integrity engine, but enforcement is applied at *list/read* boundaries, not at *by-ID writes*.** Hence the authz gaps (E2E-01/02/03) and TOCTOU (E2E-13) — classic consequences of "no DB constraints + partial app checks."
2. **Denormalized aggregates without a single write authority.** `total_demand` is computed in three places and updated in one → E2E-06/08. A view-based single source of truth would eliminate the class.
3. **Two half-built approval systems.** The *visit* approval is a real, guarded state machine; the *generic* `approval_request` queue is UI + storage without enactment → E2E-07/28.
4. **Process-local caching under a horizontally-scaled runtime** → E2E-18.
5. **Federated, name-matched, dual-dataset warehouse** (deliberate per DDL header) leaks into operational correctness → E2E-21/23 and the `QUALIFY`-dedup defensiveness throughout.

## 18. Recommended Fixes (consolidated)

| # | Fix | Addresses | Complexity |
|---|---|---|---|
| 1 | Central `_assert_can_act_on_visit()` on every by-ID visit handler incl. GET; force `salesman_sk` from token on checkin; validate `visit_date`; guard `resubmit` to `REVISION_REQUIRED` only. | E2E-01/02 | M |
| 2 | Recompute `total_demand` on `final-qty` (and on resubmit); or a `vw_visit_effective` view COALESCEing `final_qty` that all readers use. | E2E-06/08 | M |
| 3 | Decide + wire (or remove) the generic approval enactment; add `revise`. | E2E-07/28 | M–L |
| 4 | Add brand/territory scope to `/store/360`, `/salesman/360`, `/evaluate/salesman`, `/outlet/list`, `/pjp/list`. | E2E-03 | M |
| 5 | Put full scope into every scoped cache key (or don't cache scoped data). | E2E-05 | S |
| 6 | Pydantic `Field(ge=0)` on qty/final_qty/stp/price; server-recompute totals; max bounds. | E2E-10 | S |
| 7 | Scope submit notifications to the owning SPV team; make notif an outbox with retry. | E2E-11/32 | M |
| 8 | Parameterize import writes; cap upload size / stream parse. | E2E-15 | M |
| 9 | Staging-swap or MERGE for PJP reload (atomic). | E2E-22 | S–M |
| 10 | Token hardening: shorten expiry + add refresh, add a `jti`/version claim checked against a per-user token-version column (cheap revocation), single-use reset tokens. | E2E-14/17 | M |
| 11 | Shared cache or post-write version-busting for correctness-sensitive reads. | E2E-18 | M |
| 12 | Restore offline session in `rehydrate` (cache the user profile locally; set authenticated on a preserved token). | E2E-25 | S |
| 13 | Converge the duplicate `dim_*` datasets (one operational source; analytics reads from it or a clearly-owned copy). | E2E-21 | L |

## 19. Suggested Refactoring · Technical Debt · Missing Features · Regression Risks

**Refactoring:** extract a `visit_authz.py` guard; a `visit_totals` module (one calc used by submit/resubmit/final-qty/detail/PDF); a shared `apply_scope(user)` predicate builder so no endpoint can forget scoping; a cache wrapper that *requires* a scope tuple.

**Technical debt:** dual `dim_*` datasets (E2E-21); name-based joins (E2E-23); three `effective_call` rules; two user-creation endpoints; `main.py` vestigial CORS credentials; `\C` docstring `SyntaxWarning`s (audit-10 F-10, still open).

**Missing features:** generic-approval enactment + revise (E2E-07/28); server-side session revocation / "logout everywhere"; GPS geofence enforcement (currently informational by design — confirm that's intended); CI gate (audit-10 F-07, still open); staging environment (F-11).

**Regression risks when fixing:** (a) tightening visit authz can break legitimate SPV/DM cross-user actions — cover with role tests first; (b) recomputing `total_demand` changes historical report numbers — snapshot before/after and communicate; (c) scoping the 360/list endpoints may hide data admins expect — verify the admin/DM "see-all" path; (d) cache-key changes drop hit-rate — watch latency; (e) atomic PJP reload changes the failure mode from "empty table" to "stale table" — intended, but announce.

## 20. Testing Checklist / Prioritized Roadmap

**Phase 0 — Confirm before changing (1–2 days, no risk):**
- [ ] Dynamically confirm E2E-07: does *anything* (incl. the separate Streamlit app) enact approved `approval_request`s? Is the queue used in prod at all?
- [ ] Confirm E2E-16: log `request.client.host` in prod — is it the Cloud Run front-end for all requests?
- [ ] Confirm E2E-18/19: instance count and detail-endpoint p95 in Cloud Run metrics.
- [ ] Confirm E2E-25 on a device: relaunch airplane-mode after login.

**Phase 1 — Authorization & integrity (highest risk-reduction, do first):**
- [ ] Fixes #1, #2, #4, #5, #6 (E2E-01/02/03/05/06/08/10). Add API tests: cross-user visit write → 403; final-qty then assert dashboard total == detail total; cross-brand 360 → 404.

**Phase 2 — Workflow correctness:**
- [ ] Fix #3 (approval enact/revise), #7 (scoped notifications + outbox). Tests: approve target-change → target row updated; submit notifies only owning SPV.

**Phase 3 — Platform hardening:**
- [ ] #8 (import), #9 (atomic PJP), #10 (tokens), #11 (cache), #12 (offline session), #13 (dataset convergence). Add the CI gate (F-07) and rotate F-06 passwords.

**Standing E2E test matrix (per platform, then cross-check identical):**
- [ ] Auth: login/expiry(24h)/invalid-token 401/logout; **new:** revoked/deactivated user still accepted? (should fail after fix #10).
- [ ] Visit happy path online + fully offline + checkout-fail-then-sync (no dup); ad-hoc (no schedule_id) offline dup check (E2E-12).
- [ ] Demand: add/edit/delete item, negative/zero/huge qty (should reject after #6), grand-total == sum, handheld total == web/PDF total (E2E-33).
- [ ] Approval state machine: every transition + illegal ones (COMPLETED→resubmit must fail after #1); two-approver race (E2E-13).
- [ ] Reports: totals/filter/sort/group; Excel/PDF export; **final-qty-adjusted visit reconciles across Store360/Salesman360/Route-Evaluate/Achievement** (E2E-06).
- [ ] RBAC × scope matrix: for each web role, each 360/list/approval endpoint, in-scope vs out-of-scope entity (E2E-03/04).
- [ ] Mobile: offline relaunch restores session; GPS/camera/gallery permission denial paths; crash-recovery `resetStuckSyncing`.

---
*Audit reflects repository state as read on 2026-07-23 (mobile at v1.4.2). Findings are static-analysis-derived; validate the NEEDS-DYNAMIC-CHECK items against runtime before scheduling their fixes. This document supplements — does not supersede — [10-production-readiness-audit](10-production-readiness-audit.md).*
