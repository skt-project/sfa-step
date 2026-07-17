# 01 — System Overview (As-Built)

## What STEP SFA is
A field-sales execution platform for Skintific's General Trade channel: salesmen (SE) visit stores on a planned route, record **orders** (sell-out demand) on an Android app — online or fully offline — and the order flows through an approval chain (SPV → Distributor Manager) on a web app, ending in a printable offering-letter PDF for the distributor.

## Architecture

```
┌─────────────────────────┐        ┌──────────────────────────┐
│  SFA Mobile (Android)   │        │  STEP Web (browser)      │
│  Expo/React Native      │        │  Vite + React 18         │
│  offline-first, SQLite  │        │  Vercel: sfa-step        │
└───────────┬─────────────┘        └───────────┬──────────────┘
            │        HTTPS + JWT (Bearer)      │
            └───────────────┬──────────────────┘
                            ▼
             ┌──────────────────────────────┐
             │  STEP API — FastAPI          │
             │  Google Cloud Run            │
             │  step-api-…run.app/api/v1    │
             └──────────────┬───────────────┘
                            ▼
             ┌──────────────────────────────┐
             │  Google BigQuery             │
             │  WRITE: sfa_web dataset      │
             │  READ : gt_schema, others    │
             └──────────────────────────────┘
```

## Repositories (authoritative list)

| Repo | Path | Remote / branch | Deploys to |
|---|---|---|---|
| **Web + Backend** | `D:\GitHub\sfa-step` | `github.com/skt-project/sfa-step` · `main` | Frontend → Vercel (`sfa-step.vercel.app`, auto on push); Backend → Cloud Run (manual, `backend/deploy_to_cloudrun.ps1`) |
| **Mobile** | `D:\GitHub\sfa-mobile` | `github.com/skt-project/sfa-mobile` · `master` | Release APK built locally (`android/gradlew assembleRelease`) or EAS |
| ~~Legacy~~ | `D:\GitHub\skintific-step` | `streamlit_app.git` · `step-prototype` | **Deprecated** — do not ship fixes here |

Other sibling repos (`SFA-Handheldv2`, `SFA-Portal`, `sfa-handheld`) are separate legacy systems, unrelated to STEP.

## Tech stacks

**Mobile** — Expo 57, React Native 0.86, TypeScript, TanStack Query v5, Zustand, expo-sqlite (WAL), expo-secure-store (JWT), expo-location/camera/image-picker, expo-notifications (push), NativeWind-adjacent custom token system (`src/theme.ts`). App id `com.skintific.sfa`.

**Web** — Vite 6, React 18, TypeScript, TanStack Query v5, React Router 6, Recharts, Tailwind v3 + custom component classes, jwt-decode. 23 lazy route chunks; ESLint with `react-hooks/rules-of-hooks=error` (mandatory — see changelog for why).

**Backend** — FastAPI (Python 3.13), python-jose JWT (HS256, 24 h), bcrypt (with transparent legacy-SHA256 upgrade), slowapi rate limiting, fpdf2 (PDF), google-cloud-bigquery with an in-process TTL cache (`services/bq.py`). 27 routers under `/api/v1`; health at `/health`.

## Environments & config

| Setting | Where | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | Vercel env / `.env.production` | Defaults to the Cloud Run URL if unset |
| `JWT_SECRET` | Cloud Run env | **Required** — no default |
| `CORS_ORIGINS` | Cloud Run env | Must include `https://sfa-step.vercel.app` |
| `BQ_SA_KEY_PATH` / `BQ_SA_KEY_JSON` | local dev / cloud | Omit on Cloud Run → workload identity |
| Mobile API URL | `src/api/client.ts` `BASE_URL` | Hardcoded Cloud Run URL — changing the API host requires a new APK |

## Key design decisions (and their consequences)
1. **BigQuery as the transactional store.** Writes are 1–3 s DML jobs; there are no row transactions. Mitigations: idempotent endpoints, batched DML where hot, in-process caching. The original design doc (04-database-erd) recommended Postgres OLTP — revisit if p95 latency degrades.
2. **Offline-first mobile.** Every visit survives with zero connectivity; the server accepts replayed timestamps (`captured_at`) and is idempotent (checkin dedupes by `schedule_id`; submit short-circuits when already `SUBMITTED`).
3. **JWT carries authorization context** (role, business unit, salesman_sk, distributor). Changing a user's role/BU in the DB requires the user to **re-login**.
4. **GPS is informational, never blocking** (200 m warn threshold on check-in distance).
