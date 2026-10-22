from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

from core.models import ObjectChange
from dcim.api.serializers import DeviceSerializer
from dcim.forms import DeviceForm
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, override_settings
from django.urls import reverse
from extras.models import CustomField
from rest_framework.test import APIClient
from users.models import Group
from utilities.api import get_serializer_for_model
from virtualization.api.serializers import VirtualMachineSerializer
from virtualization.forms import VirtualMachineForm
from virtualization.models import VirtualMachine

from netbox_monitoring.api.serializers import MonitoringAssetOverrideSerializer, MonitoringProfileSerializer
from netbox_monitoring.models import MonitoringAssetOverride, MonitoringCheckKey, MonitoringCheckRule, MonitoringProfile
from netbox_monitoring.monitoring_forms import MonitoringAssetOverrideForm, MonitoringCheckRuleForm
from netbox_monitoring.monitoring_permissions import MonitoringRequestMiddleware, monitoring_request
from netbox_monitoring.monitoring_schema import DEFAULTS, PROFILE_FIELD

from .base import MonitoringTestCase


def api_url(model, action="list", pk=None):
    return reverse(f"plugins-api:netbox_monitoring-api:{model}-{action}", args=[pk] if pk else None)


def ui_url(model, suffix="_list", pk=None):
    return reverse(f"plugins:netbox_monitoring:{model}{suffix}", args=[pk] if pk else None)


