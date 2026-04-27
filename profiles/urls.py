from django.urls import path
from .views import (
    ProfileListCreateView,
    ProfileDetailView,
    ProfileSearchView,
    ProfileExportView,
)

urlpatterns = [
    path("profiles/search", ProfileSearchView.as_view(), name="profile-search"),
    path("profiles/export", ProfileExportView.as_view(), name="profile-export"),
    path("profiles", ProfileListCreateView.as_view(), name="profile-list-create"),
    path("profiles/<uuid:pk>", ProfileDetailView.as_view(), name="profile-detail"),
]
