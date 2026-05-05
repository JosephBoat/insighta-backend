import csv
from datetime import datetime, timezone
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Profile
from .serializers import ProfileSerializer, ProfileListSerializer
from .services import fetch_profile_data
from .filters import apply_filters, apply_sorting, apply_pagination
from .parser import parse_query
from .permissions import require_auth, require_admin, require_api_version
from .query_cache import build_cache_key, get_cached, set_cached, bump_version

from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator


def build_pagination_payload(request, queryset, serializer_class):
    """Build a paginated response dict (without wrapping in Response).
    Split out from build_pagination_response so we can cache the dict."""
    paginated, page, limit, total = apply_pagination(queryset, request.query_params)
    serializer = serializer_class(paginated, many=True)

    import math

    total_pages = math.ceil(total / limit) if limit > 0 else 1

    # Build base URL without page and limit params
    base_params = request.query_params.copy()
    base_params.pop("page", None)
    base_params.pop("limit", None)
    base_query = "&".join(f"{k}={v}" for k, v in base_params.items())
    base_path = request.path

    def build_link(p):
        params = f"page={p}&limit={limit}"
        if base_query:
            params += f"&{base_query}"
        return f"{base_path}?{params}"

    links = {
        "self": build_link(page),
        "next": build_link(page + 1) if page < total_pages else None,
        "prev": build_link(page - 1) if page > 1 else None,
    }
    pagination = {
        "page": page,
        "limit": limit,
        "per_page": limit,
        "total": total,
        "total_items": total,
        "total_pages": total_pages,
        "pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }

    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "pagination": pagination,
        "meta": {"pagination": pagination},
        "links": links,
        "data": list(serializer.data),
    }


def build_pagination_response(request, queryset, serializer_class):
    """Backward-compatible wrapper that returns a DRF Response."""
    return Response(build_pagination_payload(request, queryset, serializer_class))


def _cached_response_or_build(request, cache_key, build_payload):
    """
    Read-through cache helper: return a Response from cache if present,
    otherwise call build_payload(), cache the resulting payload, and return.
    `build_payload` returns a JSON-serializable dict (the body).
    """
    cached = get_cached(cache_key)
    if cached is not None:
        cached = {**cached, "cached": True}
        return Response(cached)

    payload = build_payload()
    set_cached(cache_key, payload)
    return Response({**payload, "cached": False})


