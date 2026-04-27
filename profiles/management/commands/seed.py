import json
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from profiles.models import Profile
from uuid6 import uuid7


class Command(BaseCommand):
    help = "Seed the database with 2026 profiles from seed_profiles.json"

    def handle(self, *args, **kwargs):
        seed_file = os.path.join(settings.BASE_DIR, "seed_profiles.json")

        if not os.path.exists(seed_file):
            self.stdout.write(
                self.style.ERROR(f"seed_profiles.json not found at {seed_file}")
            )
            return

        with open(seed_file, "r") as f:
            data = json.load(f)

        profiles = data.get("profiles", [])

        # Fetch all names that already exist in one single DB query
        existing_names = set(Profile.objects.values_list("name", flat=True))

        # Build list of Profile objects to insert — skip existing ones
        to_create = []
        for item in profiles:
            if item["name"] not in existing_names:
                to_create.append(
                    Profile(
                        id=uuid7(),
                        name=item["name"],
                        gender=item["gender"],
                        gender_probability=item["gender_probability"],
                        age=item["age"],
                        age_group=item["age_group"],
                        country_id=item["country_id"],
                        country_name=item["country_name"],
                        country_probability=item["country_probability"],
                        sample_size=0,
                    )
                )

        if not to_create:
            self.stdout.write(
                self.style.WARNING("No new profiles to insert. All already exist.")
            )
            return

        # Insert all records in one single database trip
        Profile.objects.bulk_create(to_create, batch_size=500)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeding complete. Created: {len(to_create)} | "
                f"Skipped (already exist): {len(profiles) - len(to_create)}"
            )
        )
