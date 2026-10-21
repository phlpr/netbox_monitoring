"""Isolated PostgreSQL configuration for native NetBox integration tests.

MONITORING_BASE_CONFIGURATION may name a local NetBox configuration.py. Only
connection settings are reused; the plugin list, database, and Redis databases
are isolated from the running installation.
"""

import os
import runpy
from copy import deepcopy

from netbox.configuration_testing import *  # noqa: F403

if os.environ.get("MONITORING_BASE_CONFIGURATION"):
    _base = runpy.run_path(os.environ["MONITORING_BASE_CONFIGURATION"])
    DATABASES = deepcopy(_base.get("DATABASES") or {"default": _base["DATABASE"]})
    REDIS = deepcopy(_base["REDIS"])
else:
    DATABASES = deepcopy(DATABASES)  # noqa: F405
    REDIS = deepcopy(REDIS)  # noqa: F405

DATABASES["default"]["NAME"] = "test_netbox_monitoring"
DATABASES["default"]["TEST"] = {"NAME": "test_netbox_monitoring"}
for _kind, _database in (("tasks", 12), ("caching", 13)):
    REDIS[_kind]["DATABASE"] = _database
    REDIS[_kind].pop("URL", None)

PLUGINS = ["netbox_monitoring"]
PLUGINS_CONFIG = {"netbox_monitoring": {}}
RELEASE_CHECK_URL = None
DEFAULT_PERMISSIONS = {}
PASSWORD_VALIDATORS = []
DEVELOPER = True
