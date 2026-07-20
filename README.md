# Skintific Territory & Execution Platform (STEP)
**Plan. Execute. Monitor.**

Internal enterprise field-sales execution platform for territory planning, route execution, target governance, and sales performance monitoring. This repo holds the **production web app + backend API** (deployed) alongside the original design deliverables and a clickable prototype.

> **📌 Source of truth:** For how the system actually works today, read [`docs/current/`](docs/current/00-INDEX.md) (as-built). The numbered `docs/01…10` files are the original *design-phase* documents — kept for intent/history, but where they differ, **the as-built docs win**. The mobile app lives in a separate repo, [`sfa-mobile`](https://github.com/skt-project/sfa-mobile).

## Contents

### Documentation (`docs/`)

| Doc | Covers |
|---|---|
| [01-PRD.md](docs/01-PRD.md) | Product Requirement Document — vision, personas, scope, functional + non-functional requirements |
| [02-information-architecture.md](docs/02-information-architecture.md) | Sitemap, RBAC × navigation matrix, territory scoping model |
| [03-ux-flows.md](docs/03-ux-flows.md) | User flow diagrams — route planning, target approval, tier override, import/export, onboarding |
| [04-database-erd.md](docs/04-database-erd.md) | Entity diagram + database recommendation (Postgres OLTP + BigQuery analytics) |
| [05-api-recommendation.md](docs/05-api-recommendation.md) | REST API design, security, SFA integration endpoints |
| [06-design-system.md](docs/06-design-system.md) | Color/type/spacing tokens, component library, responsive breakpoints |
| [07-screen-specifications.md](docs/07-screen-specifications.md) | Dashboard spec, Route Planner spec, Recommendation Engine design |
| [08-approval-workflow.md](docs/08-approval-workflow.md) | Approval state machine, SLA model, configurable approval matrix |
| [09-sfa-integration-architecture.md](docs/09-sfa-integration-architecture.md) | Sync architecture, retry queue, status taxonomy, contract boundary with SFA-Handheldv2 |
| [10-roadmap-and-backlog.md](docs/10-roadmap-and-backlog.md) | Phase 1/2/3 roadmap + future enhancement backlog |

### Clickable Prototype (`prototype/`)

Static HTML/CSS/JS, no build step — open `prototype/index.html` directly or serve locally:

```
cd prototype
python -m http.server 8765
# open http://localhost:8765
```

Use the **role switcher** in the top bar to demo the same data from all 5 roles (SPV, Area Manager, Distributor Manager, Regional Sales, Head Office Admin) without logging in separately. This switcher is a prototype-only convenience — the production app derives role from SSO (see [05-api-recommendation.md](docs/05-api-recommendation.md#2-authentication--security)).

| Page | Module |
|---|---|
| `index.html` | Login |
| `dashboard.html` | Dashboard (role-aware) |
| `route-planner.html` | Route Planner + Recommendation Engine |
| `outlet-salesman.html` | Outlet & Salesman list |
| `outlet-360.html` | Outlet 360 |
| `salesman-360.html` | Salesman 360 |
| `target-management.html` | Target Management |
| `approvals.html` | Approvals Inbox |
| `reports.html` | Reports |
| `notifications.html` | Notification Center |
| `announcements.html` | Announcement Center |
| `import-export.html` | Import & Export Center |
| `administration.html` | Administration (Head Office Admin) |

### Implementation

| Path | Stack | Deploys to |
|---|---|---|
| [`backend/`](backend/) | FastAPI (Python 3.13), python-jose JWT, bcrypt, slowapi, google-cloud-bigquery | Google Cloud Run (`step-api`), manual via [`backend/deploy_to_cloudrun.ps1`](backend/deploy_to_cloudrun.ps1) |
| [`frontend/`](frontend/) | Vite 6 + React 18 + TypeScript + Tailwind | Vercel (`sfa-step.vercel.app`), auto on push to `main` |
| [`database/`](database/) | BigQuery DDL + migrations (`sfa_web` dataset is writable; source datasets are read-only) | — |

## Status

**In production**, current release **v1.4.2** (see [docs/current/07-changelog.md](docs/current/07-changelog.md)). Actively maintained. The design docs below reflect original Phase-1 intent; the deployed system has since evolved — always reconcile against [`docs/current/`](docs/current/00-INDEX.md).
