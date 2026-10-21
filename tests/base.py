from copy import deepcopy
from io import StringIO

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from users.models import ObjectPermission
from virtualization.models import VirtualMachine

from netbox_monitoring.models import MonitoringAssetOverride, MonitoringCheckRule, MonitoringProfile
from netbox_monitoring.monitoring_schema import DEFAULTS, PROFILE_FIELD


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class MonitoringTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("setup_monitoring_fields", apply=True, stdout=StringIO())
        cls.admin = get_user_model().objects.create_superuser(username="monitoring-admin")
        cls.profile = MonitoringProfile.objects.create(name="Linux Standard")
        cls.rule = MonitoringCheckRule.objects.create(
            profile=cls.profile,
            key="disk.all",
            check_type="disk",
            target="*",
            parameters=deepcopy(DEFAULTS["disk"]),
        )
        site = Site.objects.create(name="Test site", slug="monitoring-test")
        cls.vm = VirtualMachine.objects.create(
            name="vm-a", site=site, custom_field_data={PROFILE_FIELD: cls.profile.pk}
        )
        cls.vm_b = VirtualMachine.objects.create(
            name="vm-b", site=site, custom_field_data={PROFILE_FIELD: cls.profile.pk}
        )
        role = DeviceRole.objects.create(name="Test role", slug="monitoring-test")
        manufacturer = Manufacturer.objects.create(name="Test vendor", slug="monitoring-test")
        device_type = DeviceType.objects.create(model="Test model", slug="monitoring-test", manufacturer=manufacturer)
        cls.device = Device.objects.create(
            name="device-a",
            site=site,
            role=role,
            device_type=device_type,
            custom_field_data={PROFILE_FIELD: cls.profile.pk},
        )

    def setUp(self):
        cache.clear()

    def make_override(self, **kwargs):
        values = {
            "profile": self.profile,
            "assigned_object_type": ContentType.objects.get_for_model(self.vm),
            "assigned_object_id": self.vm.pk,
            "rule": self.rule,
            "key": self.rule.key,
            "operation": "change",
            "parameters": {"warning": 85},
            "reason": "Temporary capacity exception",
        }
        return MonitoringAssetOverride.objects.create(**(values | kwargs))

    def user_with_permissions(self, name, models, actions=("view",), constraints=None):
        user = get_user_model().objects.create_user(username=name)
        permission = ObjectPermission.objects.create(name=name, actions=list(actions), constraints=constraints)
        permission.object_types.set(ContentType.objects.get_for_model(model) for model in models)
        permission.users.add(user)
        return user
