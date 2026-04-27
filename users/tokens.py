import jwt
import uuid
from datetime import datetime, timezone, timedelta
from django.conf import settings
from .models import RefreshToken


def generate_access_token(user) -> str:
    """
    Creates a short-lived access token (3 minutes).
    Access tokens are stateless — validated by signature only, not stored in DB.
    They contain the user's id and role so we don't need a DB lookup on every request.
    """
    payload = {
        "user_id": str(user.id),
        "username": user.username,
        "role": user.role,
        "type": "access",
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRY_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def generate_refresh_token(user) -> str:
    """
    Creates a refresh token and stores it in the database.
    Refresh tokens are stateful — stored in DB so they can be invalidated on logout.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.REFRESH_TOKEN_EXPIRY_MINUTES
    )
    # Generate a random token value
    token_value = str(uuid.uuid4()) + str(uuid.uuid4())

    RefreshToken.objects.create(
        user=user,
        token=token_value,
        expires_at=expires_at,
    )
    return token_value


def validate_access_token(token: str) -> dict | None:
    """
    Validates an access token and returns its payload.
    Returns None if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
