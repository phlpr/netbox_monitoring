from copy import deepcopy

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase, override_settings
from users.models import ObjectPermission
from virtualization.models import VirtualMachine

from netbox_monitoring.models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)
from netbox_monitoring.monitoring_schema import DEFAULTS


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class MonitoringTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(username="monitoring-admin")
        cls.profile = MonitoringProfile.objects.create(name="Linux Standard")
        cls.check_key = MonitoringCheckKey.objects.create(name="disk.all", check_type="disk")
        cls.rule = MonitoringCheckRule.objects.create(
            profile=cls.profile,
            key=cls.check_key,
            target="*",
            parameters=deepcopy(DEFAULTS["disk"]),
        )
        site = Site.objects.create(name="Test site", slug="monitoring-test")
        cls.vm = VirtualMachine.objects.create(name="vm-a", site=site)
        cls.vm_b = VirtualMachine.objects.create(name="vm-b", site=site)
        role = DeviceRole.objects.create(name="Test role", slug="monitoring-test")
        manufacturer = Manufacturer.objects.create(name="Test vendor", slug="monitoring-test")
        device_type = DeviceType.objects.create(model="Test model", slug="monitoring-test", manufacturer=manufacturer)
        cls.device = Device.objects.create(
            name="device-a",
            site=site,
            role=role,
            device_type=device_type,
        )

        for asset in (cls.vm, cls.vm_b, cls.device):
            assignment = MonitoringProfileAssignment.objects.create(
                profile=cls.profile,
                assigned_object_type=ContentType.objects.get_for_model(asset),
                assigned_object_id=asset.pk,
            )
            if asset == cls.vm:
                cls.assignment = assignment

    def setUp(self):
        cache.clear()

    def make_override(self, **kwargs):
        values = {
            "assigned_object_type": ContentType.objects.get_for_model(self.vm),
            "assigned_object_id": self.vm.pk,
            "key": self.rule.key,
            "operation": "change",
            "parameters": {"warning": 85},
            "reason": "Temporary capacity exception",
        }
        kind = kwargs.pop("check_type", None)
        if isinstance(kwargs.get("key"), str):
            kwargs["key"], _ = MonitoringCheckKey.objects.get_or_create(
                name=kwargs["key"], defaults={"check_type": kind or "disk"}
            )
        return MonitoringAssetOverride.objects.create(**(values | kwargs))

    def user_with_permissions(self, name, models, actions=("view",), constraints=None):
        user = get_user_model().objects.create_user(username=name)
        permission = ObjectPermission.objects.create(name=name, actions=list(actions), constraints=constraints)
        permission.object_types.set(ContentType.objects.get_for_model(model) for model in models)
        permission.users.add(user)
        return user
