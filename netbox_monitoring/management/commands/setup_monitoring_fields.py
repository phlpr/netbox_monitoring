"""Add/extend the native profile selector without changing asset assignments."""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from extras.models import CustomField

from netbox_monitoring.assets import asset_object_types
from netbox_monitoring.models import MonitoringProfile
from netbox_monitoring.monitoring_schema import PROFILE_FIELD


class Command(BaseCommand):
    help = "Preview/create/extend monitoring_profile on public object types supporting custom fields."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply changes; default is a read-only preview.")

    @transaction.atomic
    def handle(self, *args, **options):
        target = ContentType.objects.filter(
            app_label="netbox_monitoring", model=MonitoringProfile._meta.model_name
        ).first()
        assets = list(asset_object_types())
        if target is None or not assets:
            raise CommandError("Required content types are missing. Run NetBox migrations first.")
        existing = CustomField.objects.filter(name=PROFILE_FIELD).first()
        if existing:
            if (
                existing.type != "object"
                or existing.related_object_type_id != target.pk
                or existing.related_object_filter != {"status": "active"}
            ):
                raise CommandError("An incompatible monitoring_profile field exists; review it manually.")
            present = set(existing.object_types.values_list("pk", flat=True))
            missing = [ct for ct in assets if ct.pk not in present]
            if not missing:
                self.stdout.write("monitoring_profile already exists. No changes made.")
            elif not options["apply"]:
                self.stdout.write(
                    f"Would extend monitoring_profile to {len(missing)} additional object types. "
                    "Run with --apply to update it."
                )
            else:
                existing.object_types.add(*missing)
                self.stdout.write(
                    self.style.SUCCESS(f"Extended monitoring_profile to {len(missing)} additional object types.")
                )
            return
        if not options["apply"]:
            self.stdout.write(
                f"Would create monitoring_profile: object → MonitoringProfile, {len(assets)} public object types, "
                "active profiles only, no default. Run with --apply to create it."
            )
            return
        field = CustomField(
            name=PROFILE_FIELD,
            label="Monitoring Profile",
            type="object",
            related_object_type=target,
            related_object_filter={"status": "active"},
            group_name="Monitoring",
            description="Centrally maintained monitoring configuration. Asset exceptions are maintained by the monitoring team.",
        )
        field.full_clean()
        field.save()
        field.object_types.set(assets)
        self.stdout.write(
            self.style.SUCCESS("Created monitoring_profile. Existing assets were not assigned a default.")
        )
