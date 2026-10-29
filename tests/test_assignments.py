from copy import deepcopy
from urllib.parse import parse_qs, urlencode, urlsplit

from dcim.models import Platform
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from extras.models import CustomField
from rest_framework.test import APIClient
from virtualization.models import VirtualMachine

from netbox_monitoring.assets import asset_config_url
from netbox_monitoring.models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)
from netbox_monitoring.monitoring_resolver import resolve_monitoring
from netbox_monitoring.monitoring_schema import DEFAULTS, PROFILE_FIELD

from .base import MonitoringTestCase
from .test_integration import api_url, ui_url


class WeightedAssignmentTests(MonitoringTestCase):
    def profile_with_rule(self, warning=70, **kwargs):
        profile = MonitoringProfile.objects.create(name="Extra profile")
        rule = MonitoringCheckRule.objects.create(
            profile=profile,
            key=self.check_key,
            target="/var",
            parameters=deepcopy(DEFAULTS["disk"]) | {"warning": warning},
            **kwargs,
        )
        return profile, rule

    def assign(self, profile, weight=200, **kwargs):
        return MonitoringProfileAssignment.objects.create(
            profile=profile,
            assigned_object_type=ContentType.objects.get_for_model(self.vm),
            assigned_object_id=self.vm.pk,
            weight=weight,
            **kwargs,
        )

    def resolve(self):
        return resolve_monitoring(self.vm, self.admin)

    def test_larger_weight_replaces_whole_check_and_distinct_keys_combine(self):
        profile, rule = self.profile_with_rule()
        key = MonitoringCheckKey.objects.create(name="cpu.asset", check_type="cpu")
        MonitoringCheckRule.objects.create(profile=profile, key=key, parameters=DEFAULTS["cpu"])
        mapping = self.assign(profile)
        result = self.resolve()
        self.assertEqual(result["schema_version"], 2)
        self.assertIsNone(result["profile"])
        self.assertEqual([p["weight"] for p in result["profiles"]], [200, 100])
        self.assertEqual([c["key"] for c in result["checks"]], ["cpu.asset", "disk.all"])
        disk = result["checks"][1]
        self.assertEqual(disk["target"], "/var")
        self.assertEqual(disk["parameters"], rule.parameters)
        self.assertEqual(disk["source"]["assignment_id"], mapping.pk)
        self.assertEqual(resolve_monitoring(self.vm_b, self.admin)["checks"][0]["target"], "*")

    def test_equal_weight_conflict_is_rejected_on_assignment_rule_update_and_export(self):
        profile, rule = self.profile_with_rule()
        with self.assertRaisesMessage(ValidationError, "Conflicting definitions"):
            self.assign(profile, weight=100)
        mapping = self.assign(profile, weight=200)
        mapping.weight = 100
        with self.assertRaises(ValidationError):
            mapping.save()
        # Corrupted/imported data must also fail closed at read time.
        MonitoringProfileAssignment.objects.filter(pk=mapping.pk).update(weight=100)
        with self.assertRaises(ValidationError):
            self.resolve()
        MonitoringProfileAssignment.objects.filter(pk=mapping.pk).update(weight=200)
        rule.target = "*"
        rule.parameters = deepcopy(self.rule.parameters)
        rule.save()
        mapping.weight = 100
        mapping.save()
        rule.parameters["warning"] = 75
        with self.assertRaises(ValidationError):
            rule.save()

    def test_identical_equal_weight_definitions_and_weight_only_changes_keep_hash(self):
        profile = MonitoringProfile.objects.create(name="Identical profile")
        MonitoringCheckRule.objects.create(
            profile=profile, key=self.check_key, target="*", parameters=self.rule.parameters
        )
        before = self.resolve()["config_hash"]
        mapping = self.assign(profile, weight=100)
        self.assertEqual(self.resolve()["config_hash"], before)
        mapping.weight = 300
        mapping.save()
        self.assertEqual(self.resolve()["config_hash"], before)

    def test_asset_exception_follows_the_winning_key_and_blocks_invalid_fallback(self):
        self.make_override()
        profile, rule = self.profile_with_rule()
        mapping = self.assign(profile)
        check = self.resolve()["checks"][0]
        self.assertEqual(check["target"], "/var")
        self.assertEqual(check["parameters"]["warning"], 85)
        rule.parameters["critical"] = 84
        with self.assertRaises(ValidationError):
            rule.save()
        mapping.delete()
        self.assertEqual(self.resolve()["checks"][0]["target"], "*")
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.assignment.delete()

    def test_bulk_delete_checks_the_result_after_all_selected_assignments_are_removed(self):
        profile = MonitoringProfile.objects.create(name="Fallback profile")
        MonitoringCheckRule.objects.create(
            profile=profile, key=self.check_key, target="*", parameters=self.rule.parameters
        )
        self.assign(profile)
        self.make_override()
        queryset = MonitoringProfileAssignment.objects.filter(
            assigned_object_type=ContentType.objects.get_for_model(self.vm),
            assigned_object_id=self.vm.pk,
        )
        with self.assertRaises(ProtectedError), transaction.atomic():
            queryset.delete()
        self.assertEqual(queryset.count(), 2)

    def test_disabled_assignments_are_ignored_and_profile_status_only_blocks_new_mappings(self):
        profile, _ = self.profile_with_rule()
        mapping = self.assign(profile, enabled=False)
        before = self.resolve()["config_hash"]
        self.assertEqual(len(self.resolve()["profiles"]), 1)
        mapping.enabled = True
        mapping.save()
        self.assertNotEqual(self.resolve()["config_hash"], before)
        profile.status = "disabled"
        profile.save()
        mapping.description = "Existing mapping remains editable"
        mapping.save()
        self.assertEqual(len(self.resolve()["profiles"]), 2)
        other = VirtualMachine.objects.create(name="other")
        with self.assertRaisesMessage(ValidationError, "Disabled profiles"):
            MonitoringProfileAssignment.objects.create(
                profile=profile,
                assigned_object_type=ContentType.objects.get_for_model(other),
                assigned_object_id=other.pk,
            )

    def test_assignments_are_unique_and_are_cleaned_up_with_the_asset(self):
        with self.assertRaises(ValidationError):
            self.assign(self.profile)
        self.make_override()
        self.vm.delete()
        self.assertFalse(MonitoringProfileAssignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertFalse(MonitoringAssetOverride.objects.exists())
        self.assertFalse(CustomField.objects.filter(name=PROFILE_FIELD).exists())

    def test_api_delete_protection_and_base_config_excludes_overrides(self):
        self.make_override()
        api = APIClient()
        api.force_authenticate(self.admin)
        response = api.delete(api_url("monitoringprofileassignment", "detail", self.assignment.pk))
        self.assertEqual(response.status_code, 409, response.data)
        base_url = reverse(
            "plugins-api:netbox_monitoring-api:asset-base-config",
            kwargs={"object_type": self.vm._meta.label_lower, "pk": self.vm.pk},
        )
        self.assertEqual(api.get(base_url).data["checks"][0]["parameters"]["warning"], 80)
        self.assertEqual(api.get(asset_config_url(self.vm)).data["checks"][0]["parameters"]["warning"], 85)

    def test_save_reloads_profile_status_cached_before_another_write(self):
        profile = MonitoringProfile.objects.create(name="Initially active")
        pending = MonitoringProfileAssignment(profile=profile, assigned_object=self.vm)
        current = MonitoringProfile.objects.get(pk=profile.pk)
        current.status = "disabled"
        current.save()
        with self.assertRaisesMessage(ValidationError, "Disabled profiles"):
            pending.save()

    def test_save_reloads_key_type_cached_before_another_write(self):
        key = MonitoringCheckKey.objects.create(name="not.yet.used", check_type="disk")
        pending = MonitoringCheckRule(profile=self.profile, key=key, target="/tmp", parameters=DEFAULTS["disk"])
        current = MonitoringCheckKey.objects.get(pk=key.pk)
        current.check_type = "cpu"
        current.save()
        with self.assertRaises(ValidationError):
            pending.save()
        self.assertFalse(MonitoringCheckRule.objects.filter(key=key).exists())

    def test_save_reloads_asset_platform_cached_before_another_write(self):
        platform = Platform.objects.create(name="Scoped OS", slug="scoped-os")
        profile = MonitoringProfile.objects.create(name="Scoped profile", platform=platform)
        self.vm.platform = platform
        self.vm.save()
        pending = MonitoringProfileAssignment(profile=profile, assigned_object=self.vm)
        current = VirtualMachine.objects.get(pk=self.vm.pk)
        current.platform = None
        current.save()
        with self.assertRaisesMessage(ValidationError, "type/platform"):
            pending.save()

    def test_key_identity_validation_reloads_prefetched_dependencies(self):
        key = MonitoringCheckKey.objects.create(name="prefetched.key", check_type="disk")
        pending = MonitoringCheckKey.objects.prefetch_related("rules", "asset_overrides").get(pk=key.pk)
        MonitoringCheckRule.objects.create(profile=self.profile, key=key, target="/tmp", parameters=DEFAULTS["disk"])
        pending.check_type = "cpu"
        with self.assertRaisesMessage(ValidationError, "referenced key"):
            pending.save()
        key.refresh_from_db()
        self.assertEqual(key.check_type, "disk")


class AssignmentPermissionTests(MonitoringTestCase):
    def test_asset_editor_can_map_profiles_without_catalogue_maintenance_membership(self):
        editor = self.user_with_permissions(
            "asset-editor",
            (VirtualMachine, MonitoringProfile, MonitoringProfileAssignment),
            ("view", "add", "change", "delete"),
        )
        api = APIClient()
        api.force_authenticate(editor)
        self.assignment.delete()
        response = api.post(
            api_url("monitoringprofileassignment"),
            {
                "assigned_object_type": "virtualization.virtualmachine",
                "assigned_object_id": self.vm.pk,
                "profile": self.profile.pk,
                "weight": 150,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_login(editor)
        response = self.client.get(self.vm.get_absolute_url())
        self.assertContains(response, "Monitoring profiles")
        self.assertContains(response, "Assign profile")
        self.assertContains(response, "Edit assignment")
        self.assertContains(response, "150")
        self.assertEqual(self.client.get(ui_url("monitoringprofileassignment", "_add")).status_code, 200)
        self.assertEqual(api.post(api_url("monitoringprofile"), {"name": "Forbidden"}, format="json").status_code, 403)

    def test_assignment_writes_require_asset_change_and_profile_visibility(self):
        editor = self.user_with_permissions(
            "mapping-only", (MonitoringProfileAssignment, MonitoringProfile), ("view", "add", "change", "delete")
        )
        asset_reader = self.user_with_permissions("asset-read-only", (VirtualMachine,))
        asset_reader.object_permissions.first().users.add(editor)
        api = APIClient()
        api.force_authenticate(editor)
        other = MonitoringProfile.objects.create(name="Other")
        response = api.post(
            api_url("monitoringprofileassignment"),
            {
                "assigned_object_type": "virtualization.virtualmachine",
                "assigned_object_id": self.vm.pk,
                "profile": other.pk,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            api.delete(api_url("monitoringprofileassignment", "detail", self.assignment.pk)).status_code, 404
        )
        self.client.force_login(editor)
        response = self.client.get(self.vm.get_absolute_url())
        self.assertContains(response, "Monitoring profiles")
        self.assertNotContains(response, "Assign profile")
        self.assertNotContains(response, "Edit assignment")

    def test_export_refuses_hidden_assignment_instead_of_returning_partial_config(self):
        reader = self.user_with_permissions(
            "no-assignment-access", (VirtualMachine, MonitoringProfile, MonitoringCheckKey, MonitoringCheckRule)
        )
        with self.assertRaises(PermissionDenied):
            resolve_monitoring(self.vm, reader)


class AssetTargetFormTests(MonitoringTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def card_link(self, asset, context_key="assignment_add_url"):
        response = self.client.get(asset.get_absolute_url() + "monitoring/")
        self.assertEqual(response.status_code, 200)
        return response.context[context_key]

    def assert_target_locked(self, response, asset):
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertTrue(form.fields["assigned_object_type"].disabled)
        self.assertTrue(form.fields["assigned_object_id"].disabled)
        self.assertTrue(form.fields["assigned_object_type"].widget.is_hidden)
        self.assertTrue(form.fields["assigned_object_id"].widget.is_hidden)
        self.assertNotContains(response, 'for="id_assigned_object_type"')
        self.assertNotContains(response, 'for="id_assigned_object_id"')
        self.assertContains(response, 'name="assigned_object_type"', count=1)
        self.assertContains(response, 'name="assigned_object_id"', count=1)
        self.assertEqual(form.initial["assigned_object_type"], ContentType.objects.get_for_model(asset).pk)
        self.assertEqual(form.initial["assigned_object_id"], asset.pk)

    def test_card_target_stays_fixed_on_get_preview_and_forged_post(self):
        other = MonitoringProfile.objects.create(name="Additional UI profile")
        for asset in (self.device, self.vm):
            with self.subTest(asset=asset):
                link = self.card_link(asset)
                self.assert_target_locked(self.client.get(link), asset)
                data = {
                    "profile": other.pk,
                    "weight": 150,
                    "enabled": "on",
                    "assigned_object_type": ContentType.objects.get_for_model(self.vm_b).pk,
                    "assigned_object_id": self.vm_b.pk,
                }
                preview = self.client.post(link, data | {"_preview": "1"})
                self.assert_target_locked(preview, asset)
                self.assertEqual(preview.context["form"].instance.assigned_object, asset)
                self.assertFalse(
                    MonitoringProfileAssignment.objects.filter(
                        profile=other,
                        assigned_object_type=ContentType.objects.get_for_model(asset),
                        assigned_object_id=asset.pk,
                    ).exists()
                )
                response = self.client.post(link, data)
                self.assertEqual(response.status_code, 302)
                mapping = MonitoringProfileAssignment.objects.get(
                    profile=other,
                    assigned_object_type=ContentType.objects.get_for_model(asset),
                    assigned_object_id=asset.pk,
                )
                self.assertEqual(mapping.weight, 150)
        self.assertFalse(
            MonitoringProfileAssignment.objects.filter(
                profile=other,
                assigned_object_type=ContentType.objects.get_for_model(self.vm_b),
                assigned_object_id=self.vm_b.pk,
            ).exists()
        )

    def test_disabled_fields_may_be_omitted_and_add_another_keeps_context(self):
        other = MonitoringProfile.objects.create(name="Another UI profile")
        response = self.client.post(
            self.card_link(self.device),
            {
                "profile": other.pk,
                "weight": 100,
                "enabled": "on",
                "_addanother": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.url).query)
        self.assertEqual(query["assigned_object_id"], [str(self.device.pk)])
        self.assertEqual(query["assigned_object_type"], [str(ContentType.objects.get_for_model(self.device).pk)])
        self.assert_target_locked(self.client.get(response.url), self.device)
        self.assertTrue(
            MonitoringProfileAssignment.objects.filter(
                profile=other,
                assigned_object_type=ContentType.objects.get_for_model(self.device),
                assigned_object_id=self.device.pk,
            ).exists()
        )

    def test_existing_assignment_target_cannot_be_changed_via_query_or_post(self):
        values = {
            "assigned_object_type": ContentType.objects.get_for_model(self.device).pk,
            "assigned_object_id": self.device.pk,
        }
        url = ui_url("monitoringprofileassignment", "_edit", self.assignment.pk) + "?" + urlencode(values)
        self.assert_target_locked(self.client.get(url), self.vm)
        response = self.client.post(url, values | {"profile": self.profile.pk, "weight": 125, "enabled": "on"})
        self.assertEqual(response.status_code, 302)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.assigned_object, self.vm)
        self.assertEqual(self.assignment.weight, 125)

    def test_standalone_add_can_still_select_an_asset(self):
        url = ui_url("monitoringprofileassignment", "_add")
        response = self.client.get(url)
        for name in ("assigned_object_type", "assigned_object_id"):
            self.assertFalse(response.context["form"].fields[name].disabled)
        other = MonitoringProfile.objects.create(name="Standalone UI profile")
        response = self.client.post(
            url,
            {
                "profile": other.pk,
                "assigned_object_type": ContentType.objects.get_for_model(self.device).pk,
                "assigned_object_id": self.device.pk,
                "weight": 100,
                "enabled": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            MonitoringProfileAssignment.objects.filter(
                profile=other,
                assigned_object_type=ContentType.objects.get_for_model(self.device),
                assigned_object_id=self.device.pk,
            ).exists()
        )

    def test_exception_form_keeps_target_without_submitted_asset_fields(self):
        link = self.card_link(self.device, "exception_add_url")
        self.assert_target_locked(self.client.get(link), self.device)
        response = self.client.post(
            link,
            {
                "operation": "change",
                "key": self.check_key.pk,
                "metric": "used_percent",
                "warning": 85,
                "critical": 90,
                "exclude_paths": "",
                "reason": "Device capacity exception",
                "enabled": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        override = MonitoringAssetOverride.objects.get()
        self.assertEqual(override.assigned_object, self.device)
        self.assertEqual(override.parameters, {"warning": 85.0})
