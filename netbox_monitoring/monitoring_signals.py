"""Validate profile selections on all Device/VM form, API and import writes."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connections
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone
from netbox.signals import post_clean

from .monitoring_models import MonitoringAssetOverride, MonitoringProfile, asset_models, assigned_assets
from .monitoring_permissions import monitoring_request
from .monitoring_schema import ASSET_MODELS, PROFILE_FIELD


@receiver(post_clean, dispatch_uid="netbox_monitoring.validate_monitoring_profile")
def validate_monitoring_profile(sender, instance, **kwargs):
    if instance._meta.label_lower not in ASSET_MODELS:
        return
    value = instance.custom_field_data.get(PROFILE_FIELD)
    old = {}
    if instance.pk:
        old = type(instance).objects.filter(pk=instance.pk).values_list("custom_field_data", flat=True).first() or {}
    previous = old.get(PROFILE_FIELD)
    if value is not None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValidationError(f"{PROFILE_FIELD}: select an existing monitoring profile.")
        profile = MonitoringProfile.objects.filter(pk=value).first()
        if profile is None:
            raise ValidationError(f"{PROFILE_FIELD}: the selected profile no longer exists.")
        request = monitoring_request.get()
        if request and not MonitoringProfile.objects.restrict(request.user, "view").filter(pk=value).exists():
            raise ValidationError(f"{PROFILE_FIELD}: view permission is required for the selected profile.")
        if not profile.accepts(instance):
            raise ValidationError(f"{PROFILE_FIELD}: the profile does not support this asset type/platform.")
        if value != previous and not profile.selectable:
            raise ValidationError(f"{PROFILE_FIELD}: this profile is no longer available for new selections.")
    if instance.pk and value != previous:
        ct = ContentType.objects.get_for_model(instance)
        active = MonitoringAssetOverride.objects.filter(
            assigned_object_type=ct,
            assigned_object_id=instance.pk,
            profile_id=previous,
            enabled=True,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        if active.exists():
            raise ValidationError(
                f"{PROFILE_FIELD}: ask the monitoring maintenance group to disable/remove existing active "
                "exceptions before switching or clearing the profile."
            )


@receiver(pre_delete, sender=MonitoringProfile, dispatch_uid="netbox_monitoring.protect_monitoring_profile")
def protect_monitoring_profile(sender, instance, **kwargs):
    MonitoringProfile.objects.using(kwargs.get("using", "default")).select_for_update().get(pk=instance.pk)
    assets = list(assigned_assets(instance))
    if assets:
        raise ProtectedError("This monitoring profile is still selected by assets.", assets)


def remove_asset_overrides(sender, instance, **kwargs):
    ct = ContentType.objects.get_for_model(instance)
    # Deliberately snapshot each dependent object so deletion is change-logged.
    for override in MonitoringAssetOverride.objects.filter(
        assigned_object_type=ct,
        assigned_object_id=instance.pk,
    ):
        override.snapshot()
        override.delete()


def validate_asset_save(sender, instance, using="default", **kwargs):
    # Core UI/API writes run inside transactions. Revalidate under the same
    # profile locks used by catalogue writes/deletion, after form validation.
    value = instance.custom_field_data.get(PROFILE_FIELD)
    if value and connections[using].in_atomic_block:
        list(MonitoringProfile.objects.using(using).select_for_update().filter(pk=value))
    validate_monitoring_profile(sender, instance)


for model in asset_models():
    pre_save.connect(
        validate_asset_save, sender=model, dispatch_uid=f"netbox_monitoring.monitoring_save.{model._meta.label_lower}"
    )
    pre_delete.connect(
        remove_asset_overrides,
        sender=model,
        dispatch_uid=f"netbox_monitoring.monitoring_cleanup.{model._meta.label_lower}",
    )
