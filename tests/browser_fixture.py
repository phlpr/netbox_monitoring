"""Disposable fixtures for tests/browser/monitoring.cjs; test databases only."""

import json
import os
from importlib import import_module
from io import StringIO
from pathlib import Path
from uuid import uuid4

from dcim.models import Site
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.core.management import call_command
from virtualization.models import VirtualMachine

from netbox_monitoring.models import MonitoringCheckKey, MonitoringCheckRule, MonitoringProfile
from netbox_monitoring.monitoring_schema import DEFAULTS, PROFILE_FIELD


def state_path():
    assert settings.DATABASES["default"]["NAME"].startswith("test_netbox_monitoring_")
    return Path(os.environ["MONITORING_BROWSER_STATE"])


def prepare():
    path = state_path()
    assert not path.exists(), "Clean up the previous browser fixture first."
    call_command("setup_monitoring_fields", apply=True, stdout=StringIO())
    marker = uuid4().hex[:10]
    user = get_user_model().objects.create_superuser(username=f"monitoring-browser-{marker}")
    site = Site.objects.create(name=f"Monitoring browser {marker}", slug=f"monitoring-browser-{marker}")
    profile = MonitoringProfile.objects.create(name=f"Monitoring browser {marker}")
    vm = VirtualMachine.objects.create(
        name=f"monitoring-browser-{marker}", site=site, custom_field_data={PROFILE_FIELD: profile.pk}
    )
    disk = MonitoringCheckKey.objects.create(name=f"browser.{marker}.disk", check_type="disk")
    cpu = MonitoringCheckKey.objects.create(name=f"browser.{marker}.cpu", check_type="cpu")
    rule = MonitoringCheckRule.objects.create(profile=profile, key=disk, target="*", parameters=DEFAULTS["disk"])
    session = import_module(settings.SESSION_ENGINE).SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = "netbox.authentication.ObjectPermissionBackend"
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.set_expiry(600)
    session.save()
    data = {
        "base_url": os.environ.get("MONITORING_BROWSER_URL", "http://127.0.0.1:8026"),
        "user_id": user.pk,
        "username": user.username,
        "site_id": site.pk,
        "profile_id": profile.pk,
        "vm_id": vm.pk,
        "disk_key_id": disk.pk,
        "disk_key_name": disk.name,
        "cpu_key_id": cpu.pk,
        "cpu_key_name": cpu.name,
        "rule_id": rule.pk,
        "cookie": {
            "name": settings.SESSION_COOKIE_NAME,
            "value": session.session_key,
            "domain": "127.0.0.1",
            "path": "/",
        },
    }
    with path.open("x") as handle:
        path.chmod(0o600)
        json.dump(data, handle)
    print("Disposable browser fixture prepared; private state:", path)


def cleanup():
    path = state_path()
    data = json.loads(path.read_text())
    assert data["username"].startswith("monitoring-browser-")
    import_module(settings.SESSION_ENGINE).SessionStore(session_key=data["cookie"]["value"]).delete()
    VirtualMachine.objects.get(pk=data["vm_id"], name=data["username"]).delete()
    MonitoringCheckRule.objects.get(pk=data["rule_id"]).delete()
    MonitoringProfile.objects.get(pk=data["profile_id"]).delete()
    MonitoringCheckKey.objects.filter(pk__in=[data["disk_key_id"], data["cpu_key_id"]]).delete()
    Site.objects.get(pk=data["site_id"]).delete()
    get_user_model().objects.get(pk=data["user_id"], username=data["username"]).delete()
    path.unlink()
    print("Disposable browser account, session, and monitoring fixtures removed.")
