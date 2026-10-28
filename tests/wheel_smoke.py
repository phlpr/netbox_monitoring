"""Smoke-test an installed wheel in an isolated NetBox test database."""

import json
from copy import deepcopy
from importlib.metadata import distribution
from pathlib import Path
from uuid import uuid4

from dcim.models import Site
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.urls import reverse
from extras.models import CustomField
from rest_framework.test import APIClient
from virtualization.models import VirtualMachine

import netbox_monitoring
from netbox_monitoring.assets import asset_config_url, asset_object_types
from netbox_monitoring.models import MonitoringAssetOverride, MonitoringCheckKey, MonitoringCheckRule, MonitoringProfile
from netbox_monitoring.monitoring_schema import DEFAULTS, PROFILE_FIELD


def verify_install():
    info = distribution("netbox-monitoring")
    assert (
        Path(netbox_monitoring.__file__).resolve() == Path(info.locate_file("netbox_monitoring/__init__.py")).resolve()
    ), "The source checkout is shadowing the installed wheel."
    direct = json.loads(info.read_text("direct_url.json") or "{}")
    assert not direct.get("dir_info", {}).get("editable"), "An editable installation is not a wheel test."
    assert info.version == netbox_monitoring.__version__
    assert settings.DATABASES["default"]["NAME"].startswith("test_netbox_monitoring"), "Use an isolated test database."
    field = CustomField.objects.get(name=PROFILE_FIELD)
    assert set(field.object_types.values_list("pk", flat=True)) >= set(
        asset_object_types().values_list("pk", flat=True)
    )
    with transaction.atomic():
        try:
            marker = uuid4().hex[:10]
            user = get_user_model().objects.create_superuser(username=f"wheel-smoke-{marker}")
            profile = MonitoringProfile.objects.create(name=f"Wheel smoke {marker}")
            profile.object_types.add(ContentType.objects.get_for_model(Site))
            key = MonitoringCheckKey.objects.create(name=f"smoke.{marker}.disk", check_type="disk")
            rule = MonitoringCheckRule.objects.create(
                profile=profile, key=key, target="*", parameters=deepcopy(DEFAULTS["disk"])
            )
            vm = VirtualMachine.objects.create(name=f"wheel-{marker}", custom_field_data={PROFILE_FIELD: profile.pk})
            site = Site.objects.create(
                name=f"Wheel {marker}", slug=f"wheel-{marker}", custom_field_data={PROFILE_FIELD: profile.pk}
            )
            MonitoringAssetOverride.objects.create(
                profile=profile,
                rule=rule,
                key=key,
                assigned_object_type=ContentType.objects.get_for_model(vm),
                assigned_object_id=vm.pk,
                operation="change",
                parameters={"warning": 85},
                reason="Release package smoke test",
            )
            client = APIClient()
            client.force_authenticate(user)
            for asset, expected in ((vm, 85), (site, 80)):
                response = client.get(asset_config_url(asset))
                assert response.status_code == 200, response.data
                assert response.data["checks"][0]["parameters"]["warning"] == expected
                assert len(response.data["config_hash"]) == 64
            client.force_login(user)
            for name, asset in (("virtualization:virtualmachine_monitoring", vm), ("dcim:site_monitoring", site)):
                response = client.get(reverse(name, args=[asset.pk]))
                assert response.status_code == 200
                assert b"Add asset Exception" in response.content
            print(
                f"Installed wheel {info.version} passed: selectors, VM/Site config, exception resolution, and UI tabs."
            )
        finally:
            transaction.set_rollback(True)
