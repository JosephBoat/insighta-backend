from django.urls import path
from .views import (
    GithubLoginView,
    GithubCallbackView,
    RefreshTokenView,
    LogoutView,
    WhoAmIView,
    DirectAuthView,
)

urlpatterns = [
    path("github", GithubLoginView.as_view(), name="github-login"),
    path("github/callback", GithubCallbackView.as_view(), name="github-callback"),
    path("refresh", RefreshTokenView.as_view(), name="token-refresh"),
    path("logout", LogoutView.as_view(), name="logout"),
    path("whoami", WhoAmIView.as_view(), name="whoami"),
    path("token", DirectAuthView.as_view(), name="direct-auth"),
]
