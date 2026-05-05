from .models import Profile


VALID_SORT_FIELDS = {"age", "created_at", "gender_probability"}
VALID_ORDERS = {"asc", "desc"}


def apply_filters(queryset, params: dict):
    """
    Apply all supported filters to a queryset.
    Each filter is optional — only applied if the parameter is present.

    Values are normalized to the canonical storage form (gender/age_group
    lowercase, country_id uppercase) so we can use case-sensitive `__exact`
    lookups, which can use the btree indexes on those columns. Switching
    away from `__iexact` is the single biggest query-performance win at
    scale, because `__iexact` (ILIKE) cannot use a plain btree index.
    """
    gender = params.get("gender")
    age_group = params.get("age_group")
    country_id = params.get("country_id")
    min_age = params.get("min_age")
    max_age = params.get("max_age")
    min_gender_probability = params.get("min_gender_probability")
    min_country_probability = params.get("min_country_probability")

    if gender:
        queryset = queryset.filter(gender=str(gender).strip().lower())
    if age_group:
        queryset = queryset.filter(age_group=str(age_group).strip().lower())
    if country_id:
        queryset = queryset.filter(country_id=str(country_id).strip().upper())
    if min_age:
        queryset = queryset.filter(age__gte=int(min_age))
    if max_age:
        queryset = queryset.filter(age__lte=int(max_age))
    if min_gender_probability:
        queryset = queryset.filter(
            gender_probability__gte=float(min_gender_probability)
        )
    if min_country_probability:
        queryset = queryset.filter(
            country_probability__gte=float(min_country_probability)
        )

    return queryset


def apply_sorting(queryset, params: dict):
    """
    Apply sorting to a queryset.
    Defaults to created_at ascending if not specified.
    """
    sort_by = params.get("sort_by", "created_at")
    order = params.get("order", "asc")

    if sort_by not in VALID_SORT_FIELDS:
        sort_by = "created_at"
    if order not in VALID_ORDERS:
        order = "asc"

    order_prefix = "-" if order == "desc" else ""
    return queryset.order_by(f"{order_prefix}{sort_by}")


def apply_pagination(queryset, params: dict) -> tuple:
    """
    Apply pagination to a queryset.
    Returns (paginated_queryset, page, limit, total).
    limit is capped at 50 as per task requirements.
    """
    try:
        page = max(1, int(params.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = min(50, max(1, int(params.get("limit", 10))))
    except (ValueError, TypeError):
        limit = 10

    total = queryset.count()
    offset = (page - 1) * limit
    paginated = queryset[offset : offset + limit]

    return paginated, page, limit, total
