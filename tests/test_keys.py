from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from rest_framework.test import APIClient

from netbox_monitoring.models import MonitoringCheckKey
from netbox_monitoring.monitoring_forms import MonitoringCheckRuleForm
from netbox_monitoring.monitoring_resolver import resolve_monitoring
from netbox_monitoring.monitoring_schema import DEFAULTS

from .base import MonitoringTestCase


class MonitoringKeyTests(MonitoringTestCase):
    def test_key_names_are_globally_unique_and_lowercase(self):
        with self.assertRaises(ValidationError):
            MonitoringCheckKey.objects.create(name="disk.all", check_type="disk")
        with self.assertRaises(ValidationError):
            MonitoringCheckKey.objects.create(name="Disk.All", check_type="disk")

    def test_referenced_keys_keep_their_identity_and_type(self):
        with self.assertRaises(ProtectedError):
            self.check_key.delete()
        self.check_key.name = "disk.renamed"
        with self.assertRaises(ValidationError):
            self.check_key.save()
        self.check_key.refresh_from_db()
        self.check_key.check_type = "dns"
        with self.assertRaises(ValidationError):
            self.check_key.save()
        self.check_key.refresh_from_db()
        self.check_key.description = "Filesystem capacity on all discovered mounts"
        self.check_key.save()

    def test_rule_type_is_derived_from_key_and_export_keys_remain_strings(self):
        form = MonitoringCheckRuleForm(instance=self.rule)
        self.assertNotIn("check_type", form.fields)
        self.assertEqual(self.rule.check_type, "disk")
        configuration = resolve_monitoring(self.vm, self.admin)
        self.assertEqual(configuration["checks"][0]["key"], "disk.all")
        self.assertEqual(configuration["checks"][0]["check_type"], "disk")

    def test_key_api_crud_and_rule_lookup(self):
        api = APIClient()
        api.force_authenticate(self.admin)
        keys = reverse("plugins-api:netbox_monitoring-api:monitoringcheckkey-list")
        response = api.post(
            keys, {"name": "cpu.asset", "check_type": "cpu", "description": "Asset CPU usage"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        key_id = response.data["id"]
        self.assertEqual(response.data["default_parameters"], DEFAULTS["cpu"])
        response = api.post(
            reverse("plugins-api:netbox_monitoring-api:monitoringcheckrule-list"),
            {
                "profile": self.profile.pk,
                "key": key_id,
                "parameters": DEFAULTS["cpu"],
                "target": "",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["key"]["name"], "cpu.asset")
        self.assertEqual(response.data["check_type"], "cpu")
        response = api.get(reverse("plugins-api:netbox_monitoring-api:monitoringcheckrule-list"), {"q": "cpu.asset"})
        self.assertEqual(response.data["count"], 1)
