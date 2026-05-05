# Stage 4B optimization: add btree indexes on every column we filter on.
# Composite indexes cover the most common multi-column filter patterns.
# AddIndex / AlterField are non-blocking on Postgres (CREATE INDEX
# CONCURRENTLY would be ideal but Django's AddIndex doesn't support it
# without a manual RunSQL — fine for the current dataset size).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("profiles", "0002_profile_country_name_alter_profile_sample_size"),
    ]

    operations = [
        migrations.AlterField(
            model_name="profile",
            name="gender",
            field=models.CharField(db_index=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="profile",
            name="age",
            field=models.IntegerField(db_index=True),
        ),
        migrations.AlterField(
            model_name="profile",
            name="age_group",
            field=models.CharField(db_index=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="profile",
            name="country_id",
            field=models.CharField(db_index=True, max_length=10),
        ),
        migrations.AlterField(
            model_name="profile",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
        migrations.AddIndex(
            model_name="profile",
            index=models.Index(
                fields=["country_id", "gender", "age"],
                name="profile_country_gender_age_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="profile",
            index=models.Index(
                fields=["gender", "age_group"],
                name="profile_gender_age_group_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="profile",
            index=models.Index(
                fields=["age_group", "country_id"],
                name="profile_age_group_country_idx",
            ),
        ),
    ]
