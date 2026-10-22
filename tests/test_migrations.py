from copy import deepcopy

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from netbox_monitoring.monitoring_schema import DEFAULTS


def historical_apps(executor, target):
    # Retain the other apps' current schema when only this plugin is rolled
    # back; newer NetBox versions add required fields to e.g. CustomField.
    native = [node for node in executor.loader.graph.leaf_nodes() if node[0] != "netbox_monitoring"]
    return executor.loader.project_state(native + target).apps


class CheckKeyMigrationTests(TransactionTestCase):
    def test_existing_rule_and_exception_keys_round_trip(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("netbox_monitoring", "0004_remove_legacy_profile_fields")]
        after = [("netbox_monitoring", "0005_check_key_catalog")]
        try:
            executor.migrate(before)
            state = historical_apps(executor, before)
            Profile = state.get_model("netbox_monitoring", "MonitoringProfile")
            Rule = state.get_model("netbox_monitoring", "MonitoringCheckRule")
            Override = state.get_model("netbox_monitoring", "MonitoringAssetOverride")
            ContentType = state.get_model("contenttypes", "ContentType")
            profile = Profile.objects.create(name="Legacy profile")
            other = Profile.objects.create(name="Other profile")
            rule = Rule.objects.create(
                profile=profile, key="disk.all", check_type="disk", target="*", parameters=deepcopy(DEFAULTS["disk"])
            )
            Rule.objects.create(
                profile=other, key="disk.all", check_type="disk", target="*", parameters=deepcopy(DEFAULTS["disk"])
            )
            ct = ContentType.objects.get(app_label="virtualization", model="virtualmachine")
            changed = Override.objects.create(
                profile=profile,
                rule=rule,
                key="disk.all",
                operation="change",
                assigned_object_type=ct,
                assigned_object_id=123,
                parameters={"warning": 85},
                reason="Legacy reason",
            )
            added = Override.objects.create(
                profile=profile,
                key="process.sshd",
                check_type="process",
                target="sshd",
                operation="add",
                assigned_object_type=ct,
                assigned_object_id=123,
                parameters=deepcopy(DEFAULTS["process"]),
                reason="Legacy additional check",
            )
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            state = historical_apps(executor, after)
            Key = state.get_model("netbox_monitoring", "MonitoringCheckKey")
            self.assertEqual(Key.objects.filter(name="disk.all").count(), 1)
            Rule = state.get_model("netbox_monitoring", "MonitoringCheckRule")
            Override = state.get_model("netbox_monitoring", "MonitoringAssetOverride")
            self.assertEqual(Rule.objects.get(pk=rule.pk).key.name, "disk.all")
            self.assertEqual(Override.objects.get(pk=changed.pk).key_id, Rule.objects.get(pk=rule.pk).key_id)
            self.assertEqual(Override.objects.get(pk=added.pk).key.check_type, "process")
            self.assertEqual(Override.objects.get(pk=changed.pk).parameters, {"warning": 85})
            executor = MigrationExecutor(connection)
            executor.migrate(before)
            restored = historical_apps(executor, before).get_model("netbox_monitoring", "MonitoringAssetOverride")
            self.assertEqual(restored.objects.get(pk=added.pk).key, "process.sshd")
            self.assertEqual(restored.objects.get(pk=added.pk).check_type, "process")
            self.assertEqual(restored.objects.get(pk=changed.pk).check_type, "")
        finally:
            MigrationExecutor(connection).migrate(latest)


class ProfileMigrationTests(TransactionTestCase):
    def test_legacy_status_scope_and_selector_are_preserved(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("netbox_monitoring", "0001_initial")]
        after = [("netbox_monitoring", "0004_remove_legacy_profile_fields")]
        try:
            executor.migrate(before)
            state = historical_apps(executor, before)
            Profile = state.get_model("netbox_monitoring", "MonitoringProfile")
            old = Profile.objects.create(name="Legacy disabled VM", selectable=False, asset_type="virtualmachine")
            both = Profile.objects.create(name="Legacy active both", selectable=True, asset_type="any")
            ContentType = state.get_model("contenttypes", "ContentType")
            Field = state.get_model("extras", "CustomField")
            field = Field.objects.create(
                name="monitoring_profile",
                type="object",
                related_object_type=ContentType.objects.get(app_label="netbox_monitoring", model="monitoringprofile"),
                related_object_filter={"selectable": True},
            )
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            state = historical_apps(executor, after)
            Profile = state.get_model("netbox_monitoring", "MonitoringProfile")
            migrated = Profile.objects.get(pk=old.pk)
            self.assertEqual(migrated.status, "disabled")
            self.assertEqual(list(migrated.object_types.values_list("model", flat=True)), ["virtualmachine"])
            self.assertEqual(Profile.objects.get(pk=both.pk).status, "active")
            self.assertEqual(Profile.objects.get(pk=both.pk).object_types.count(), 2)
            self.assertEqual(
                state.get_model("extras", "CustomField").objects.get(pk=field.pk).related_object_filter,
                {"status": "active"},
            )
            executor = MigrationExecutor(connection)
            executor.migrate(before)
            reverted = historical_apps(executor, before).get_model("netbox_monitoring", "MonitoringProfile")
            self.assertFalse(reverted.objects.get(pk=old.pk).selectable)
            self.assertEqual(reverted.objects.get(pk=old.pk).asset_type, "virtualmachine")
        finally:
            MigrationExecutor(connection).migrate(latest)
