"""Compatibility command for installations upgrading from the profile selector."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Deprecated: monitoring assignments are plugin models; run migrate instead."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Retained for compatibility; no custom fields are created."
        )

    def handle(self, *args, **options):
        self.stdout.write("No custom fields are needed. Run migrate and use the Monitoring profiles card.")
