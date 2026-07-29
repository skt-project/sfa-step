"""
Unit tests for the authorization + data-consistency fixes from the ecosystem
E2E audit (docs/current/13-ecosystem-e2e-audit.md). These are deliberately
BigQuery-free so they run in CI without credentials — they cover the pure logic:
model validation floors, the visit ownership guard (salesman path), and the
single-entity brand-scope helper.
"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.auth import UserContext
from models.visit import CheckoutRequest, FinalQtyItem, StorePriceItem, VisitItemIn


# ── E2E-10: negative quantities/prices must be rejected ───────────────────────

def test_visititem_rejects_negative_qty_and_price():
    assert VisitItemIn(sku_id="X", qty=3, stp=1000).qty == 3  # valid still works
    with pytest.raises(ValidationError):
        VisitItemIn(sku_id="X", qty=-1)
    with pytest.raises(ValidationError):
        VisitItemIn(sku_id="X", stp=-5)


def test_final_qty_and_price_and_total_reject_negative():
    with pytest.raises(ValidationError):
        FinalQtyItem(sku_id="X", final_qty=-1)
    with pytest.raises(ValidationError):
        StorePriceItem(sku_id="X", price_for_store=-1)
    with pytest.raises(ValidationError):
        CheckoutRequest(total_demand=-1)


# ── E2E-01: visit ownership guard (salesman path is BQ-free) ──────────────────

def _se(sk="SK-100"):
    return UserContext(user_id="u1", username="se1", role="salesman", salesman_sk=sk)


def test_salesman_can_act_on_own_visit():
    from routers.visit import _assert_can_act_on_visit
    _assert_can_act_on_visit(None, _se(), "SK-100")  # no raise


def test_salesman_blocked_from_other_visit():
    from routers.visit import _assert_can_act_on_visit
    with pytest.raises(HTTPException) as e:
        _assert_can_act_on_visit(None, _se(), "SK-999")
    assert e.value.status_code == 403


def test_admin_roles_pass_ownership_guard():
    from routers.visit import _assert_can_act_on_visit
    for role in ("ho_admin", "dm", "asm"):
        u = UserContext(user_id="a", username=role, role=role)
        _assert_can_act_on_visit(None, u, "SK-ANY")  # no raise


# ── E2E-03: single-entity brand scope ─────────────────────────────────────────

def test_brand_scope_allows_admin_and_in_scope():
    from dependencies import assert_brand_group_allowed
    assert_brand_group_allowed(UserContext(user_id="a", username="adm", role="ho_admin"), "G2G")
    assert_brand_group_allowed(UserContext(user_id="b", username="asm", role="asm", brand_group="SKT"), "SKT")


@pytest.mark.parametrize("entity_bg", ["G2G", None])
def test_brand_scope_blocks_out_of_scope_and_null(entity_bg):
    from dependencies import assert_brand_group_allowed
    skt = UserContext(user_id="b", username="asm", role="asm", brand_group="SKT")
    with pytest.raises(HTTPException) as e:
        assert_brand_group_allowed(skt, entity_bg)
    assert e.value.status_code == 404
