import time
import logging
from .tokens import validate_access_token
from .models import User

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """
    Logs every request: method, endpoint, status code, response time.
    Required by the TRD.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"{request.method} {request.path} "
            f"status={response.status_code} "
            f"time={duration_ms}ms"
        )
        return response


def get_user_from_request(request):
    """
    Extracts and validates the Bearer token from the Authorization header.
    Attaches the user to the request if valid.
    Returns (user, error_message) — one will always be None.
    """
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return None, "Authentication required"

    token = auth_header.split(" ")[1]
    payload = validate_access_token(token)

    if not payload:
        return None, "Invalid or expired token"

    try:
        user = User.objects.get(id=payload["user_id"])
    except User.DoesNotExist:
        return None, "User not found"

    if not user.is_active:
        return None, "Account is inactive"

    return user, None
