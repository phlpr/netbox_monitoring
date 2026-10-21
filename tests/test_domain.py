from copy import deepcopy
from datetime import timedelta

from dcim.models import Platform
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from virtualization.models import VirtualMachine

from netbox_monitoring.models import MonitoringAssetOverride, MonitoringCheckRule, MonitoringProfile
from netbox_monitoring.monitoring_resolver import resolve_monitoring
from netbox_monitoring.monitoring_schema import DEFAULTS, PROFILE_FIELD

from .base import MonitoringTestCase


class MonitoringDomainTests(MonitoringTestCase):
    def resolve(self, asset=None, **kwargs):
        return resolve_monitoring(asset or self.vm, self.admin, **kwargs)

    def test_one_asset_patch_preserves_shared_profile_inheritance(self):
        self.make_override()
        self.rule.parameters["critical"] = 95
        self.rule.save()
        self.assertEqual(self.resolve()["checks"][0]["parameters"]["warning"], 85)
        self.assertEqual(self.resolve()["checks"][0]["parameters"]["critical"], 95)
        self.assertEqual(self.resolve(self.vm_b)["checks"][0]["parameters"]["warning"], 80)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.parameters["warning"], 80)

    def test_add_disable_expiry_and_provenance(self):
        now = timezone.now()
        override = self.make_override(operation="disable", parameters={}, expires_at=now + timedelta(minutes=5))
        addition = self.make_override(
            operation="add",
            rule=None,
            key="process.sshd",
            check_type="process",
            target="sshd",
            parameters=deepcopy(DEFAULTS["process"]),
        )
        resolved = self.resolve(now=now)
        self.assertEqual([check["key"] for check in resolved["checks"]], ["disk.all", "process.sshd"])
        self.assertFalse(resolved["checks"][0]["enabled"])
        self.assertEqual(resolved["checks"][0]["source"]["override_id"], override.pk)
        self.assertEqual(resolved["checks"][1]["source"]["override_id"], addition.pk)
        expired = self.resolve(now=override.expires_at)
        self.assertTrue(expired["checks"][0]["enabled"])
        self.assertNotEqual(resolved["config_hash"], expired["config_hash"])

    def test_hash_ignores_metadata_and_changes_with_effective_parameters(self):
        override = self.make_override(ticket="INC-1")
        before = self.resolve()["config_hash"]
        override.reason = "Updated explanation"
        override.ticket = "INC-2"
        override.expires_at = timezone.now() + timedelta(days=1)
        override.save()
        self.assertEqual(before, self.resolve()["config_hash"])
        override.parameters = {"warning": 86}
        override.save()
        self.assertNotEqual(before, self.resolve()["config_hash"])

    def test_unconfigured_asset_and_disabled_profile(self):
        vm = VirtualMachine.objects.create(name="unconfigured")
        self.assertFalse(self.resolve(vm)["configured"])
        self.profile.selectable = False
        self.profile.save()
        self.vm.full_clean()
        self.assertTrue(self.resolve()["configured"])
        with self.assertRaises(ValidationError):
            VirtualMachine.objects.create(name="new", custom_field_data={PROFILE_FIELD: self.profile.pk})

    def test_duplicates_and_invalid_stored_dependencies_are_rejected(self):
        self.make_override()
        with self.assertRaises(ValidationError):
            self.make_override()
        with self.assertRaises(ValidationError):
            MonitoringCheckRule.objects.create(
                profile=self.profile,
                key="disk.other",
                check_type="disk",
                target="*",
                parameters=DEFAULTS["disk"],
            )
        self.rule.parameters["critical"] = 84
        with self.assertRaises(ValidationError):
            self.rule.save()
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.parameters["critical"], 90)
        self.rule.key = "new.key"
        with self.assertRaises(ValidationError):
            self.rule.save()
        with self.assertRaises(ProtectedError):
            self.rule.delete()
        with self.assertRaises(ProtectedError):
            self.profile.delete()

    def test_profile_scope_changes_cannot_invalidate_existing_assignments(self):
        self.profile.asset_type = "device"
        with self.assertRaises(ValidationError):
            self.profile.save()
        self.profile.asset_type = "any"
        self.profile.platform = Platform.objects.create(name="other-platform", slug="other-platform")
        with self.assertRaises(ValidationError):
            self.profile.save()

    def test_active_exceptions_block_profile_switch_and_inactive_exceptions_survive(self):
        override = self.make_override()
        self.vm.custom_field_data[PROFILE_FIELD] = None
        with self.assertRaises(ValidationError):
            self.vm.full_clean()
        with self.assertRaises(ValidationError):
            self.vm.save()
        override.enabled = False
        override.save()
        self.vm.save()
        override.refresh_from_db()
        self.assertEqual(override.profile_id, self.profile.pk)
        self.assertFalse(self.resolve()["configured"])

    def test_asset_deletion_cleans_up_exceptions(self):
        override = self.make_override()
        self.vm.delete()
        self.assertFalse(MonitoringAssetOverride.objects.filter(pk=override.pk).exists())

    def test_resolver_refuses_partially_visible_rules_or_active_exceptions(self):
        reader = self.user_with_permissions("profile-only", (VirtualMachine, MonitoringProfile))
        with self.assertRaises(PermissionDenied):
            resolve_monitoring(self.vm, reader)
        reader = self.user_with_permissions("rules-reader", (VirtualMachine, MonitoringProfile, MonitoringCheckRule))
        self.assertTrue(resolve_monitoring(self.vm, reader)["configured"])
        override = self.make_override()
        with self.assertRaises(PermissionDenied):
            resolve_monitoring(self.vm, reader)
        override.enabled = False
        override.save()
        self.assertTrue(resolve_monitoring(self.vm, reader)["configured"])

    def test_disabled_and_additional_checks_still_enforce_unique_targets(self):
        self.make_override(
            operation="add",
            rule=None,
            key="process.a",
            check_type="process",
            target="sshd",
            parameters=DEFAULTS["process"],
            enabled=False,
        )
        with self.assertRaises(ValidationError):
            self.make_override(
                operation="add",
                rule=None,
                key="process.b",
                check_type="process",
                target="sshd",
                parameters=DEFAULTS["process"],
            )
