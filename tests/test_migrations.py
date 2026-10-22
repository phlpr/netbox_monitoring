from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ProfileMigrationTests(TransactionTestCase):
    def test_legacy_status_scope_and_selector_are_preserved(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("netbox_monitoring", "0001_initial")]
        after = [("netbox_monitoring", "0004_remove_legacy_profile_fields")]
        try:
            executor.migrate(before)
            state = executor.loader.project_state(before).apps
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
            state = executor.loader.project_state(after).apps
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
            reverted = executor.loader.project_state(before).apps.get_model("netbox_monitoring", "MonitoringProfile")
            self.assertFalse(reverted.objects.get(pk=old.pk).selectable)
            self.assertEqual(reverted.objects.get(pk=old.pk).asset_type, "virtualmachine")
        finally:
            MigrationExecutor(connection).migrate(latest)
