"""
Reproducible before/after benchmarks for the SOLUTION.md table.

Usage:
    python manage.py benchmark               # run all scenarios
    python manage.py benchmark --runs 20     # more samples for tighter p95
    python manage.py benchmark --no-cache    # skip the cached-hit measurements

Each scenario runs three modes for a representative query:
  1. Cold DB    — cache cleared, query hits Postgres
  2. Warm cache — second identical request, served from cache
  3. Variant    — semantically equivalent query expressed differently
                  (proves normalization shares the cached entry)
"""

import statistics
import time

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.test import RequestFactory

from profiles.models import Profile
from profiles.views import ProfileListCreateView, ProfileSearchView
from profiles.query_cache import bump_version
from users.models import User


SCENARIOS = [
    {
        "name": "list / no filter",
        "view": "list",
        "params": {},
    },
    {
        "name": "list / gender=male",
        "view": "list",
        "params": {"gender": "male"},
    },
    {
        "name": "list / country=NG, gender=female, min_age=18, max_age=35",
        "view": "list",
        "params": {
            "country_id": "NG",
            "gender": "female",
            "min_age": "18",
            "max_age": "35",
        },
    },
    {
        "name": "search / 'young males from nigeria'",
        "view": "search",
        "params": {"q": "young males from nigeria"},
        "variant_params": {"q": "men from nigeria younger than 25"},
    },
]


class Command(BaseCommand):
    help = "Benchmark profile list / search latency"

    def add_arguments(self, parser):
        parser.add_argument("--runs", type=int, default=10)
        parser.add_argument("--no-cache", action="store_true")

    def _get_admin_user(self):
        return User.objects.filter(role="admin").first() or User.objects.first()

    def _make_request(self, path, params, user):
        factory = RequestFactory()
        request = factory.get(path, params, HTTP_X_API_VERSION="1")
        request.user = user
        return request

    def _time_call(self, view_method, request, runs):
        samples = []
        for _ in range(runs):
            t0 = time.perf_counter()
            view_method(request)
            samples.append((time.perf_counter() - t0) * 1000.0)
        return samples

    def _stats(self, samples):
        return {
            "p50": statistics.median(samples),
            "p95": statistics.quantiles(samples, n=20)[18]
            if len(samples) >= 20
            else max(samples),
            "min": min(samples),
            "mean": statistics.mean(samples),
        }

    def handle(self, *args, **opts):
        runs = opts["runs"]
        skip_cache = opts["no_cache"]

        total = Profile.objects.count()
        admin = self._get_admin_user()
        if admin is None:
            self.stdout.write(self.style.ERROR("Need at least one user in DB"))
            return

        self.stdout.write(self.style.NOTICE(f"Profiles in DB: {total}"))
        self.stdout.write(self.style.NOTICE(f"Runs per measurement: {runs}\n"))

        list_view = ProfileListCreateView()
        search_view = ProfileSearchView()

        for s in SCENARIOS:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n● {s['name']}"))

            if s["view"] == "list":
                path = "/api/profiles"
                view_get = list_view.get
            else:
                path = "/api/profiles/search"
                view_get = search_view.get

            # Cold DB — clear cache so every request hits Postgres
            cache.clear()
            bump_version()
            req = self._make_request(path, s["params"], admin)
            cold = self._time_call(view_get, req, runs)
            self._print_row("cold (DB)", cold)

            if not skip_cache:
                # Warm cache — second pass, identical query
                req = self._make_request(path, s["params"], admin)
                warm = self._time_call(view_get, req, runs)
                self._print_row("warm (cache)", warm)

                # Variant query — same intent, different expression
                if "variant_params" in s:
                    req = self._make_request(path, s["variant_params"], admin)
                    variant = self._time_call(view_get, req, runs)
                    self._print_row("variant (cache)", variant)

    def _print_row(self, label, samples):
        st = self._stats(samples)
        self.stdout.write(
            f"  {label:<18}  p50={st['p50']:7.2f}ms  "
            f"p95={st['p95']:7.2f}ms  min={st['min']:7.2f}ms  "
            f"mean={st['mean']:7.2f}ms"
        )
