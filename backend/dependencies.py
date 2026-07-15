"""
FastAPI dependency for JWT authentication.
Usage: current_user: UserContext = Depends(require_auth)
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from models.auth import UserContext
from services.auth import decode_token

_bearer = HTTPBearer()

# Business Unit → brand mapping. Brand values in gt_schema.master_product are
# UPPERCASE — comparisons against these lists must uppercase both sides.
# (Title-case lists previously caused empty product lists and checkout 403s
# for brand-scoped salesmen.)
# BU 1 (SKT): SKINTIFIC, TIMEPHORIA, FACERINNA
# BU 2 (G2G): G2G (Glad2Glow), BODIBREZE, NEXTPRIME
# DEMO: unrestricted — sees all brands and all salesmen (for demo/testing accounts)
BRAND_GROUPS: dict[str, list[str]] = {
    "SKT": ["SKINTIFIC", "TIMEPHORIA", "FACERINNA"],
    "G2G": ["G2G", "BODIBREZE", "NEXTPRIME"],
    "DEMO": ["SKINTIFIC", "TIMEPHORIA", "FACERINNA", "G2G", "BODIBREZE", "NEXTPRIME"],
}

# brand_groups that bypass all SQL row-level filters (see all routes, all salesmen)
_UNRESTRICTED_GROUPS = {"DEMO"}


def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> UserContext:
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    try:
        sk = payload.get("salesman_sk")
        return UserContext(
            user_id=payload["sub"],
            username=payload["username"],
            role=payload["role"],
            territory=payload.get("territory"),
            distributor_code=payload.get("distributor_code"),
            brand_group=payload.get("brand_group") or None,
            salesman_sk=sk or None,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")


def require_role(*roles: str):
    """Factory: Depends(require_role('ho_admin', 'dm'))"""
    def _check(user: UserContext = Depends(require_auth)) -> UserContext:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return _check


def brand_group_filter(
    user: UserContext,
    param_name: str = "bg",
    table_alias: str = "",
) -> tuple[str, list]:
    """
    Returns (SQL fragment, BQ params) to filter by brand_group column on dim_salesman.
    ho_admin and dm see all brands; users without a brand_group get no filter.
    Pass table_alias (e.g. "sm") when the query joins multiple tables.
    """
    from services.bq import BQClient
    if user.role in ("ho_admin", "dm") or not user.brand_group or user.brand_group in _UNRESTRICTED_GROUPS:
        return "", []
    col = f"{table_alias}.brand_group" if table_alias else "brand_group"
    return f"AND {col} = @{param_name}", [BQClient.p(param_name, "STRING", user.brand_group)]


def brand_list_filter(
    user: UserContext,
    col: str = "brand",
    param_prefix: str = "bgb",
) -> tuple[str, list]:
    """
    Returns (SQL fragment, BQ params) to restrict a `brand` column to the brands
    that belong to the user's business group.  Used for tables (e.g. spv_target)
    that store the brand name rather than a brand_group foreign key.

    ho_admin / dm / no brand_group → no restriction (sees all brands).
    Unknown brand_group            → restrict to nothing (AND 1=0).
    """
    from services.bq import BQClient
    if user.role in ("ho_admin", "dm") or not user.brand_group or user.brand_group in _UNRESTRICTED_GROUPS:
        return "", []
    brands = BRAND_GROUPS.get(user.brand_group, [])
    if not brands:
        return "AND 1=0", []
    placeholders = ", ".join(f"@{param_prefix}_{i}" for i in range(len(brands)))
    params = [BQClient.p(f"{param_prefix}_{i}", "STRING", b) for i, b in enumerate(brands)]
    # UPPER() on the column: brand casing differs between tables
    # (master_product is UPPERCASE, older tables may be Title-case).
    return f"AND UPPER({col}) IN ({placeholders})", params


def spv_salesman_filter(
    user: UserContext,
    salesman_col: str = "salesman_sk",
    param_name: str = "spv_own",
) -> tuple[str, list]:
    """
    One-Line-Management: restrict rows to salesmen assigned to this SPV
    (dim_salesman.spv_name matches the SPV user's full_name/username).

    Only applies to role 'spv'. If the SPV has NO mapped salesmen in
    dim_salesman, no filter is added (graceful fallback to brand-group
    scoping) so unmapped/test SPV accounts keep working.
    """
    from services.bq import BQClient
    from config import settings

    if user.role != "spv":
        return "", []

    bq = BQClient.get()
    # Resolve the SPV's display name once (users.full_name), cached 5 min.
    cache_key = f"spvmap:{user.user_id}"
    has_team = bq.cache.get(cache_key)
    if has_team is None:
        row = bq.query_one(
            f"SELECT full_name FROM {settings.table('users')} WHERE user_id = @uid",
            [bq.p("uid", "STRING", user.user_id)],
        )
        spv_name = (row or {}).get("full_name") or user.username
        n = bq.query_one(
            f"SELECT COUNT(*) AS n FROM {settings.table('dim_salesman')} "
            "WHERE UPPER(spv_name) = UPPER(@nm) AND is_active = TRUE",
            [bq.p("nm", "STRING", spv_name)],
        )
        has_team = {"name": spv_name, "count": int((n or {}).get("n", 0))}
        bq.cache.set(cache_key, has_team, ttl=300)

    if has_team["count"] == 0:
        return "", []  # unmapped SPV — fall back to brand-group scoping only

    clause = (
        f"AND {salesman_col} IN ("
        f"SELECT salesman_sk FROM {settings.table('dim_salesman')} "
        f"WHERE UPPER(spv_name) = UPPER(@{param_name}) AND is_active = TRUE)"
    )
    return clause, [BQClient.p(param_name, "STRING", has_team["name"])]
