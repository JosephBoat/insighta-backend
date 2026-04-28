from django.urls import path
from .views import WhoAmIView

urlpatterns = [
    path("me", WhoAmIView.as_view(), name="users-me"),
]
