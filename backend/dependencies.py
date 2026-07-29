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

# ---------------------------------------------------------------------------
# Brand-name ↔ brand_group normalization.
# The warehouse spells "brand" two ways:
#   - dim_outlet.brand          → marketing names: "Skintific", "Glad2Glow", "Timephoria"
#   - gt_schema.master_product  → codes:           "SKINTIFIC", "G2G", "TIMEPHORIA", ...
# BRAND_GROUPS above only knows the *codes*, so matching an outlet's marketing
# name against it silently fails (e.g. "Glad2Glow" ∉ ["G2G", ...]). These aliases
# fold BOTH spellings to the business-unit group so scoping is reliable.
_BRAND_ALIASES: dict[str, str] = {
    "SKINTIFIC": "SKT", "TIMEPHORIA": "SKT", "FACERINNA": "SKT", "TPH": "SKT", "SKT": "SKT",
    "G2G": "G2G", "GLAD2GLOW": "G2G", "GLAD 2 GLOW": "G2G", "BODIBREZE": "G2G", "NEXTPRIME": "G2G",
}

# Group → the set of brand SPELLINGS (names + codes) that belong to it. Used to
# build SQL `UPPER(brand) IN (...)` predicates for list endpoints whose `brand`
# column holds marketing names.
BRAND_NAMES_BY_GROUP: dict[str, list[str]] = {
    "SKT": ["SKINTIFIC", "TIMEPHORIA", "FACERINNA", "TPH"],
    "G2G": ["G2G", "GLAD2GLOW", "BODIBREZE", "NEXTPRIME"],
}


def brand_to_group(brand_value: str | None) -> str | None:
    """Normalize any brand spelling (name or code) to its brand_group, or None."""
    if not brand_value:
        return None
    key = brand_value.strip().upper()
    if key in _BRAND_ALIASES:
        return _BRAND_ALIASES[key]
    if key in BRAND_GROUPS:  # already a group code (SKT/G2G/DEMO)
        return key
    for alias, grp in _BRAND_ALIASES.items():  # compound-name fallback
        if alias in key:
            return grp
    return None


def _token_version_ok(user_id: str, tv_claim) -> bool:
    """E2E-14: reject tokens minted before the user's current token_version
    (bumped on logout / password reset / deactivate). Cached 30s per user to keep
    this off the hot path. Fail-OPEN: if the column is absent (pre-migration 004)
    or BigQuery is unreachable, we do not lock anyone out."""
    from services.bq import BQClient
    from config import settings
    bq = BQClient.get()
    cache_key = f"tokver:{user_id}"
    current = bq.cache.get(cache_key)
    if current is None:
        try:
            row = bq.query_one(
                f"SELECT token_version FROM {settings.table('users')} WHERE user_id = @id",
                [bq.p("id", "STRING", user_id)],
            )
            current = int((row or {}).get("token_version") or 0)
        except Exception:
            current = 0  # pre-migration / column missing / BQ error → no revocation
        bq.cache.set(cache_key, current, ttl=30)
    return int(tv_claim or 0) >= int(current)


def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> UserContext:
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    _uid = payload.get("sub")
    if _uid and not _token_version_ok(_uid, payload.get("tv")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session ended. Please log in again.")

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


def assert_brand_group_allowed(user: UserContext, entity_brand_group: str | None) -> None:
    """Object-level brand scoping for single-entity detail reads (E2E-03).

    Mirrors brand_group_filter exactly: ho_admin / dm / accounts with no brand_group
    / DEMO see everything. A restricted user may only open an entity whose
    brand_group equals theirs — the same rows their /list and /search already return
    (both filter `brand_group = @bg`, which likewise excludes NULL brand_group).

    Raises 404 (not 403) so an out-of-scope id is indistinguishable from a missing
    one — no cross-brand existence oracle.
    """
    if user.role in ("ho_admin", "dm") or not user.brand_group or user.brand_group in _UNRESTRICTED_GROUPS:
        return
    if (entity_brand_group or None) != user.brand_group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def assert_brand_name_allowed(user: UserContext, brand_value: str | None) -> None:
    """Same as assert_brand_group_allowed, but for entities carrying a brand NAME
    (e.g. dim_outlet.brand) rather than a brand_group code — normalizes via
    brand_to_group() so "Glad2Glow" correctly maps to G2G (E2E-03).

    Blocks only entities whose brand maps to a KNOWN, different group. An
    unclassified/unmappable brand (NULL or not in the alias table — common for
    federated SADATA outlets) is allowed through, matching brand_name_filter's
    `OR brand IS NULL`, so restricted users aren't over-blocked from shared stores.
    """
    if user.role in ("ho_admin", "dm") or not user.brand_group or user.brand_group in _UNRESTRICTED_GROUPS:
        return
    grp = brand_to_group(brand_value)
    if grp is not None and grp != user.brand_group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def brand_name_filter(
    user: UserContext,
    col: str = "brand",
    table_alias: str = "",
    param_prefix: str = "bnf",
) -> tuple[str, list]:
    """SQL predicate restricting a brand-NAME column to the caller's group (plus
    NULL/unclassified rows). ho_admin / dm / no brand_group / DEMO → no filter.
    Use for list endpoints whose `brand` column holds marketing names (E2E-03)."""
    from services.bq import BQClient
    if user.role in ("ho_admin", "dm") or not user.brand_group or user.brand_group in _UNRESTRICTED_GROUPS:
        return "", []
    names = BRAND_NAMES_BY_GROUP.get(user.brand_group, [])
    if not names:
        return "", []
    c = f"{table_alias}.{col}" if table_alias else col
    placeholders = ", ".join(f"@{param_prefix}_{i}" for i in range(len(names)))
    params = [BQClient.p(f"{param_prefix}_{i}", "STRING", n) for i, n in enumerate(names)]
    return f"AND (UPPER({c}) IN ({placeholders}) OR {c} IS NULL)", params


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
