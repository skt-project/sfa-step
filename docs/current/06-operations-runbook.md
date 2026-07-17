# 06 — Operations Runbook

## Standard deployment

**Order matters: backend first, then clients.**

1. **Backend → Cloud Run** (manual):
   ```powershell
   cd backend; .\deploy_to_cloudrun.ps1
   ```
   Env requirements: `JWT_SECRET`, `CORS_ORIGINS` (must include `https://sfa-step.vercel.app`), BQ credentials via workload identity. Recommended: min-instances = 1.
2. **Web → Vercel**: automatic on push to `main`. Verify the deployment turned green in the Vercel dashboard, then hard-refresh and open a Visit Detail (regression canary for the #310 class).
3. **Mobile → APK**: build per [05-mobile-guide](05-mobile-guide.md), distribute `app-release.apk`, users re-login.
4. **Migrations**: run any pending `database/migrations/*.sql` via `bq query` (currently: 005 if not yet applied).

## Post-deploy smoke test (5 min)
1. `GET /health` → `{"status":"ok"}`.
2. Mobile login `test_se` → product list **non-empty**, SKT brands only, prices + pack sizes visible.
3. One full flow: checkin → order → checkout → submit → **no 403** → 🟢 Tersinkron.
4. Web SPV/admin sees the visit under Menunggu SPV; approve; DM sets price; PDF downloads with correct filename.

## Test accounts (UAT)

| Username | Password | Role / BU | Notes |
|---|---|---|---|
| `test_se` | `STEP@2026` | salesman(se) / SKT | linked salesman_sk |
| `demo` | `STEP@2026` | salesman(se) / SKT | demo account |
| `test_spv` | `STEP@2026` | spv / SKT* | unmapped in dim_salesman → BU-wide fallback scope |
| `test_dist` | `STEP@2026` | dm* | *pending role normalization from `distributor_admin` |
| `admin` | `Step@2026!` | ho_admin | sees everything; final approvals |

⚠ Rotate these before real go-live; they are seeded with a known default password (`backend/create_test_users.py`).

## Monitoring
- **Cloud Run**: 5xx rate, p95 latency (alert > 3 s), instance count; Cloud Logging for stack traces.
- **Uptime**: external monitor on `https://sfa-step.vercel.app` + `/health` every 5 min.
- **BigQuery**: slot usage / query errors on `sfa_web`; watch DML latency growth on `step_visit_item`.
- **During rollouts watch**: submit-visit duration (known issue R2), `/visit/{id}` error rate, notification insert failures (silent-except paths).

## Rollback
- **Web**: Vercel → Deployments → promote previous. Or `git revert` + push.
- **Backend**: Cloud Run → Revisions → route 100 % traffic to previous revision (instant).
- **Mobile**: reinstall previous APK (`adb install -r -d` for downgrade); keep the last 2 APKs archived.
- **DB**: migrations are additive (`IF NOT EXISTS`) — no rollback needed; BigQuery time-travel (7 days) covers data accidents.
- Record "last known good" (git tag + Cloud Run revision) with every release.

## Known issues register (live)

| ID | Issue | Sev | Workaround / plan |
|---|---|---|---|
| R1 | ASM shown Approve button but backend has no ASM transition → 403 | Med | Keep ASM out of approval UAT; product decision pending |
| R2 | Submit inserts order items one-DML-per-SKU → slow/timeout risk on very large baskets | Med | Idempotent retry + offline fallback absorb it; batch-INSERT planned |
| R3 | Migration 005 must be run once for invoice adjustment to persist | Low | One `bq query` command; graceful degrade until then |
| R6 | Legacy repo `skintific-step` can drift | Med | Process rule: only `sfa-step` ships |
| R7 | Mobile Profil screen version label hardcoded | Cosmetic | Check version via Android Settings; fix = read from expo-application |
| R8 | Release APK signed with debug keystore | Med (deploy) | Internal sideload OK; generate real keystore before Play Store |
| R9 | `users.role` legacy values (`se` ok, `distributor_admin` broken) | Med | Normalize `distributor_admin` → `dm`; users re-login |
| R10 | SPV↔Distributor-Admin mapping has no data model | Backlog | Needs product definition before implementation |

## Incident quick-diagnosis (from real cases)

| Symptom | First checks |
|---|---|
| "Mobile data not on web" | 1) Is the visit `CHECKED_IN` with 0 items in BQ? → still on the device; pull-to-refresh. 2) Viewer's BU vs visit `brand_group` (NULL is invisible to BU-scoped SPVs). 3) DM only sees `SPV_APPROVED+`. 4) Default tab filters `PENDING_SPV` only. |
| Empty product list on mobile | Salesman BU set but backend pre-case-fix, or genuinely no priced SKUs for that BU. Check `/product` with the user's token. |
| 403 on checkout/submit | Brand outside user's BU (check item brand casing vs BRAND_GROUPS), or SPV acting cross-line (One-Line 403). |
| Web page crashes to error screen | Check for hooks-after-early-return regressions — `npx eslint src` (rules-of-hooks) catches them; React #310 in prod console. |
| User's role/BU change "didn't work" | JWT is stale — user must log out/in. |

## Where everything lives
- This runbook + as-built docs: `docs/current/` (this repo)
- Historic session reports & audits: `D:\Claude\STEP-Sprint-2026-07-13\`
- Design-phase docs: `docs/01…10`
- E2E scripts: [08-e2e-test-scripts.md](08-e2e-test-scripts.md) · Windows Server hosting: [09-windows-server-deployment.md](09-windows-server-deployment.md)
