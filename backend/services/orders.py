"""
Multi-source order reader.

Two INDEPENDENT sources, each queried separately so a failure in one cannot take
down the other (spec §14):

  SFA         — sfa_web.step_visit + step_visit_item, written by STEP Handheld.
                UNCHANGED by this module: read-only here, and routers/visit.py
                keeps serving it exactly as before.
  SPREADSHEET — sfa_web.ext_visit + ext_visit_item, the already-synced mirror of
                the external workbook's `visit` / `visit_item` tabs.

The spreadsheet source reads BigQuery, NOT Google Sheets. Sheets is touched only
by the sync job, so a Google outage cannot affect anyone browsing orders — it can
only make the mirror stale.

Distributor scoping applies to BOTH sources and FAILS CLOSED: a dm without a
distributor_code sees nothing, never everything.
"""
from __future__ import annotations

import logging
from typing import Any

from config import settings
from dependencies import brand_group_filter, spv_salesman_filter
from models.auth import UserContext
from models.order import OrderItemRow, OrderRow

logger = logging.getLogger(__name__)

SOURCE_SFA = "SFA"
SOURCE_SHEET = "SPREADSHEET"
SOURCE_LABELS = {SOURCE_SFA: "STEP Handheld / SFA", SOURCE_SHEET: "Spreadsheet"}

COMPLETED_STATUSES = {"COMPLETED"}
REJECTED_STATUSES = {"REJECTED"}


class SourceUnavailable(RuntimeError):
    """A single source could not be read. Never aborts the other source."""


def _tbl(name: str) -> str:
    return f"`{settings.bq_project}.{settings.bq_dataset}.{name}`"


def _iso(v: Any) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def _like(value: str) -> str:
    return f"%{value.lower()}%"


def _product_summary(count: int, first_name: str | None) -> str | None:
    if count <= 0:
        return None
    if count == 1:
        return first_name
    return f"{count} produk"


def distributor_predicate(user: UserContext, column: str, param: str) -> tuple[str, list]:
    """Distributor scoping shared by both sources.

    ho_admin / spv / asm → unrestricted here (require_role governs who may call).
    dm                   → pinned to their own distributor_code(s) from the token.
                           A dm normally represents exactly one distributor, but the
                           claim accepts a comma-separated list (e.g. a test/roaming
                           account covering more than one) — a single code is just a
                           one-element list, so this is fully backward compatible.
    dm with no code      → NOTHING (fail closed). An unscoped distributor account
                           must never silently become an all-distributor account.
    """
    from services.bq import BQClient

    if user.role != "dm":
        return "", []
    codes = [c.strip() for c in (user.distributor_code or "").split(",") if c.strip()]
    if not codes:
        return "AND 1=0", []
    placeholders = ", ".join(f"@{param}_{i}" for i in range(len(codes)))
    params = [BQClient.p(f"{param}_{i}", "STRING", c) for i, c in enumerate(codes)]
    return f"AND {column} IN ({placeholders})", params


def role_scope(user: UserContext, visit_alias: str, salesman_col: str) -> tuple[list[str], list]:
    """Non-distributor scoping, reusing the SAME helpers routers/visit.py uses so
    the unified list can never be laxer than the list it supplements.

    se/salesman → own visits only.
    spv         → own team (dim_salesman.spv_name), plus brand group.
    asm         → brand group.
    ho_admin/dm → handled elsewhere (dm by distributor_predicate).
    """
    from services.bq import BQClient

    clauses: list[str] = []
    params: list = []

    bg_clause, bg_params = brand_group_filter(user, table_alias=visit_alias)
    if bg_clause:
        clauses.append(bg_clause)
        params.extend(bg_params)

    if user.role in ("salesman", "se"):
        clauses.append(f"AND {salesman_col} = @self_sk")
        params.append(BQClient.p("self_sk", "STRING", user.salesman_sk or user.user_id))
    elif user.role == "spv":
        spv_clause, spv_params = spv_salesman_filter(user, salesman_col=salesman_col)
        if spv_clause:
            clauses.append(spv_clause)
            params.extend(spv_params)

    return clauses, params


# ---------------------------------------------------------------------------
# SFA
# ---------------------------------------------------------------------------

