from rest_framework.response import Response
from rest_framework import status
from users.middleware import get_user_from_request


def require_auth(func):
    """
    Decorator that requires a valid access token.
    Attaches the user to the request object.
    Returns 401 if not authenticated.
    """

    def wrapper(self, request, *args, **kwargs):
        user, error = get_user_from_request(request)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        request.user = user
        return func(self, request, *args, **kwargs)

    return wrapper


def require_admin(func):
    """
    Decorator that requires admin role.
    Returns 403 if user is not an admin.
    Always runs after require_auth.
    """

    def wrapper(self, request, *args, **kwargs):
        user, error = get_user_from_request(request)
        if error:
            return Response(
                {"status": "error", "message": error},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if user.role != "admin":
            return Response(
                {"status": "error", "message": "Admin access required"},
                status=status.HTTP_403_FORBIDDEN,
            )
        request.user = user
        return func(self, request, *args, **kwargs)

    return wrapper


def require_api_version(func):
    """
    Decorator that requires the X-API-Version: 1 header.
    Returns 400 if header is missing.
    Required on all /api/* endpoints per the TRD.
    """

    def wrapper(self, request, *args, **kwargs):
        api_version = request.headers.get("X-API-Version")
        if request.path.startswith("/api/v1/"):
            return func(self, request, *args, **kwargs)
        if api_version != "1":
            return Response(
                {"status": "error", "message": "API version header required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return func(self, request, *args, **kwargs)

    return wrapper
