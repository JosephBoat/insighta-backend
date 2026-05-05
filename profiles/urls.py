from django.urls import path
from .views import (
    ProfileListCreateView,
    ProfileDetailView,
    ProfileSearchView,
    ProfileExportView,
    ProfileImportView,
)

urlpatterns = [
    path("profiles/search", ProfileSearchView.as_view(), name="profile-search"),
    path("profiles/export", ProfileExportView.as_view(), name="profile-export"),
    path("profiles/import", ProfileImportView.as_view(), name="profile-import"),
    path("profiles", ProfileListCreateView.as_view(), name="profile-list-create"),
    path("profiles/<uuid:pk>", ProfileDetailView.as_view(), name="profile-detail"),
]
