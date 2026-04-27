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

from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator


def build_pagination_response(request, queryset, serializer_class):
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

    return Response(
        {
            "status": "success",
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
            "links": {
                "self": build_link(page),
                "next": build_link(page + 1) if page < total_pages else None,
                "prev": build_link(page - 1) if page > 1 else None,
            },
            "data": serializer.data,
        }
    )


class ProfileListCreateView(APIView):

    @require_api_version
    @require_auth
    def get(self, request):
        """GET /api/profiles — all profiles with filtering, sorting, pagination"""
        queryset = Profile.objects.all()
        queryset = apply_filters(queryset, request.query_params)
        queryset = apply_sorting(queryset, request.query_params)
        return build_pagination_response(request, queryset, ProfileListSerializer)

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
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileSearchView(APIView):

    @require_api_version
    @require_auth
    def get(self, request):
        """GET /api/profiles/search?q=..."""
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

        queryset = Profile.objects.all()
        queryset = apply_filters(queryset, filters)
        queryset = apply_sorting(queryset, request.query_params)
        return build_pagination_response(request, queryset, ProfileListSerializer)


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