class ProfileListCreateView(APIView):

    @require_api_version
    @require_auth
    def get(self, request):
        """GET /api/profiles — all profiles with filtering, sorting, pagination.
        Read-through cache: identical normalized queries hit Redis/LocMem."""
        cache_key = build_cache_key(request.query_params, scope="list")

        def build():
            queryset = Profile.objects.all()
            queryset = apply_filters(queryset, request.query_params)
            queryset = apply_sorting(queryset, request.query_params)
            return build_pagination_payload(request, queryset, ProfileListSerializer)

        return _cached_response_or_build(request, cache_key, build)

    @require_api_version
    @require_admin
    def post(self, request):
        """POST /api/profiles — create profile (admin only)"""
        name = request.data.get("name")

        if name is None or name == "":
            return Response(
                {"status": "error", "message": "name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(name, str):
            return Response(
                {"status": "error", "message": "name must be a string"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        name = name.strip().lower()

        existing = Profile.objects.filter(name=name).first()
        if existing:
            serializer = ProfileSerializer(existing)
            return Response(
                {
                    "status": "success",
                    "message": "Profile already exists",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        api_data, error_message = fetch_profile_data(name)
        if error_message:
            return Response(
                {"status": "error", "message": error_message},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        profile = Profile.objects.create(name=name, **api_data)
        # Invalidate every cached list/search response — the dataset changed.
        bump_version()
        serializer = ProfileSerializer(profile)
        return Response(
            {
                "status": "success",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class ProfileDetailView(APIView):

    @require_api_version
    @require_auth
    def get(self, request, pk):
        """GET /api/profiles/{id}"""
        try:
            profile = Profile.objects.get(pk=pk)
        except Profile.DoesNotExist:
            return Response(
                {"status": "error", "message": "Profile not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ProfileSerializer(profile)
        return Response({"status": "success", "data": serializer.data})

    @require_api_version
    @require_admin
    def delete(self, request, pk):
        """DELETE /api/profiles/{id} — admin only"""
        try:
            profile = Profile.objects.get(pk=pk)
        except Profile.DoesNotExist:
            return Response(
                {"status": "error", "message": "Profile not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        profile.delete()
        bump_version()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileSearchView(APIView):

    @require_api_version
    @require_auth
    def get(self, request):
        """GET /api/profiles/search?q=...

        The cache key is built from the *parsed and normalized filter dict*,
        not the raw query string. This means two queries that produce the
        same filters — "Nigerian women 20-45" vs "women aged 20-45 from
        Nigeria" — share a cache entry, even though their raw strings differ.
        """
        q = request.query_params.get("q", "").strip()

        if not q:
            return Response(
                {"status": "error", "message": "Unable to interpret query"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filters, error_message = parse_query(q)
        if error_message:
            return Response(
                {"status": "error", "message": error_message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Merge parsed filters with sort/page from the raw request.
        cache_input = {
            **filters,
            "sort_by": request.query_params.get("sort_by"),
            "order": request.query_params.get("order"),
            "page": request.query_params.get("page"),
            "limit": request.query_params.get("limit"),
        }
        cache_key = build_cache_key(cache_input, scope="search")

        def build():
            queryset = Profile.objects.all()
            queryset = apply_filters(queryset, filters)
            queryset = apply_sorting(queryset, request.query_params)
            return build_pagination_payload(request, queryset, ProfileListSerializer)

        return _cached_response_or_build(request, cache_key, build)


class ProfileImportView(APIView):
    """
    POST /api/profiles/import — bulk CSV upload (admin only).

    Accepts a multipart upload with the file under the form field `file`.
    Streams the CSV row-by-row, validates each row, batches valid rows for
    bulk insert, and reports a summary. Bad rows are skipped, never fatal.
    Already-inserted rows from a partial run remain in the DB.
    """

    @require_api_version
    @require_admin
    def post(self, request):
        from .ingestion import ingest_csv

        upload = request.FILES.get("file") or request.FILES.get("csv")
        if upload is None:
            return Response(
                {"status": "error", "message": "Upload a CSV under form field 'file'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            summary = ingest_csv(upload)
        except Exception as exc:
            # An unexpected error mid-stream — already-committed batches
            # remain in the DB per the partial-failure rule.
            return Response(
                {
                    "status": "error",
                    "message": f"Ingestion aborted: {exc}",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        http_status = (
            status.HTTP_200_OK
            if summary.get("status") == "success"
            else status.HTTP_400_BAD_REQUEST
        )
        return Response(summary, status=http_status)


class ProfileExportView(APIView):

    @require_api_version
    @require_auth
    def get(self, request):
        """
        GET /api/profiles/export?format=csv
        Exports filtered profiles as a CSV file.
        Applies same filters as GET /api/profiles.
        """
        export_format = request.query_params.get("format", "csv")

        if export_format != "csv":
            return Response(
                {"status": "error", "message": "Only csv format is supported"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = Profile.objects.all()
        queryset = apply_filters(queryset, request.query_params)
        queryset = apply_sorting(queryset, request.query_params)

        # Build CSV response
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"profiles_{timestamp}.csv"

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)

        # Header row — columns in exact order specified by TRD
        writer.writerow(
            [
                "id",
                "name",
                "gender",
                "gender_probability",
                "age",
                "age_group",
                "country_id",
                "country_name",
                "country_probability",
                "created_at",
            ]
        )

        # Data rows
        for profile in queryset:
            writer.writerow(
                [
                    str(profile.id),
                    profile.name,
                    profile.gender,
                    profile.gender_probability,
                    profile.age,
                    profile.age_group,
                    profile.country_id,
                    profile.country_name,
                    profile.country_probability,
                    profile.created_at.isoformat(),
                ]
            )

        return response
