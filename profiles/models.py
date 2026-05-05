from django.db import models
from uuid6 import uuid7


class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    name = models.CharField(max_length=255, unique=True)
    gender = models.CharField(max_length=50, db_index=True)
    gender_probability = models.FloatField()
    age = models.IntegerField(db_index=True)
    age_group = models.CharField(max_length=50, db_index=True)
    country_id = models.CharField(max_length=10, db_index=True)
    country_name = models.CharField(max_length=255, default="")
    country_probability = models.FloatField()
    sample_size = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "profiles"
        indexes = [
            # Composite indexes for the most common filter combinations.
            # Postgres can use a multi-column btree index for queries that
            # filter on a leading prefix of the columns, so ordering matters:
            # high-selectivity columns first.
            models.Index(
                fields=["country_id", "gender", "age"],
                name="profile_country_gender_age_idx",
            ),
            models.Index(
                fields=["gender", "age_group"],
                name="profile_gender_age_group_idx",
            ),
            models.Index(
                fields=["age_group", "country_id"],
                name="profile_age_group_country_idx",
            ),
        ]

    def __str__(self):
        return self.name
