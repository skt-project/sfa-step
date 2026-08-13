"""
Data-quality validation for the external distributor transaction source.

Reads the spreadsheet directly (no BigQuery write) and reports every check from
docs/current/17 §data quality. Run this BEFORE exposing new source data to
distributors, and after any change to the sheet's structure.

    cd backend
    python -m scripts.ops.validate_ext_transactions            # source checks only
    python -m scripts.ops.validate_ext_transactions --with-bq  # + STEP mapping coverage

--with-bq needs read access to sfa_web.dim_outlet / dim_salesman (BQ_SA_KEY_PATH
or ADC). Exits non-zero when a BLOCKING check fails, so it can gate a deploy.
"""
from __future__ import annotations

import argparse
import sys

# Allow `python -m scripts.ops.validate_ext_transactions` from backend/
sys.path.insert(0, ".")

from config import settings  # noqa: E402
from services.ext_transactions import (  # noqa: E402
    SheetUnavailable,
    fetch_sheet_rows,
    transform,
)

BLOCKING = "BLOCK"
WARNING = "WARN"
INFO = "INFO"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, level: str, check: str, detail: str) -> None:
        self.rows.append((level, check, detail))

    def print(self) -> int:
        width = max((len(c) for _, c, _ in self.rows), default=20)
        print("\n" + "=" * 78)
        print("EXTERNAL DISTRIBUTOR TRANSACTIONS - DATA QUALITY REPORT")
        print(f"spreadsheet: {settings.ext_tx_spreadsheet_id}")
        print("=" * 78)
        for level, check, detail in self.rows:
            mark = {BLOCKING: "[BLOCK]", WARNING: "[WARN ]", INFO: "[ ok  ]"}[level]
            print(f"{mark} {check.ljust(width)}  {detail}")
        blocking = sum(1 for lv, _, _ in self.rows if lv == BLOCKING)
        warnings = sum(1 for lv, _, _ in self.rows if lv == WARNING)
        print("-" * 78)
        print(f"{blocking} blocking, {warnings} warnings, {len(self.rows)} checks")
        print("=" * 78 + "\n")
        return blocking


def validate_source(rep: Report) -> tuple[list, dict]:
    try:
        visit_rows = fetch_sheet_rows(settings.ext_tx_visit_gid)
        item_rows = fetch_sheet_rows(settings.ext_tx_visit_item_gid)
        try:
            sku_rows = fetch_sheet_rows(settings.ext_tx_sku_gid)
        except SheetUnavailable:
            sku_rows = []
    except SheetUnavailable as exc:
        rep.add(BLOCKING, "source readable", f"cannot read the spreadsheet: {exc}")
        return [], {}

    rep.add(INFO, "source readable", "visit + visit_item tabs fetched")

    visits, res = transform(visit_rows, item_rows, sku_rows)

    rep.add(INFO if res.visits_read else WARNING, "total visit rows", str(res.visits_read))
    rep.add(INFO if res.items_read else WARNING, "total visit_item rows", str(res.items_read))
    rep.add(INFO, "unique visit ids", str(len(visits)))

    rep.add(WARNING if res.duplicate_visits else INFO,
            "duplicate transaction ids", f"{res.duplicate_visits} (last occurrence wins)")
    rep.add(WARNING if res.invalid_visits else INFO,
            "invalid visit rows", f"{res.invalid_visits} rejected")
    rep.add(WARNING if res.invalid_items else INFO,
            "invalid item rows", f"{res.invalid_items} rejected (bad qty/price)")
    rep.add(BLOCKING if res.orphan_items else INFO,
            "items without a parent visit", f"{res.orphan_items} orphan rows")

    no_items = sum(1 for v in visits if v.item_count == 0)
    rep.add(WARNING if no_items else INFO,
            "visits without items", f"{no_items} kept with zero detail")

    null_dates = sum(1 for v in visits if v.visit_date is None)
    rep.add(BLOCKING if null_dates else INFO, "null transaction dates", str(null_dates))

    bad_qty = sum(1 for v in visits for i in v.items if (i.qty or 0) < 0)
    bad_val = sum(1 for v in visits for i in v.items if (i.line_value or 0) < 0)
    rep.add(BLOCKING if bad_qty else INFO, "negative quantities", str(bad_qty))
    rep.add(BLOCKING if bad_val else INFO, "negative monetary values", str(bad_val))

    rep.add(WARNING if res.total_mismatches else INFO,
            "source total != item sum", f"{res.total_mismatches} transactions")

    missing_sm = sum(1 for v in visits if not v.source_username)
    missing_st = sum(1 for v in visits if not v.source_store_id)
    rep.add(WARNING if missing_sm else INFO, "visits with no salesman id", str(missing_sm))
    rep.add(WARNING if missing_st else INFO, "visits with no store id", str(missing_st))

    if visits:
        dates = sorted(v.visit_date for v in visits if v.visit_date)
        if dates:
            rep.add(INFO, "date range", f"{dates[0]} .. {dates[-1]}")

    return visits, {
        "usernames": {v.source_username for v in visits if v.source_username},
        "store_ids": {v.source_store_id for v in visits if v.source_store_id},
    }


