import hashlib
import base64
from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import RefreshToken
from .tokens import generate_access_token, generate_refresh_token
from .auth_service import exchange_code_for_token, get_github_user, get_or_create_user
from .middleware import get_user_from_request
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator


@method_decorator(ratelimit(key="ip", rate="10/m", block=True), name="get")
class GithubLoginView(APIView):
    """
    GET /auth/github
    Redirects the user to GitHub's OAuth authorization page.
    The state parameter prevents CSRF attacks on the OAuth flow.
    """

    def get(self, request):
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


@method_decorator(ratelimit(key="ip", rate="10/m", block=True), name="get")
class GithubCallbackView(APIView):
    """
    GET /auth/github/callback
    GitHub redirects here after user authenticates.
    We exchange the code for tokens and redirect to frontend.
    """

    def get(self, request):
        code = request.query_params.get("code")
        state = request.query_params.get("state", "")
        code_verifier = request.query_params.get("code_verifier")
        is_cli = request.query_params.get("cli") == "true"

        if not code:
            return Response(
                {"status": "error", "message": "No code provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Exchange code for GitHub token
        github_token, error = exchange_code_for_token(code, code_verifier)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Get user info from GitHub
        github_user_data, error = get_github_user(github_token)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Create or update user in our DB
        user = get_or_create_user(github_user_data)

        if not user.is_active:
            return Response(
                {"status": "error", "message": "Account is inactive"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Issue our own tokens
        tokens = {
            "access_token": generate_access_token(user),
            "refresh_token": generate_refresh_token(user),
        }

        # CLI flow — return JSON directly
        if is_cli:
            return Response(
                {
                    "status": "success",
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "username": user.username,
                }
            )

        # Web flow — redirect to frontend with tokens in URL
        # Frontend will store in HTTP-only cookie
        frontend_url = (
            f"{settings.FRONTEND_URL}/index.html"
            f"?access_token={tokens['access_token']}"
            f"&refresh_token={tokens['refresh_token']}"
        )
        return redirect(frontend_url)


@method_decorator(ratelimit(key="ip", rate="10/m", block=True), name="post")
class RefreshTokenView(APIView):
    """
    POST /auth/refresh
    Exchange a refresh token for a new access + refresh token pair.
    The old refresh token is immediately invalidated (token rotation).
    """

    def post(self, request):
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

        # Check expiry
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

        # Invalidate old token immediately (token rotation)
        token_obj.delete()

        # Issue new token pair
        return Response(
            {
                "status": "success",
                "access_token": generate_access_token(user),
                "refresh_token": generate_refresh_token(user),
            }
        )


class LogoutView(APIView):
    """
    POST /auth/logout
    Invalidates the refresh token server-side.
    """

    def post(self, request):
        refresh_token_value = request.data.get("refresh_token")

        if refresh_token_value:
            RefreshToken.objects.filter(token=refresh_token_value).delete()

        return Response({"status": "success", "message": "Logged out successfully"})


class WhoAmIView(APIView):
    """
    GET /auth/whoami
    Returns the currently authenticated user's info.
    Used by the CLI's `insighta whoami` command.
    """

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
