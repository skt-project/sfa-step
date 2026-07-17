# 03 — API Reference (As-Built)

Base URL: `https://step-api-141828905128.asia-southeast1.run.app/api/v1`
Auth: `Authorization: Bearer <JWT>` on everything except `/auth/login`, `/auth/reset-password`, `/health`.
Interactive docs: `GET /docs` (Swagger). Rate limit: 200/min global, 20/min on login.

## Auth
| Method & path | Roles | Notes |
|---|---|---|
| POST `/auth/login` | public | `{username,password}` → `{access_token,user}`; bcrypt w/ legacy-hash upgrade |
| GET `/auth/me` | any | Current JWT context |
| POST `/auth/reset-password` | token | Purpose-scoped reset token |
| POST `/auth/users` | ho_admin | Legacy create-user |

## Visit lifecycle (mobile writes)
| Method & path | Roles | Notes |
|---|---|---|
| POST `/visit/checkin` | any auth | Idempotent by `schedule_id`; records GPS distance (never blocks); `captured_at` honored |
| POST `/visit/{id}/checkout` | any auth | Times/coords/notes; **items NOT stored here**; BU brand guard (case-insensitive) |
| POST `/visit/{id}/submit` | any auth | Idempotent; wipes partial items then inserts; recomputes `total_demand`, EC; → `PENDING_SPV`; notifies SPVs |
| PUT `/visit/{id}/resubmit` | any auth | After `REVISION_REQUIRED`; items replaced; → `PENDING_SPV` |

## Visit approval & admin (web)
| Method & path | Roles | Notes |
|---|---|---|
| GET `/visit` | role-scoped | salesman/`se`→self; **spv→own salesmen (One-Line, fallback BU)**; dm→own distributor + `SPV_APPROVED/COMPLETED`; filters: date, status, store_name, pagination |
| GET `/visit/{id}` | any auth | Full detail incl. items (+`sku_size`=pack_size, warehouse stock join) |
| PUT `/visit/{id}/approve` | spv → dm/ho_admin | State machine; **SPV cross-line blocked (403)** |
| PUT `/visit/{id}/reject` | same | → `REVISION_REQUIRED` + notes; SPV cross-line blocked |
| PUT `/visit/{id}/final-qty` | spv (pre-approve), dm/ho (post-SPV) | Batched CASE update |
| PUT `/visit/{id}/store-price` | dm, ho_admin | Batched CASE update |
| PUT `/visit/{id}/adjustment` | dm, ho_admin | Invoice ± adjustment (needs migration 005) |
| GET `/visit/{id}/pdf` | spv/asm/dm/ho_admin | Offering letter; filename `{Store}_{ddMMyyyy}.pdf`; download logged |

## Catalog & schedule (mobile reads)
| Method & path | Notes |
|---|---|
| GET `/product` | BU-filtered (case-insensitive), **only priced SKUs**, returns `pack_size`; 5-min cache per BU |
| GET `/schedule/download?salesman_sk&week` | Weekly PJP for offline cache |
| GET `/schedule/today?salesman_sk` | Today's stores |
| GET `/dashboard/kpi?salesman_sk&visit_date` | SE home KPIs |
| GET `/dashboard/team?visit_date` | SPV team KPIs |

## Skipped stores
POST `/skipped-stores` (SE batch) · GET `/skipped-stores` · PUT `/skipped-stores/{id}/return` · PUT `/skipped-stores/{id}/execute` · GET `/skipped-stores/summary`

## Web modules (selected)
| Prefix | Purpose |
|---|---|
| GET `/dashboard/web` | Web dashboard: comply (spv_target), KPIs, leaderboard — live BQ, 2-min cache |
| `/approvals` | Non-visit approvals (target_adjust, tier_override, reopen) |
| `/target …` (target_web) | SPV target entry; BU brand validation (case-insensitive) |
| `/route-planner` | Weekly route assignment CRUD |
| `/evaluate` | Route compliance/EC evaluation |
| `/salesman/list,search,360/{sk}` | Salesman master + 360 (static paths registered before `/{sk}`) |
| `/outlet/search`, `/store/360/{id}` | Store master + 360 |
| `/notifications` | List/read/mark-all/register-push-token (keyed by `user_id`) |
| `/admin/users` | ho_admin user CRUD |
| `/reports`, `/reports/export.csv` | Report tables + CSV export |
| `/import-export` | Bulk jobs |
| `/announcements` | Announcement feed (typed) |
| GET `/health` | `{"status":"ok"}` — no auth, use for monitors |

## Error semantics
- 401 → clients auto-logout (web redirects to /login; mobile clears token via unauthorized handler)
- 403 → role/BU/One-Line violation; body `detail` is user-displayable (Indonesian)
- Timeouts: clients use 20 s (45 s for checkout/submit); mobile falls back to offline queue on network failure
- Notification/audit writes are fire-and-forget — they never fail the main operation

## Contract stability rules
- Changes must be **additive** (new optional fields) — old APKs stay in the field.
- `items` is always an array (never null). `adjustment_*` are null until migration 005 runs — clients treat null as 0/absent.
