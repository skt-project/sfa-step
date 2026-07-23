# STEP SFA — Current Documentation (As-Built)

**Last updated:** 2026-07-15 · covers Web `sfa-step@17582fb` · Mobile `v1.4.2` (versionCode 11)

This folder documents the system **as actually built and deployed**. The numbered docs in the parent `docs/` folder (01-PRD … 10-roadmap) are the original *design-phase* documents — useful for intent and history, but where they conflict with these files, **these files win**.

| Doc | What it covers |
|---|---|
| [01-system-overview.md](01-system-overview.md) | Architecture, repositories, deploy targets, tech stacks |
| [02-business-rules.md](02-business-rules.md) | Roles & RBAC, Business Units, visit lifecycle, approval flow, One-Line-Management, offline rules |
| [03-api-reference.md](03-api-reference.md) | Endpoint inventory with auth/role requirements |
| [04-database-guide.md](04-database-guide.md) | BigQuery datasets, tables, migrations, data gotchas |
| [05-mobile-guide.md](05-mobile-guide.md) | Mobile screens, offline sync engine, build & release |
| [06-operations-runbook.md](06-operations-runbook.md) | Deployment, test accounts, monitoring, rollback, known issues |
| [07-changelog.md](07-changelog.md) | Release history v1.4.0 → v1.4.2 with root-cause notes |
| [08-e2e-test-scripts.md](08-e2e-test-scripts.md) | Manual E2E scripts — BU 1 (SKT) and BU 2 (G2G) flows |
| [09-windows-server-deployment.md](09-windows-server-deployment.md) | Migrating STEP Web hosting to an on-prem Windows Server |
| [10-production-readiness-audit.md](10-production-readiness-audit.md) | Readiness verdict, findings register, web RBAC matrix, remediation backlog (2026-07-21) |
| [adr-0001-bigquery-as-transactional-store.md](adr-0001-bigquery-as-transactional-store.md) | ADR: why BigQuery is the OLTP store, mitigations, and revisit triggers |
| [11-e2e-test-cases.md](11-e2e-test-cases.md) | Formal E2E test-case suite (objective/precondition/steps/validation/pass-fail/priority) across the full business process |
| [12-step-design-system.md](12-step-design-system.md) | STEP design system — brand hierarchy, logo, color/type/spacing/radius/shadow tokens, component classes, animation & a11y rules |

**Golden rules for anyone touching this system**
1. `D:\GitHub\sfa-step` (`github.com/skt-project/sfa-step`, branch `main`) is the **only** production web/backend repo. `skintific-step` is a deprecated working copy.
2. BigQuery source datasets are **read-only**; only `sfa_web` is writable.
3. Brand values in `gt_schema.master_product` are **UPPERCASE** — every brand comparison must be case-insensitive (see 04-database-guide).
4. Business logic (approval flow, visit flow, RBAC) never changes without a product decision.
