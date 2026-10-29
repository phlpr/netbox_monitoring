from io import StringIO
from urllib.parse import parse_qs, urlsplit

from dcim.forms import SiteForm
from dcim.models import Interface, Platform, Rack, Site
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from extras.models import CustomField
from ipam.models import IPAddress
from rest_framework.test import APIClient

from netbox_monitoring.assets import asset_config_url
from netbox_monitoring.models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)
from netbox_monitoring.monitoring_forms import (
    MonitoringAssetOverrideImportForm,
    MonitoringProfileForm,
    MonitoringProfileImportForm,
)
from netbox_monitoring.monitoring_schema import PROFILE_FIELD

from .base import MonitoringTestCase
from .test_integration import api_url


class MonitoringObjectTypeTests(MonitoringTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def make_site(self):
        self.profile.object_types.add(ContentType.objects.get_for_model(Site))
        site = Site.objects.create(name="Monitored site", slug="monitored-site")
        self.assign(site)
        return site

    def assign(self, asset, profile=None):
        return MonitoringProfileAssignment.objects.create(
            profile=profile or self.profile,
            assigned_object_type=ContentType.objects.get_for_model(asset),
            assigned_object_id=asset.pk,
        )

    def test_native_choices_include_more_object_types_and_exclude_internal_configuration(self):
        form = MonitoringProfileForm()
        ids = set(form.fields["object_types"].queryset.values_list("pk", flat=True))
        for model in (Site, Rack, Interface, IPAddress):
            self.assertIn(ContentType.objects.get_for_model(model).pk, ids)
        for model in (get_user_model(), MonitoringProfile, MonitoringCheckKey, MonitoringAssetOverride):
            self.assertNotIn(ContentType.objects.get_for_model(model).pk, ids)
        # Offering more choices does not silently broaden a new profile's scope.
        self.assertEqual(set(form.initial["object_types"]), set(self.profile.object_types.values_list("pk", flat=True)))
        form = MonitoringProfileImportForm(
            data={"name": "Imported network profile", "status": "active", "object_types": "dcim.site,ipam.ipaddress"}
        )
        self.assertTrue(form.is_valid(), form.errors)
        imported = form.save()
        self.assertEqual(set(imported.object_types.values_list("model", flat=True)), {"site", "ipaddress"})
        override_field = MonitoringAssetOverrideImportForm().fields["assigned_object_type"]
        self.assertIs(override_field.clean("dcim.site").model_class(), Site)
        with self.assertRaises(ValidationError):
            override_field.clean("users.user")

    def test_profile_api_accepts_new_types_and_native_site_assignment(self):
        response = self.api.post(
            api_url("monitoringprofile"),
            {"name": "Site profile", "object_types": ["dcim.site"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        site = Site.objects.create(name="API site", slug="api-site")
        self.assertNotIn("cf_monitoring_profile", SiteForm(instance=site).fields)
        response = self.api.post(
            api_url("monitoringprofileassignment"),
            {"profile": response.data["id"], "assigned_object_type": "dcim.site", "assigned_object_id": site.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.api.get(asset_config_url(site)).status_code, 200)

    def test_platform_filter_only_applies_to_models_with_a_platform(self):
        site = self.make_site()
        profile = MonitoringProfile.objects.create(
            name="Platform-specific site profile", platform=Platform.objects.create(name="Router OS", slug="router-os")
        )
        profile.object_types.add(ContentType.objects.get_for_model(Site))
        self.assertTrue(profile.accepts(site))
        self.assertFalse(profile.accepts(self.device))
        self.assign(site, profile)

    def test_sites_and_ip_addresses_have_complete_config_tabs_discovery_and_exceptions(self):
        site = self.make_site()
        self.profile.object_types.add(ContentType.objects.get_for_model(IPAddress))
        address = IPAddress.objects.create(address="192.0.2.9/32")
        self.assign(address)
        self.client.force_login(self.admin)
        for asset, namespace in ((site, "dcim:site_monitoring"), (address, "ipam:ipaddress_monitoring")):
            with self.subTest(asset=asset):
                response = self.api.post(
                    api_url("monitoringassetoverride"),
                    {
                        "profile": self.profile.pk,
                        "rule": self.rule.pk,
                        "key": self.rule.key_id,
                        "assigned_object_type": asset._meta.label_lower,
                        "assigned_object_id": asset.pk,
                        "operation": "change",
                        "parameters": {"warning": 85},
                        "reason": "Site/network exception",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 201, response.data)
                response = self.api.get(asset_config_url(asset))
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["checks"][0]["parameters"]["warning"], 85)
                response = self.client.get(reverse(namespace, args=[asset.pk]))
                self.assertContains(response, "Add asset Exception")
                link = response.context["exception_add_url"]
                self.assertEqual(parse_qs(urlsplit(link).query)["return_url"], [reverse(namespace, args=[asset.pk])])
                self.assertEqual(self.client.get(link).status_code, 200)
        response = self.api.get(reverse("plugins-api:netbox_monitoring-api:monitored-assets"))
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(self.api.get(api_url("monitoringassetoverride")).data["count"], 2)
        address.delete()
        self.assertEqual(MonitoringAssetOverride.objects.count(), 1)

    def test_new_object_types_enforce_scope_status_and_profile_deletion_protection(self):
        site = self.make_site()
        with self.assertRaises(ValidationError), transaction.atomic():
            self.profile.object_types.remove(ContentType.objects.get_for_model(Site))
        self.profile.status = "disabled"
        self.profile.save()
        site.full_clean()
        site.save()
        with self.assertRaises(ValidationError):
            self.assign(Site.objects.create(name="New site", slug="new-site"))
        isolated = MonitoringProfile.objects.create(name="Site only")
        isolated.object_types.set([ContentType.objects.get_for_model(Site)])
        self.assign(site, isolated)
        with self.assertRaises(ProtectedError):
            isolated.delete()

    def test_new_object_types_obey_native_object_permissions(self):
        site = self.make_site()
        hidden = Site.objects.create(name="Hidden site", slug="hidden-site")
        self.assign(hidden)
        reader = self.user_with_permissions(
            "site-reader",
            (
                MonitoringProfile,
                MonitoringProfileAssignment,
                MonitoringCheckKey,
                MonitoringCheckRule,
                MonitoringAssetOverride,
            ),
        )
        site_reader = self.user_with_permissions("one-site", (Site,), constraints={"pk": site.pk})
        site_reader.object_permissions.first().users.add(reader)
        self.api.force_authenticate(reader)
        self.assertEqual(self.api.get(asset_config_url(site)).status_code, 200)
        self.assertEqual(self.api.get(asset_config_url(hidden)).status_code, 404)
        response = self.api.get(reverse("plugins-api:netbox_monitoring-api:monitored-assets"))
        self.assertEqual(
            [(item["object_type"], item["id"]) for item in response.data["results"]], [("dcim.site", site.pk)]
        )
        self.make_override(assigned_object_type=ContentType.objects.get_for_model(site), assigned_object_id=site.pk)
        self.make_override(assigned_object_type=ContentType.objects.get_for_model(hidden), assigned_object_id=hidden.pk)
        self.assertEqual(self.api.get(api_url("monitoringassetoverride")).data["count"], 1)

    def test_unsupported_model_types_cannot_be_assigned_or_exported(self):
        for object_type in ("users.user", "netbox_monitoring.monitoringprofile", "missing.model", "invalid"):
            response = self.api.get(
                reverse("plugins-api:netbox_monitoring-api:asset-config", kwargs={"object_type": object_type, "pk": 1})
            )
            self.assertEqual(response.status_code, 404)
        response = self.api.patch(
            api_url("monitoringprofile", "detail", self.profile.pk),
            {"object_types": ["users.user"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)

    def test_deprecated_setup_preserves_assignments_without_native_custom_fields(self):
        before = list(MonitoringProfileAssignment.objects.values())
        call_command("setup_monitoring_fields", apply=True, stdout=StringIO())
        self.assertFalse(CustomField.objects.filter(name=PROFILE_FIELD).exists())
        self.assertEqual(list(MonitoringProfileAssignment.objects.values()), before)