def validate_mapping(rep: Report, keys: dict) -> None:
    """Check how much of the source resolves onto STEP masters. Unmapped stores
    are the critical one: without a distributor_code no dm can ever see them."""
    from services.bq import BQClient

    bq = BQClient.get()
    usernames = sorted(keys.get("usernames") or [])
    store_ids = sorted(keys.get("store_ids") or [])

    if not store_ids and not usernames:
        rep.add(INFO, "STEP mapping", "no source keys to check (empty source)")
        return

    if store_ids:
        arr = ",".join(f'"{s}"' for s in store_ids)
        row = bq.query_one(f"""
            WITH src AS (SELECT * FROM UNNEST([{arr}]) AS code)
            SELECT COUNT(*) AS total,
                   COUNTIF(o.source_outlet_code IS NOT NULL) AS matched,
                   COUNT(DISTINCT o.distributor_code) AS distributors
            FROM src s
            LEFT JOIN {settings.table('dim_outlet')} o ON o.source_outlet_code = s.code
        """) or {}
        total, matched = int(row.get("total") or 0), int(row.get("matched") or 0)
        pct = (matched / total * 100) if total else 0
        rep.add(BLOCKING if pct < 50 else (WARNING if pct < 100 else INFO),
                "stores mapped to dim_outlet",
                f"{matched}/{total} ({pct:.1f}%) - unmapped stores are invisible to every dm")
        rep.add(INFO, "distinct distributor codes", str(int(row.get("distributors") or 0)))

    if usernames:
        arr = ",".join(f'"{u}"' for u in usernames)
        row = bq.query_one(f"""
            WITH src AS (SELECT * FROM UNNEST([{arr}]) AS code)
            SELECT COUNT(*) AS total,
                   COUNTIF(d.source_salesman_code IS NOT NULL) AS matched
            FROM src s
            LEFT JOIN {settings.table('dim_salesman')} d
              ON d.source_salesman_code = s.code
        """) or {}
        total, matched = int(row.get("total") or 0), int(row.get("matched") or 0)
        pct = (matched / total * 100) if total else 0
        rep.add(WARNING if pct < 100 else INFO,
                "salesmen mapped to dim_salesman",
                f"{matched}/{total} ({pct:.1f}%)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with-bq", action="store_true",
                    help="also check mapping coverage against STEP masters")
    args = ap.parse_args()

    rep = Report()
    _, keys = validate_source(rep)
    if args.with_bq:
        try:
            validate_mapping(rep, keys)
        except Exception as exc:  # noqa: BLE001 — report, don't crash the check run
            rep.add(WARNING, "STEP mapping", f"could not check: {type(exc).__name__}: {exc}")

    return 1 if rep.print() else 0


if __name__ == "__main__":
    raise SystemExit(main())
