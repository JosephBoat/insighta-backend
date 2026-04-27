from django.db import models
from uuid6 import uuid7


class User(models.Model):
    ROLE_CHOICES = [
        ("admin", "Admin"),
        ("analyst", "Analyst"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    github_id = models.CharField(max_length=255, unique=True)
    username = models.CharField(max_length=255)
    email = models.CharField(max_length=255, blank=True, default="")
    avatar_url = models.CharField(max_length=500, blank=True, default="")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="analyst")
    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.username


class RefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token = models.CharField(max_length=500, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "refresh_tokens"

    def __str__(self):
        return f"RefreshToken for {self.user.username}"