class MonitoringIntegrationTests(MonitoringTestCase):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.client.force_login(self.admin)

    def test_profile_uses_native_status_object_types_and_ownership_section(self):
        response = self.client.get(ui_url("monitoringprofile", "_add"))
        self.assertContains(response, "Ownership")
        self.assertContains(response, "Object type(s)")
        html = response.content.decode()
        self.assertLess(html.index('id="id_owner_group"'), html.index('id="id_owner"'))
        self.assertNotIn('name="selectable"', html)
        self.assertNotIn('name="asset_type"', html)
        response = self.api.get(api_url("monitoringprofile", "detail", self.profile.pk))
        self.assertEqual(response.data["status"], {"value": "active", "label": "Active"})
        self.assertEqual(set(response.data["object_types"]), {"dcim.device", "virtualization.virtualmachine"})

    def test_profile_scope_api_change_cannot_orphan_assigned_assets(self):
        response = self.api.patch(
            api_url("monitoringprofile", "detail", self.profile.pk), {"object_types": ["dcim.device"]}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.profile.object_types.count(), 2)

    def test_object_type_preview_shows_changes_without_saving(self):
        profile = MonitoringProfile.objects.create(name="Unused preview profile")
        response = self.client.post(
            ui_url("monitoringprofile", "_edit", profile.pk),
            {
                "name": profile.name,
                "status": "active",
                "_preview": "1",
                "object_types": [ContentType.objects.get_for_model(self.device).pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(row[0] == "Object types" for row in response.context["changes"]))
        self.assertEqual(profile.object_types.count(), 2)

    def test_native_serializer_discovery_custom_fields_and_event_data(self):
        self.assertIs(get_serializer_for_model(MonitoringProfile), MonitoringProfileSerializer)
        for asset, serializer_type, form_type in (
            (self.vm, VirtualMachineSerializer, VirtualMachineForm),
            (self.device, DeviceSerializer, DeviceForm),
        ):
            with self.subTest(asset=asset):
                form = form_type(instance=asset)
                self.assertIn("cf_monitoring_profile", form.fields)
                serialized = serializer_type(asset, context={"request": None}).data
                self.assertEqual(serialized["custom_fields"][PROFILE_FIELD]["id"], self.profile.pk)
                self.assertEqual(asset.serialize_object()["custom_fields"][PROFILE_FIELD], self.profile.pk)
                asset.snapshot()
                change = asset.to_objectchange("update")
                self.assertEqual(change.postchange_data["custom_fields"][PROFILE_FIELD], self.profile.pk)

    def test_api_crud_impact_effective_and_filters(self):
        response = self.api.post(api_url("monitoringprofile"), {"name": "Windows Standard"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        profile_id = response.data["id"]
        response = self.api.patch(
            api_url("monitoringprofile", "detail", profile_id), {"status": "disabled"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        response = self.api.get(api_url("monitoringprofile"), {"status": "active"})
        self.assertEqual([item["id"] for item in response.data["results"]], [self.profile.pk])
        response = self.api.get(api_url("monitoringprofile", "impact", self.profile.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["visible_asset_count"], 3)
        response = self.api.post(
            api_url("monitoringassetoverride"),
            {
                "profile": self.profile.pk,
                "rule": self.rule.pk,
                "key": self.rule.key_id,
                "operation": "change",
                "assigned_object_type": "virtualization.virtualmachine",
                "assigned_object_id": self.vm.pk,
                "parameters": {"warning": 85},
                "reason": "Capacity exception",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["active"])
        for asset in (self.vm, self.device):
            url = reverse(
                "plugins-api:netbox_monitoring-api:monitoring-effective",
                kwargs={"object_type": asset._meta.label_lower, "pk": asset.pk},
            )
            response = self.api.get(url)
            self.assertEqual(response.status_code, 200, response.data)
            expected = 85 if asset == self.vm else 80
            self.assertEqual(response.data["checks"][0]["parameters"]["warning"], expected)
        self.assertEqual(self.api.delete(api_url("monitoringprofile", "detail", profile_id)).status_code, 204)

    def test_native_asset_api_rejects_incompatible_assignment(self):
        incompatible = MonitoringProfile.objects.create(name="Device only")
        incompatible.object_types.set([ContentType.objects.get_for_model(self.device)])
        url = reverse("virtualization-api:virtualmachine-detail", args=[self.vm.pk])
        response = self.api.patch(url, {"custom_fields": {PROFILE_FIELD: incompatible.pk}}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.vm.refresh_from_db()
        self.assertEqual(self.vm.custom_field_data[PROFILE_FIELD], self.profile.pk)

    def test_list_detail_forms_tabs_journal_and_changelog_render(self):
        for model, instance in (
            ("monitoringprofile", self.profile),
            ("monitoringcheckkey", self.check_key),
            ("monitoringcheckrule", self.rule),
            ("monitoringassetoverride", self.make_override()),
        ):
            for suffix, pk in (
                ("_list", None),
                ("", instance.pk),
                ("_add", None),
                ("_edit", instance.pk),
                ("_changelog", instance.pk),
                ("_journal", instance.pk),
                ("_import", None),
            ):
                with self.subTest(model=model, suffix=suffix):
                    response = self.client.get(ui_url(model, suffix, pk))
                    self.assertEqual(response.status_code, 200)
        for namespace, asset in (
            ("dcim:device_monitoring", self.device),
            ("virtualization:virtualmachine_monitoring", self.vm),
        ):
            response = self.client.get(reverse(namespace, args=[asset.pk]))
            self.assertContains(response, "Effective monitoring configuration")
            self.assertContains(response, "disk.all")

    def test_preview_does_not_save_and_normal_edit_creates_native_changelog(self):
        url = ui_url("monitoringprofile", "_edit", self.profile.pk)
        data = {
            "name": "Changed name",
            "status": "active",
            "object_types": list(self.profile.object_types.values_list("pk", flat=True)),
            "_preview": "1",
        }
        response = self.client.post(url, data)
        self.assertContains(response, "Change preview")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.name, "Linux Standard")
        data.pop("_preview")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.name, "Changed name")
        self.assertTrue(
            ObjectChange.objects.filter(
                changed_object_type=ContentType.objects.get_for_model(self.profile),
                changed_object_id=self.profile.pk,
            ).exists()
        )

    def test_human_forms_store_only_explicit_parameter_changes(self):
        cpu = MonitoringCheckKey.objects.create(name="cpu.asset", check_type="cpu")
        form = MonitoringCheckRuleForm(
            data={
                "profile": self.profile.pk,
                "key": cpu.pk,
                "target": "",
                "metric": "utilization_percent",
                "warning": 80,
                "critical": 95,
                "window_seconds": 300,
                "enabled": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().parameters, DEFAULTS["cpu"])
        form = MonitoringAssetOverrideForm(
            data={
                "profile": self.profile.pk,
                "rule": self.rule.pk,
                "operation": "change",
                "assigned_object_type": ContentType.objects.get_for_model(self.vm).pk,
                "assigned_object_id": self.vm.pk,
                "metric": "used_percent",
                "warning": 85,
                "critical": 90,
                "exclude_paths": "",
                "reason": "Capacity exception",
                "enabled": True,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().parameters, {"warning": 85.0})

    def test_reason_only_form_edit_preserves_existing_explicit_patch(self):
        override = self.make_override()
        self.rule.parameters["warning"] = 85
        self.rule.save()
        form = MonitoringAssetOverrideForm(
            instance=override,
            data={
                "profile": self.profile.pk,
                "rule": self.rule.pk,
                "operation": "change",
                "assigned_object_type": ContentType.objects.get_for_model(self.vm).pk,
                "assigned_object_id": self.vm.pk,
                "metric": "used_percent",
                "warning": 85,
                "critical": 90,
                "exclude_paths": "",
                "reason": "New reason",
                "enabled": True,
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().parameters, {"warning": 85.0})

    def test_setup_is_previewable_idempotent_and_refuses_legacy_field(self):
        out = StringIO()
        call_command("setup_monitoring_fields", apply=True, stdout=out)
        self.assertIn("already exists", out.getvalue())
        field = CustomField.objects.get(name=PROFILE_FIELD)
        field.related_object_type = ContentType.objects.get_for_model(VirtualMachine)
        field.save()
        with self.assertRaises(CommandError):
            call_command("setup_monitoring_fields", apply=True, stdout=StringIO())
        field.delete()
        out = StringIO()
        call_command("setup_monitoring_fields", stdout=out)
        self.assertIn("Would create", out.getvalue())
        self.assertFalse(CustomField.objects.filter(name=PROFILE_FIELD).exists())


class MonitoringPermissionTests(MonitoringTestCase):
    def test_central_group_and_native_model_permissions_are_both_required(self):
        group = Group.objects.create(name="Monitoring Administrators")
        models = (MonitoringProfile, MonitoringCheckKey, MonitoringCheckRule, MonitoringAssetOverride, VirtualMachine)
        plain = self.user_with_permissions("model-admin", models, ("view", "add", "change", "delete"))
        member = self.user_with_permissions("central-admin", models, ("view", "add", "change", "delete"))
        member.groups.add(group)
        group_only = self.user_with_permissions("group-only", (VirtualMachine,))
        group_only.groups.add(group)
        api = APIClient()
        for user, status in ((plain, 403), (group_only, 403), (member, 201), (self.admin, 201)):
            with self.subTest(user=user):
                api.force_authenticate(user)
                response = api.post(api_url("monitoringprofile"), {"name": f"Created by {user}"}, format="json")
                self.assertEqual(response.status_code, status, response.data)
        self.client.force_login(plain)
        self.assertEqual(self.client.get(ui_url("monitoringprofile", "_add")).status_code, 403)
        self.assertEqual(
            self.client.post(ui_url("monitoringprofile", "_edit", self.profile.pk), {"name": "Forbidden"}).status_code,
            403,
        )

    @override_settings(LOGIN_REQUIRED=False, EXEMPT_VIEW_PERMISSIONS=["*"])
    def test_anonymous_reads_are_denied_even_with_public_netbox(self):
        api = APIClient()
        for model in ("monitoringprofile", "monitoringcheckkey", "monitoringcheckrule", "monitoringassetoverride"):
            self.assertIn(api.get(api_url(model)).status_code, (401, 403))
            self.assertEqual(self.client.get(ui_url(model)).status_code, 302)

    def test_rule_and_override_lists_hide_inaccessible_relations(self):
        self.make_override()
        reader = self.user_with_permissions("relations", (MonitoringCheckRule, MonitoringAssetOverride))
        api = APIClient()
        api.force_authenticate(reader)
        for model in ("monitoringcheckrule", "monitoringassetoverride"):
            response = api.get(api_url(model))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 0)

    def test_related_object_validation_and_asset_profile_selection_require_visibility(self):
        group = Group.objects.create(name="Monitoring Administrators")
        user = self.user_with_permissions("writer", (MonitoringAssetOverride,), ("view", "add"))
        user.groups.add(group)
        request = SimpleNamespace(user=user)
        serializer = MonitoringAssetOverrideSerializer(
            data={
                "profile": self.profile.pk,
                "rule": self.rule.pk,
                "key": self.rule.key_id,
                "assigned_object_type": "virtualization.virtualmachine",
                "assigned_object_id": self.vm.pk,
                "operation": "change",
                "parameters": {"warning": 85},
                "reason": "Capacity",
            },
            context={"request": request},
        )
        self.assertFalse(serializer.is_valid())
        with self.assertRaises(ValidationError):
            # Exercise request-scoped validation on a native asset, independently
            # of an API nested serializer rejecting the profile first.
            token = monitoring_request.set(request)
            try:
                self.vm.full_clean()
            finally:
                monitoring_request.reset(token)

    def test_impact_reports_only_visible_assets(self):
        user = self.user_with_permissions("impact", (MonitoringProfile,))
        permission_user = self.user_with_permissions("visible-vm", (VirtualMachine,), constraints={"pk": self.vm.pk})
        permission = permission_user.object_permissions.first()
        permission.users.add(user)
        api = APIClient()
        api.force_authenticate(user)
        response = api.get(api_url("monitoringprofile", "impact", self.profile.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["assets"]), 1)
        self.assertEqual(response.data["assets"][0]["id"], self.vm.pk)
        self.assertTrue(
            response.data["assets"][0]["config_url"].endswith(
                f"/assets/virtualization.virtualmachine/{self.vm.pk}/config/"
            )
        )

    def test_request_context_is_reset_when_a_request_raises(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        get_response = Mock(side_effect=RuntimeError("test"))
        with self.assertRaises(RuntimeError):
            MonitoringRequestMiddleware(get_response)(request)
        self.assertIsNone(monitoring_request.get())