def fetch_sfa_orders(bq, user: UserContext, f: dict, limit: int) -> list[OrderRow]:
    """SFA orders, one row per visit. Items are aggregated onto the header so a
    multi-item order can never fan out into several table rows (spec §10)."""
    item_tbl = _tbl("step_visit_item")
    conditions: list[str] = ["v.is_deleted = FALSE"]
    params: list = []

    scope, scope_params = distributor_predicate(user, "o.distributor_code", "sfa_dist")
    if scope:
        conditions.append(scope)
        params.extend(scope_params)

    role_clauses, role_params = role_scope(user, "v", "v.salesman_sk")
    conditions.extend(role_clauses)
    params.extend(role_params)

    # Preserve the existing rule: a dm only ever saw orders that reached them.
    if user.role == "dm":
        conditions.append("AND v.approval_status IN ('SPV_APPROVED','COMPLETED')")

    if f.get("from_date"):
        conditions.append("AND v.visit_date >= @from_date")
        params.append(bq.p("from_date", "DATE", f["from_date"]))
    if f.get("to_date"):
        conditions.append("AND v.visit_date <= @to_date")
        params.append(bq.p("to_date", "DATE", f["to_date"]))
    if f.get("status"):
        conditions.append("AND v.approval_status = @status")
        params.append(bq.p("status", "STRING", f["status"]))
    if f.get("store"):
        conditions.append(
            "AND (LOWER(o.store_name) LIKE @store OR LOWER(o.source_outlet_code) LIKE @store)"
        )
        params.append(bq.p("store", "STRING", _like(f["store"])))
    if f.get("order_number"):
        conditions.append("AND LOWER(v.visit_id) LIKE @ordno")
        params.append(bq.p("ordno", "STRING", _like(f["order_number"])))
    if f.get("sku"):
        conditions.append(
            "AND EXISTS (SELECT 1 FROM " + item_tbl + " i WHERE i.visit_id = v.visit_id "
            "AND (LOWER(i.sku_id) LIKE @sku OR LOWER(i.sku_name) LIKE @sku))"
        )
        params.append(bq.p("sku", "STRING", _like(f["sku"])))
    if f.get("search"):
        conditions.append(
            "AND (LOWER(v.visit_id) LIKE @q OR LOWER(o.store_name) LIKE @q "
            "OR LOWER(o.source_outlet_code) LIKE @q OR LOWER(sm.salesman_name) LIKE @q "
            "OR EXISTS (SELECT 1 FROM " + item_tbl + " i WHERE i.visit_id = v.visit_id "
            "AND (LOWER(i.sku_id) LIKE @q OR LOWER(i.sku_name) LIKE @q)))"
        )
        params.append(bq.p("q", "STRING", _like(f["search"])))

    sql = f"""
    WITH agg AS (
      SELECT visit_id,
             COUNT(*) AS item_count,
             SUM(COALESCE(final_qty, qty)) AS quantity,
             MIN(sku_name) AS first_product
      FROM {item_tbl}
      GROUP BY visit_id
    )
    SELECT v.visit_id, v.visit_date, v.approval_status, v.total_demand,
           sm.salesman_name, o.store_name, o.source_outlet_code,
           o.distributor_code, o.distributor_name,
           COALESCE(a.item_count, 0) AS item_count,
           a.quantity, a.first_product
    FROM {_tbl('step_visit')} v
    LEFT JOIN (
      SELECT salesman_sk, salesman_name FROM {_tbl('dim_salesman')}
      QUALIFY ROW_NUMBER() OVER (PARTITION BY salesman_sk ORDER BY salesman_sk) = 1
    ) sm ON v.salesman_sk = sm.salesman_sk
    LEFT JOIN (
      SELECT outlet_sk, store_name, source_outlet_code, distributor_code, distributor_name
      FROM {_tbl('dim_outlet')}
      QUALIFY ROW_NUMBER() OVER (PARTITION BY outlet_sk ORDER BY outlet_sk) = 1
    ) o ON v.outlet_sk = o.outlet_sk
    LEFT JOIN agg a ON a.visit_id = v.visit_id
    WHERE {' '.join(conditions)}
    QUALIFY ROW_NUMBER() OVER (PARTITION BY v.visit_id ORDER BY v.updated_at DESC) = 1
    ORDER BY v.visit_date DESC, v.visit_id
    LIMIT @lim
    """
    try:
        rows = bq.query(sql, params + [bq.p("lim", "INT64", limit)])
    except Exception as exc:
        logger.exception("orders: SFA source failed")
        raise SourceUnavailable(str(exc)) from exc

    out: list[OrderRow] = []
    for r in rows:
        count = int(r.get("item_count") or 0)
        out.append(OrderRow(
            source=SOURCE_SFA,
            source_label=SOURCE_LABELS[SOURCE_SFA],
            order_id=r["visit_id"],
            order_number=r["visit_id"],
            order_date=_iso(r.get("visit_date")),
            store_id=r.get("source_outlet_code"),
            store_name=r.get("store_name"),
            distributor_code=r.get("distributor_code"),
            distributor_name=r.get("distributor_name"),
            salesman_name=r.get("salesman_name"),
            item_count=count,
            product_summary=_product_summary(count, r.get("first_product")),
            quantity=float(r["quantity"]) if r.get("quantity") is not None else None,
            order_value=r.get("total_demand"),
            status=r.get("approval_status"),
        ))
    return out


