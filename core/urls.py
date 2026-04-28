from django.urls import path, include
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator

urlpatterns = [
    path("auth/", include("users.urls")),
    path("api/", include("profiles.urls")),
    path("api/users/", include("users.api_urls")),
]
