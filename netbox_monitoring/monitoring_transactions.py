"""Serialize configuration writes, including composition across several profiles."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db import connections, transaction

asset_cleanup = ContextVar("monitoring_asset_cleanup", default=False)


@contextmanager
def configuration_write(using=None):
    using = using or "default"
    with transaction.atomic(using=using):
        # One transaction-scoped namespace for the small configuration catalogue.
        # A shared lock order avoids deadlocks between multi-profile assets.
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [0x4E424D4F, 0])
        yield