def fetch_sfa_items(bq, order_ids: list[str]) -> list[OrderItemRow]:
    safe = [i for i in order_ids if '"' not in i and "\\" not in i]
    if not safe:
        return []
    ids = ", ".join('"' + i + '"' for i in safe)
    rows = bq.query(
        "SELECT i.visit_id, i.sku_id, i.sku_name, i.qty, i.final_qty, i.stp, i.demand "
        "FROM " + _tbl("step_visit_item") + " i "
        "WHERE i.visit_id IN (" + ids + ") ORDER BY i.visit_id, i.sku_name"
    )
    out: list[OrderItemRow] = []
    for r in rows:
        qty = r.get("final_qty") if r.get("final_qty") is not None else r.get("qty")
        out.append(OrderItemRow(
            source=SOURCE_SFA,
            order_id=r["visit_id"],
            order_number=r["visit_id"],
            sku=r.get("sku_id"),
            product_name=r.get("sku_name"),
            quantity=float(qty) if qty is not None else None,
            unit_price=r.get("stp"),
            line_value=r.get("demand"),
        ))
    return out


# ---------------------------------------------------------------------------
# Spreadsheet (mirrored into BigQuery by services/ext_transactions.run_sync)
# ---------------------------------------------------------------------------

def fetch_sheet_orders(bq, user: UserContext, f: dict, limit: int) -> list[OrderRow]:
    item_tbl = _tbl("ext_visit_item")
    conditions: list[str] = ["TRUE"]
    params: list = []

    scope, scope_params = distributor_predicate(user, "e.distributor_code", "sh_dist")
    if scope:
        conditions.append(scope)
        params.extend(scope_params)

    role_clauses, role_params = role_scope(user, "e", "e.salesman_sk")
    conditions.extend(role_clauses)
    params.extend(role_params)

    if f.get("from_date"):
        conditions.append("AND e.visit_date >= @from_date")
        params.append(bq.p("from_date", "DATE", f["from_date"]))
    if f.get("to_date"):
        conditions.append("AND e.visit_date <= @to_date")
        params.append(bq.p("to_date", "DATE", f["to_date"]))
    if f.get("status"):
        conditions.append("AND e.visit_status = @status")
        params.append(bq.p("status", "STRING", f["status"]))
    if f.get("store"):
        conditions.append(
            "AND (LOWER(e.store_name) LIKE @store OR LOWER(e.source_store_id) LIKE @store)"
        )
        params.append(bq.p("store", "STRING", _like(f["store"])))
    if f.get("order_number"):
        conditions.append("AND LOWER(e.ext_visit_id) LIKE @ordno")
        params.append(bq.p("ordno", "STRING", _like(f["order_number"])))
    if f.get("sku"):
        conditions.append(
            "AND EXISTS (SELECT 1 FROM " + item_tbl + " i WHERE i.ext_visit_id = e.ext_visit_id "
            "AND (LOWER(i.sku_id) LIKE @sku OR LOWER(i.sku_name) LIKE @sku))"
        )
        params.append(bq.p("sku", "STRING", _like(f["sku"])))
    if f.get("search"):
        conditions.append(
            "AND (LOWER(e.ext_visit_id) LIKE @q OR LOWER(e.store_name) LIKE @q "
            "OR LOWER(e.source_store_id) LIKE @q OR LOWER(e.salesman_name) LIKE @q "
            "OR EXISTS (SELECT 1 FROM " + item_tbl + " i WHERE i.ext_visit_id = e.ext_visit_id "
            "AND (LOWER(i.sku_id) LIKE @q OR LOWER(i.sku_name) LIKE @q)))"
        )
        params.append(bq.p("q", "STRING", _like(f["search"])))

    sql = f"""
    SELECT e.ext_visit_id, e.visit_date, e.visit_status, e.computed_value, e.computed_qty,
           e.item_count, e.store_name, e.source_store_id, e.distributor_code, e.salesman_name,
           (SELECT MIN(sku_name) FROM {item_tbl} i
             WHERE i.ext_visit_id = e.ext_visit_id) AS first_product
    FROM {_tbl('ext_visit')} e
    WHERE {' '.join(conditions)}
    ORDER BY e.visit_date DESC, e.ext_visit_id
    LIMIT @lim
    """
    try:
        rows = bq.query(sql, params + [bq.p("lim", "INT64", limit)])
    except Exception as exc:
        logger.warning("orders: SPREADSHEET source unavailable (%s)", type(exc).__name__)
        raise SourceUnavailable(str(exc)) from exc

    out: list[OrderRow] = []
    for r in rows:
        count = int(r.get("item_count") or 0)
        out.append(OrderRow(
            source=SOURCE_SHEET,
            source_label=SOURCE_LABELS[SOURCE_SHEET],
            order_id=r["ext_visit_id"],
            order_number=r["ext_visit_id"],
            order_date=_iso(r.get("visit_date")),
            store_id=r.get("source_store_id"),
            store_name=r.get("store_name"),
            distributor_code=r.get("distributor_code"),
            distributor_name=None,   # the workbook carries no distributor name
            salesman_name=r.get("salesman_name"),
            item_count=count,
            product_summary=_product_summary(count, r.get("first_product")),
            quantity=r.get("computed_qty"),
            order_value=r.get("computed_value"),
            status=r.get("visit_status"),
        ))
    return out


