"""
Unit tests for the unified multi-source order model.

BQ-free: pure functions only (scoping predicates, sorting, summarising). The
query paths are covered by the end-to-end suite against real BigQuery.
"""
import pytest

from models.auth import UserContext
from models.order import OrderRow
from services.orders import (
    SOURCE_LABELS,
    SOURCE_SFA,
    SOURCE_SHEET,
    distributor_predicate,
    sort_orders,
    summarise,
)


def _user(role, dist=None, sk=None, bg=None):
    return UserContext(user_id="u", username="t", role=role,
                       distributor_code=dist, brand_group=bg, salesman_sk=sk)


def _order(**kw):
    base = dict(
        source=SOURCE_SFA, source_label=SOURCE_LABELS[SOURCE_SFA],
        order_id="O1", order_number="O1", order_date="2026-08-12",
        item_count=1, quantity=1, order_value=1000, status="COMPLETED",
    )
    base.update(kw)
    return OrderRow(**base)


# ── Distributor scoping — the security-critical part ─────────────────────────

def test_dm_is_pinned_to_its_own_distributor():
    clause, params = distributor_predicate(_user("dm", "DST157"), "o.distributor_code", "d")
    assert "o.distributor_code IN (@d_0)" in clause
    assert params[0].value == "DST157"


def test_dm_with_multiple_comma_separated_codes_sees_all_of_them():
    """A dm claim accepts a comma-separated list — e.g. a roaming/test account
    covering more than one distributor. A single code is just a one-element list,
    so this is fully backward compatible with every real (single-code) account."""
    clause, params = distributor_predicate(_user("dm", "DST157,DST105"), "o.distributor_code", "d")
    assert clause == "AND o.distributor_code IN (@d_0, @d_1)"
    assert [p.value for p in params] == ["DST157", "DST105"]


def test_dm_multi_code_list_tolerates_stray_whitespace():
    clause, params = distributor_predicate(_user("dm", "DST157, DST105 ,"), "o.distributor_code", "d")
    assert [p.value for p in params] == ["DST157", "DST105"]


def test_dm_without_a_distributor_code_sees_nothing():
    """Regression guard. This previously fell through with NO predicate at all,
    so an unscoped distributor account saw every distributor's orders."""
    clause, params = distributor_predicate(_user("dm", None), "o.distributor_code", "d")
    assert clause == "AND 1=0"
    assert params == []


def test_dm_with_blank_distributor_code_also_fails_closed():
    clause, _ = distributor_predicate(_user("dm", ""), "o.distributor_code", "d")
    assert clause == "AND 1=0"


@pytest.mark.parametrize("role", ["ho_admin", "spv", "asm", "se"])
def test_non_dm_roles_get_no_distributor_predicate(role):
    """Other roles are scoped by their own rules (brand group / SPV team), not by
    distributor — applying a distributor filter here would over-restrict them."""
    clause, params = distributor_predicate(_user(role, "DST157"), "o.distributor_code", "d")
    assert clause == "" and params == []


def test_the_predicate_targets_the_column_it_is_given():
    """Both sources reuse this helper against different tables."""
    sfa, _ = distributor_predicate(_user("dm", "D1"), "o.distributor_code", "a")
    sheet, _ = distributor_predicate(_user("dm", "D1"), "e.distributor_code", "b")
    assert "o.distributor_code" in sfa and "e.distributor_code" in sheet


# ── Sorting ──────────────────────────────────────────────────────────────────

def test_sort_by_date_desc_by_default():
    rows = [_order(order_id="a", order_date="2026-08-01"),
            _order(order_id="b", order_date="2026-08-20")]
    assert [o.order_id for o in sort_orders(rows, "order_date", "desc")] == ["b", "a"]


def test_sort_ascending():
    rows = [_order(order_id="a", order_date="2026-08-20"),
            _order(order_id="b", order_date="2026-08-01")]
    assert [o.order_id for o in sort_orders(rows, "order_date", "asc")] == ["b", "a"]


def test_unknown_sort_key_falls_back_to_date_rather_than_raising():
    rows = [_order(order_id="a", order_date="2026-08-01"),
            _order(order_id="b", order_date="2026-08-20")]
    assert [o.order_id for o in sort_orders(rows, "'; DROP TABLE x--", "desc")] == ["b", "a"]


def test_sort_handles_missing_values():
    rows = [_order(order_id="a", order_value=None), _order(order_id="b", order_value=500)]
    assert [o.order_id for o in sort_orders(rows, "value", "desc")] == ["b", "a"]


def test_sort_mixes_sources_into_one_ordering():
    rows = [_order(order_id="sfa", order_date="2026-08-01"),
            _order(order_id="sheet", source=SOURCE_SHEET,
                   source_label=SOURCE_LABELS[SOURCE_SHEET], order_date="2026-08-20")]
    assert [o.order_id for o in sort_orders(rows, "order_date", "desc")] == ["sheet", "sfa"]


# ── Summary ──────────────────────────────────────────────────────────────────

def test_summary_counts_each_order_once_regardless_of_item_count():
    rows = [_order(order_id="a", item_count=5, quantity=17, order_value=450000),
            _order(order_id="b", item_count=1, quantity=2, order_value=50000)]
    s = summarise(rows)
    assert s["total_orders"] == 2
    assert s["total_quantity"] == 19
    assert s["total_value"] == 500000


def test_pending_excludes_completed_and_rejected():
    rows = [_order(order_id="a", status="COMPLETED"),
            _order(order_id="b", status="REJECTED"),
            _order(order_id="c", status="SPV_APPROVED"),
            _order(order_id="d", status="PENDING_SPV")]
    s = summarise(rows)
    assert s["completed_orders"] == 1
    assert s["pending_orders"] == 2   # c and d; the rejected one is neither


def test_summary_of_an_empty_set_is_all_zero():
    assert summarise([]) == {
        "total_orders": 0, "completed_orders": 0, "pending_orders": 0,
        "total_quantity": 0, "total_value": 0,
    }


def test_summary_tolerates_missing_amounts():
    rows = [_order(order_id="a", quantity=None, order_value=None)]
    s = summarise(rows)
    assert s["total_orders"] == 1 and s["total_quantity"] == 0 and s["total_value"] == 0


def test_status_matching_is_case_insensitive():
    assert summarise([_order(status="completed")])["completed_orders"] == 1


# ── Model contract ───────────────────────────────────────────────────────────

def test_every_row_must_carry_a_source():
    """`source` is mandatory: the table labels provenance without opening a row."""
    with pytest.raises(Exception):
        OrderRow(order_id="x", source_label="x")  # type: ignore[call-arg]


def test_both_sources_have_human_labels():
    assert SOURCE_LABELS[SOURCE_SFA] == "STEP Handheld / SFA"
    assert SOURCE_LABELS[SOURCE_SHEET] == "Spreadsheet"


def test_absent_fields_stay_none_rather_than_being_invented():
    o = _order(store_name=None, distributor_name=None)
    assert o.store_name is None and o.distributor_name is None
