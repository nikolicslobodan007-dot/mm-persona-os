"""manage.py brauzer --url <URL> — test browser-render preko Gateway-a.

Koristi Lightpanda pool ako je `LIGHTPANDA_CDP` podešen, inače lokalni Chromium
(fallback). Traži Playwright (pokretati gde je instaliran, npr. worker_browser).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.memory.sakupljanje import brauzer


class Command(BaseCommand):
    help = "Test browser-render (Gateway): Lightpanda pool (CDP) ili lokalni Chromium."

    def add_arguments(self, p):
        p.add_argument("--url", required=True, help="URL za render.")
        p.add_argument("--suvo", action="store_true", help="Bez mreže (proba).")

    def handle(self, *args, **o):
        try:
            r = brauzer.render(o["url"], suvo=o["suvo"])
        except brauzer.BrauzerGreska as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(
            f"engine={r['engine']} | {len(r['tekst'])} znakova | "
            f"naslov: {r['naslov'][:80]}"))
