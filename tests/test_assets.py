from urllib.parse import parse_qs, urlsplit

from django.urls import reverse
from rest_framework.test import APIClient
from virtualization.models import VirtualMachine

from netbox_monitoring.assets import asset_config_url
from netbox_monitoring.models import MonitoringAssetOverride, MonitoringCheckKey, MonitoringCheckRule, MonitoringProfile
from netbox_monitoring.monitoring_schema import PROFILE_FIELD

from .base import MonitoringTestCase


class MonitoredAssetTests(MonitoringTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def test_one_call_config_is_complete_for_devices_and_vms(self):
        self.make_override()
        for asset in (self.vm, self.device):
            response = self.api.get(asset_config_url(asset))
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["asset"]["id"], asset.pk)
            self.assertEqual(response.data["checks"][0]["key"], "disk.all")
            self.assertEqual(response.data["checks"][0]["parameters"]["warning"], 85 if asset == self.vm else 80)
            self.assertEqual(len(response.data["config_hash"]), 64)

    def test_discovery_includes_only_configured_visible_assets_and_direct_urls(self):
        none = VirtualMachine.objects.create(name="no-monitoring", site=self.vm.site)
        null = VirtualMachine.objects.create(
            name="null-monitoring", site=self.vm.site, custom_field_data={PROFILE_FIELD: None}
        )
        url = reverse("plugins-api:netbox_monitoring-api:monitored-assets")
        response = self.api.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 3)
        for item in response.data["results"]:
            self.assertEqual(self.api.get(item["config_url"]).status_code, 200)
        self.assertEqual(self.api.get(asset_config_url(none)).status_code, 404)
        self.assertEqual(self.api.get(asset_config_url(null)).status_code, 404)
        self.profile.status = "disabled"
        self.profile.save()
        self.assertEqual(self.api.get(url).data["count"], 3)
        self.assertEqual(self.api.get(asset_config_url(self.vm)).status_code, 200)
        response = self.api.get(url, {"limit": 1, "offset": 1})
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNotNone(response.data["previous"])

    def test_config_requires_all_related_permissions_and_authentication(self):
        reader = self.user_with_permissions("asset-discovery", (VirtualMachine, MonitoringProfile))
        self.api.force_authenticate(reader)
        response = self.api.get(reverse("plugins-api:netbox_monitoring-api:monitored-assets"))
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(self.api.get(asset_config_url(self.vm)).status_code, 403)
        self.assertEqual(self.api.get(asset_config_url(self.device)).status_code, 404)
        self.api.force_authenticate(user=None)
        self.assertIn(self.api.get(asset_config_url(self.vm)).status_code, (401, 403))

    def test_asset_exception_button_prefills_asset_and_profile(self):
        self.client.force_login(self.admin)
        for namespace, asset in (
            ("dcim:device_monitoring", self.device),
            ("virtualization:virtualmachine_monitoring", self.vm),
        ):
            response = self.client.get(reverse(namespace, args=[asset.pk]))
            self.assertContains(response, "Add asset Exception")
            self.assertContains(response, asset_config_url(asset))
            link = response.context["exception_add_url"]
            query = parse_qs(urlsplit(link).query)
            self.assertEqual(query["assigned_object_id"], [str(asset.pk)])
            self.assertEqual(query["profile"], [str(self.profile.pk)])
            form_response = self.client.get(link)
            self.assertEqual(form_response.status_code, 200)
            self.assertEqual(str(form_response.context["form"].initial["assigned_object_id"]), str(asset.pk))
        reader = self.user_with_permissions(
            "read-only-tab",
            (
                VirtualMachine,
                MonitoringProfile,
                MonitoringCheckKey,
                MonitoringCheckRule,
                MonitoringAssetOverride,
            ),
        )
        self.client.force_login(reader)
        response = self.client.get(reverse("virtualization:virtualmachine_monitoring", args=[self.vm.pk]))
        self.assertNotContains(response, "Add asset Exception")
