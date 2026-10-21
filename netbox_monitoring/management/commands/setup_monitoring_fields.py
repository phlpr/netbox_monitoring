"""Add the native Device/VM profile selector without changing existing assets."""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from extras.models import CustomField

from netbox_monitoring.models import MonitoringProfile
from netbox_monitoring.monitoring_schema import ASSET_MODELS, PROFILE_FIELD


class Command(BaseCommand):
    help = "Preview/create monitoring_profile as an object field on Devices and VMs."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Create the field; default is a read-only preview.")

    @transaction.atomic
    def handle(self, *args, **options):
        target = ContentType.objects.filter(
            app_label="netbox_monitoring", model=MonitoringProfile._meta.model_name
        ).first()
        assets = [
            ContentType.objects.filter(app_label=label.split(".")[0], model=label.split(".")[1]).first()
            for label in ASSET_MODELS
        ]
        if target is None or any(ct is None for ct in assets):
            raise CommandError("Required content types are missing. Run NetBox migrations first.")
        existing = CustomField.objects.filter(name=PROFILE_FIELD).first()
        if existing:
            if (
                existing.type != "object"
                or existing.related_object_type_id != target.pk
                or existing.related_object_filter != {"selectable": True}
                or not all(existing.object_types.filter(pk=ct.pk).exists() for ct in assets)
            ):
                raise CommandError("An incompatible monitoring_profile field exists; review it manually.")
            self.stdout.write("monitoring_profile already exists. No changes made.")
            return
        if not options["apply"]:
            self.stdout.write(
                "Would create monitoring_profile: object → MonitoringProfile, Device + VM, "
                "selectable profiles only, no default. Run with --apply to create it."
            )
            return
        field = CustomField(
            name=PROFILE_FIELD,
            label="Monitoring Profile",
            type="object",
            related_object_type=target,
            related_object_filter={"selectable": True},
            group_name="Monitoring",
            description="Centrally maintained monitoring configuration. Asset exceptions are maintained by the monitoring team.",
        )
        field.full_clean()
        field.save()
        field.object_types.set(assets)
        self.stdout.write(
            self.style.SUCCESS("Created monitoring_profile. Existing assets were not assigned a default.")
        )
