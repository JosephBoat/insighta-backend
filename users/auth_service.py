import requests
from django.conf import settings
from django.utils import timezone
from .models import User
from .tokens import generate_access_token, generate_refresh_token


def exchange_code_for_token(code: str, code_verifier: str = None) -> tuple:
    payload = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    response = requests.post(
        "https://github.com/login/oauth/access_token",
        json=payload,
        headers={"Accept": "application/json"},
        timeout=10,
    )

    print("GitHub response status:", response.status_code)
    print("GitHub response body:", response.json())

    if response.status_code != 200:
        return None, "Failed to exchange code with GitHub"

    data = response.json()
    token = data.get("access_token")

    if not token:
        return None, "GitHub did not return an access token"

    return token, None


def get_github_user(github_token: str) -> tuple:
    """
    Use the GitHub access token to fetch the user's profile.
    Returns (user_data_dict, error_message)
    """
    response = requests.get(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/json",
        },
        timeout=10,
    )

    if response.status_code != 200:
        return None, "Failed to fetch user from GitHub"

    data = response.json()
    return {
        "github_id": str(data["id"]),
        "username": data["login"],
        "email": data.get("email") or "",
        "avatar_url": data.get("avatar_url") or "",
    }, None


def get_or_create_user(github_user_data: dict) -> User:
    """
    Find existing user by github_id, or create a new one.
    Updates login timestamp every time.
    First user to log in becomes admin automatically.
    """
    user, created = User.objects.get_or_create(
        github_id=github_user_data["github_id"],
        defaults={
            "username": github_user_data["username"],
            "email": github_user_data["email"],
            "avatar_url": github_user_data["avatar_url"],
            "role": "admin" if User.objects.count() == 0 else "analyst",
        },
    )

    if not created:
        # Update info in case they changed their GitHub profile
        user.username = github_user_data["username"]
        user.email = github_user_data["email"]
        user.avatar_url = github_user_data["avatar_url"]

    user.last_login_at = timezone.now()
    user.save()

    return user


def issue_tokens(user: User) -> dict:
    """
    Generate both access and refresh tokens for a user.
    Returns a dict with both tokens.
    """
    return {
        "access_token": generate_access_token(user),
        "refresh_token": generate_refresh_token(user),
    }
