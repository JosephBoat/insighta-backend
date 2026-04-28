import hashlib
import base64
from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import RefreshToken
from .tokens import generate_access_token, generate_refresh_token
from .auth_service import exchange_code_for_token, get_github_user, get_or_create_user
from .middleware import get_user_from_request


def check_rate_limit(request, key_prefix, limit, window=60):
    """
    Simple rate limiter using Django's cache.
    Returns True if rate limit exceeded.
    """
    ip = request.META.get(
        "HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", "unknown")
    )
    if "," in str(ip):
        ip = ip.split(",")[0].strip()
    cache_key = f"ratelimit:{key_prefix}:{ip}"
    requests_made = cache.get(cache_key, 0)
    if requests_made >= limit:
        return True
    cache.set(cache_key, requests_made + 1, window)
    return False


class GithubLoginView(APIView):
    """GET /auth/github — redirect to GitHub OAuth"""

    def get(self, request):
        if check_rate_limit(request, "auth", 10):
            return Response(
                {"status": "error", "message": "Too many requests"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        state = request.query_params.get("state", "")
        code_challenge = request.query_params.get("code_challenge", "")
        code_challenge_method = request.query_params.get(
            "code_challenge_method", "S256"
        )

        params = (
            f"client_id={settings.GITHUB_CLIENT_ID}"
            f"&redirect_uri={settings.GITHUB_REDIRECT_URI}"
            f"&scope=user:email"
            f"&state={state}"
        )
        if code_challenge:
            params += (
                f"&code_challenge={code_challenge}"
                f"&code_challenge_method={code_challenge_method}"
            )

        github_url = f"https://github.com/login/oauth/authorize?{params}"
        return redirect(github_url)


class GithubCallbackView(APIView):
    """GET /auth/github/callback — handle OAuth callback"""

    def get(self, request):
        if check_rate_limit(request, "auth", 10):
            return Response(
                {"status": "error", "message": "Too many requests"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        code = request.query_params.get("code")
        state = request.query_params.get("state")
        code_verifier = request.query_params.get("code_verifier")
        is_cli = request.query_params.get("cli") == "true"

        if not code:
            return Response(
                {"status": "error", "message": "No code provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not state:
            return Response(
                {"status": "error", "message": "Missing state parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        github_token, error = exchange_code_for_token(code, code_verifier)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        github_user_data, error = get_github_user(github_token)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        user = get_or_create_user(github_user_data)

        if not user.is_active:
            return Response(
                {"status": "error", "message": "Account is inactive"},
                status=status.HTTP_403_FORBIDDEN,
            )

        tokens = {
            "access_token": generate_access_token(user),
            "refresh_token": generate_refresh_token(user),
        }

        if is_cli:
            return Response(
                {
                    "status": "success",
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "username": user.username,
                }
            )

        frontend_url = (
            f"{settings.FRONTEND_URL}/index.html"
            f"?access_token={tokens['access_token']}"
            f"&refresh_token={tokens['refresh_token']}"
        )
        return redirect(frontend_url)


class RefreshTokenView(APIView):
    """POST /auth/refresh — exchange refresh token for new pair"""

    def post(self, request):
        if check_rate_limit(request, "auth", 10):
            return Response(
                {"status": "error", "message": "Too many requests"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        refresh_token_value = request.data.get("refresh_token")

        if not refresh_token_value:
            return Response(
                {"status": "error", "message": "refresh_token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token_obj = RefreshToken.objects.select_related("user").get(
                token=refresh_token_value
            )
        except RefreshToken.DoesNotExist:
            return Response(
                {"status": "error", "message": "Invalid refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if token_obj.expires_at < timezone.now():
            token_obj.delete()
            return Response(
                {"status": "error", "message": "Refresh token expired"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = token_obj.user

        if not user.is_active:
            return Response(
                {"status": "error", "message": "Account is inactive"},
                status=status.HTTP_403_FORBIDDEN,
            )

        token_obj.delete()

        return Response(
            {
                "status": "success",
                "access_token": generate_access_token(user),
                "refresh_token": generate_refresh_token(user),
            }
        )


class LogoutView(APIView):
    """POST /auth/logout — invalidate refresh token"""

    def post(self, request):
        refresh_token_value = request.data.get("refresh_token")

        if not refresh_token_value:
            return Response(
                {"status": "error", "message": "refresh_token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        RefreshToken.objects.filter(token=refresh_token_value).delete()

        return Response({"status": "success", "message": "Logged out successfully"})


class WhoAmIView(APIView):
    """GET /auth/whoami and GET /api/users/me — return current user"""

    def get(self, request):
        user, error = get_user_from_request(request)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            {
                "status": "success",
                "data": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "avatar_url": user.avatar_url,
                    "role": user.role,
                    "created_at": user.created_at,
                },
            }
        )


class DirectAuthView(APIView):
    """
    POST /auth/token
    Accepts a GitHub access token directly and returns our JWT tokens.
    Used for programmatic/API-based authentication (CLI, testing).
    """

    def post(self, request):
        if check_rate_limit(request, "auth", 10):
            return Response(
                {"status": "error", "message": "Too many requests"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        github_token = request.data.get("github_token") or request.data.get(
            "access_token"
        )

        if not github_token:
            return Response(
                {"status": "error", "message": "github_token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        github_user_data, error = get_github_user(github_token)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = get_or_create_user(github_user_data)

        if not user.is_active:
            return Response(
                {"status": "error", "message": "Account is inactive"},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {
                "status": "success",
                "access_token": generate_access_token(user),
                "refresh_token": generate_refresh_token(user),
                "token_type": "Bearer",
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "role": user.role,
                },
            }
        )