def fetch_sheet_items(bq, order_ids: list[str]) -> list[OrderItemRow]:
    safe = [i for i in order_ids if '"' not in i and "\\" not in i]
    if not safe:
        return []
    ids = ", ".join('"' + i + '"' for i in safe)
    rows = bq.query(
        "SELECT ext_visit_id, sku_id, sku_name, qty, stp, line_value FROM "
        + _tbl("ext_visit_item") + " WHERE ext_visit_id IN (" + ids + ") "
        "ORDER BY ext_visit_id, sku_name"
    )
    return [
        OrderItemRow(
            source=SOURCE_SHEET,
            order_id=r["ext_visit_id"],
            order_number=r["ext_visit_id"],
            sku=r.get("sku_id"),
            product_name=r.get("sku_name"),
            quantity=r.get("qty"),
            unit_price=r.get("stp"),
            line_value=r.get("line_value"),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Merge / summarise — pure, unit-tested
# ---------------------------------------------------------------------------

SORT_KEYS = {
    "order_date": lambda o: (o.order_date or ""),
    "value": lambda o: (o.order_value or 0),
    "quantity": lambda o: (o.quantity or 0),
    "store": lambda o: (o.store_name or "").lower(),
    "source": lambda o: o.source,
    "status": lambda o: (o.status or ""),
}


def sort_orders(orders: list[OrderRow], sort_by: str, sort_order: str) -> list[OrderRow]:
    key = SORT_KEYS.get(sort_by, SORT_KEYS["order_date"])
    return sorted(orders, key=key, reverse=(str(sort_order).lower() != "asc"))


def summarise(orders: list[OrderRow]) -> dict:
    """Summary over the whole filtered set. Rows are already one-per-order, so a
    multi-item order counts once."""
    completed = sum(1 for o in orders if (o.status or "").upper() in COMPLETED_STATUSES)
    rejected = sum(1 for o in orders if (o.status or "").upper() in REJECTED_STATUSES)
    return {
        "total_orders": len(orders),
        "completed_orders": completed,
        "pending_orders": len(orders) - completed - rejected,
        "total_quantity": round(sum(o.quantity or 0 for o in orders), 2),
        "total_value": round(sum(o.order_value or 0 for o in orders), 2),
    }
