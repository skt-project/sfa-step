# backend/scripts

One-off operational, seed, migration, and diagnostic scripts. These are **not** part
of the running API (`main.py` never imports them) — they are run by hand by an operator.

## How to run

Always run from the **`backend/`** directory as a module, so the app packages
(`config`, `services`, …) and `.env` resolve exactly as they do for the API:

```bash
cd backend
python -m scripts.<category>.<name>
# e.g.
python -m scripts.seed.create_test_users
python -m scripts.migrations.migrate_brand_group
```

> Running a file directly (`python scripts/seed/create_test_users.py`) will **fail** —
> Python would put `scripts/seed/` on the path instead of `backend/`, breaking
> `from config import settings`. Use `-m` from `backend/`.

## Categories

| Folder | Contents |
|---|---|
| `migrations/` | Schema/data migrations (`migrate_*`, `add_brand_group_col`). Idempotent where possible; check the docstring for run-order notes. |
| `seed/`       | Seed/create data & accounts (`seed_*`, `create_*_users`, `create_demo_user`, `inject_skt_salesmen`). |
| `ops/`        | Production data operations (`sync_sfa_web`, `assign_spv_territory`, `update_user_roles`) and **destructive** tools (`cleanup_demo_data`, `reset_test_account`). |
| `dev/`        | Local diagnostics — safe to run (`debug_login`, `check_skt_salesmen`, `validate_bq_schema`, `probe_api`, `probe_visit_api`). |

## ⚠ Destructive scripts

`ops/cleanup_demo_data` and `ops/reset_test_account` mutate **production** BigQuery
and refuse to run without explicit confirmation (see `backend/ops_guard.py`):

```bash
# PowerShell
$env:STEP_ALLOW_DESTRUCTIVE=1; python -m scripts.ops.cleanup_demo_data
# bash
STEP_ALLOW_DESTRUCTIVE=1 python -m scripts.ops.cleanup_demo_data
# or
python -m scripts.ops.cleanup_demo_data --yes
```

New destructive scripts should call `confirm_destructive(action, target)` from
`ops_guard` before touching data.
