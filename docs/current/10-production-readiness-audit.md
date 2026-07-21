# 10 — Production Readiness Audit

**Date:** 2026-07-21 · **Auditor:** Enterprise delivery review
**Scope audited:** `sfa-step` (web + backend) and `sfa-mobile` (Expo/React Native)
**Not in this pass:** `docker-airflow`, Power BI / BI dashboards, external penetration test, formal load/soak test. (Called out in [§7 Backlog](#7-remediation-backlog).)

> STEP is **already in production** (web on Vercel, API on Cloud Run, mobile released at **v1.4.2**). This is therefore a *hardening* audit of a live system, not a pre-launch gate. Where this document and design-phase docs (`docs/01…10`) disagree, the as-built docs in this folder win (see [00-INDEX](00-INDEX.md)).

---

## 1. Verdict

**Conditionally production-ready.** The core is well-engineered — required-secret config, bcrypt + JWT with legacy-hash migration, rate limiting, restricted CORS, offline-first sync with a mutex and crash recovery, and a strong as-built doc set. This session removed the highest-risk defects (deploy-from-deprecated-repo, unguarded destructive prod scripts, an offline-sync duplicate window, and an offline auth lockout) and closed the frontend's zero-test gap for its security-critical logic.

Remaining conditions before "unconditionally production-grade" are operational, not architectural: rotate seeded default passwords, add a CI gate that runs the new tests, and make a deliberate decision on BigQuery-as-OLTP for the 10-year horizon ([§7](#7-remediation-backlog)).

## 2. Readiness scorecard

| Domain | Status | Rationale |
|---|---|---|
| Architecture | 🟢 Good | Clean FastAPI + Vite/React; documented multi-repo topology; one accepted deviation (BQ as OLTP) that needs a written ADR. |
| Security | 🟡 Watch | Secrets hygiene clean; auth solid. Open: seeded default passwords (`STEP@2026`), CORS `*` methods/headers, no automated dependency/secret scanning. |
| Testing | 🟡 Improving | Backend suite + mobile jest/detox existed; **web had 0 tests** → now covers RBAC/auth/client/hooks. No CI gate yet; coverage still thin on pages. |
| Data quality | 🟢 Good | Case-insensitive brand handling fixed (v1.4.2); idempotent sync; read-only source datasets. Referential integrity is app-enforced (BQ has no FKs). |
| Operability | 🟢 Good | Runbook, rollback, monitoring, E2E scripts all exist. Destructive scripts now guarded; deploy source fixed. |
| Performance | ⚪ Unmeasured | No load/soak test in evidence. Monitoring thresholds defined (p95 > 3s alert). BQ DML latency is the watch item. |
| Maintainability | 🟢 Good | Backend root decluttered; nav RBAC extracted & tested; docs authoritative. |

## 3. What was fixed this session

Delivered on branch **`hardening/prod-readiness-1`** in both repos (not yet merged to `main`/`master` — PRs pending review).

| Repo | Commit | Change |
|---|---|---|
| sfa-step | `65aec8b` | Deploy script no longer builds the prod image from the **deprecated** `skintific-step` tree; destructive scripts guarded; API version single-sourced; stray `netlify.toml` removed; stale README corrected. |
| sfa-step | `f282c58` | 24 one-off root scripts moved into a `backend/scripts/` package (run via `python -m scripts.<cat>.<name>`); `pytest.ini` pins the suite; script README added. |
| sfa-step | `a8d1d89` | Vitest + Testing Library; nav RBAC extracted to `nav.ts`; 24 tests across RBAC / auth store / API client / debounce. |
| sfa-mobile | `cc32540` | Offline-sync duplicate window closed; rehydrate no longer logs users out on offline launch; `EXPO_PUBLIC_API_BASE_URL` override. |

All changes verified: backend `py_compile` + destructive-guard exercised; web `24/24` tests + `build` clean; mobile `jest 13/13` + `tsc --noEmit` clean.

## 4. Findings register

Severity: **P0** ship-blocker · **P1** fix-soon · **P2** improvement. Status: ✅ fixed this session · ⏳ open · 🅰 accepted risk.

| ID | Sev | Status | Finding | Evidence |
|---|---|---|---|---|
| F-01 | P0 | ✅ `65aec8b` | Documented deploy command built the Cloud Run image from the deprecated repo path. | `backend/deploy_to_cloudrun.ps1` |
| F-02 | P0 | ✅ `65aec8b` | `cleanup_demo_data` / `reset_test_account` ran DELETE/UPDATE on prod BigQuery with no confirmation. | now gated by `backend/ops_guard.py` |
| F-03 | P1 | ✅ `cc32540` | Offline sync could duplicate a visit if checkout/submit failed after check-in. | `sfa-mobile/src/sync/engine.ts` |
| F-04 | P1 | ✅ `cc32540` | Offline app launch wiped the JWT on a network error → user locked out offline. | `sfa-mobile/src/store/authStore.ts` |
| F-05 | P1 | ✅ `a8d1d89` | Web app had zero automated tests over 19 live pages. | `frontend/src/**/*.test.ts` |
| F-06 | P1 | ⏳ open | Test accounts seeded with a known default password `STEP@2026`; must be rotated before/at go-live. | [06-operations-runbook](06-operations-runbook.md) §Test accounts |
| F-07 | P1 | ⏳ open | No CI: the new web/mobile tests and typechecks are not enforced on push. | no `.github/workflows` in either repo |
| F-08 | P2 | 🅰 accepted | CORS uses `allow_methods=["*"]`, `allow_headers=["*"]` with credentials. Safe behind the origin allowlist; tighten in staging. | `backend/main.py` |
| F-09 | P2 | ⏳ open | BigQuery is the transactional store (design doc recommended Postgres OLTP). Needs a written ADR + p95 watch. | [01-system-overview](01-system-overview.md) §Key decisions |
| F-10 | P2 | ⏳ open | Some migration scripts have `\C` escape-sequence `SyntaxWarning`s in docstrings (future-Python breakage). | `backend/scripts/migrations/*` |
| F-11 | P2 | ⏳ open | Mobile API host is build-time only; override now exists but there is no documented staging environment. | `sfa-mobile/src/api/client.ts` |

## 5. Web RBAC matrix (as-built)

Source of truth: [`frontend/src/components/layout/nav.ts`](../../frontend/src/components/layout/nav.ts) (extracted and unit-tested this session). Roles `salesman` and `demo` are **mobile-app users and see no web navigation**.

| Menu | spv | asm | dm | ho_admin |
|---|:--:|:--:|:--:|:--:|
| Dashboard | ✅ | ✅ | ✅ | ✅ |
| Master Data · Route Planner | ✅ | ✅ | ✅ | ✅ |
| Master Data · PJP / Salesman | — | ✅ | ✅ | ✅ |
| Master Data · Target / Outlet | ✅ | ✅ | ✅ | ✅ |
| Reports · Route Evaluate / Visit / Store360 / Salesman360 | ✅ | ✅ | ✅ | ✅ |
| Reports · Store Opportunity | — | ✅ | ✅ | ✅ |
| Approvals | ✅ | ✅ | ✅ | ✅ |
| Import & Export | — | — | ✅ | ✅ |
| Announcements | ✅ | ✅ | ✅ | ✅ |
| Administration | — | — | — | ✅ |

> **Note:** menu visibility is a UX affordance. Server-side authorization (role/BU checks in `backend/dependencies.py` and routers) is the enforcement boundary — this matrix must be validated against it, not treated as the control itself.

## 6. Go-live & hypercare

The operational artifacts already exist and were **not** regenerated — use them directly:
- Deploy, rollback, monitoring, known issues → [06-operations-runbook](06-operations-runbook.md)
- Manual end-to-end validation (BU-1 SKT + BU-2 G2G) → [08-e2e-test-scripts](08-e2e-test-scripts.md)
- On-prem hosting migration → [09-windows-server-deployment](09-windows-server-deployment.md)

Pre-go-live checklist deltas surfaced by this audit: rotate F-06 passwords; run the E2E scripts post-deploy; confirm the deploy script fix (F-01) is merged before the next backend release.

## 7. Remediation backlog

Prioritized, for the team to schedule:

1. **Rotate seeded default passwords** (F-06) — go-live blocker; ops/data-team task in BigQuery.
2. **Add CI** (F-07) — GitHub Actions: web `npm run build` + `npm test`; mobile `tsc --noEmit` + `jest`; backend `pytest`. Gate merges to `main`.
3. **Write the BigQuery-as-OLTP ADR** (F-09) — record the decision, mitigations, and the p95-latency trigger to revisit.
4. **Tighten CORS in staging** (F-08) — explicit methods/headers, verified against web + mobile.
5. **Expand test coverage** — page-level tests for the approval flow and Visit Detail (the page that previously crashed with React #310).
6. **Out-of-scope audits to schedule** — `docker-airflow` pipeline reliability/idempotency, Power BI RLS + refresh, a formal load/soak test, and a dependency/secret-scan pass.

---
*This audit reflects the repository state as of the commits in §3. Re-run the verification commands after merging to confirm parity on `main`/`master`.*
