"""Validate composition and keep plugin-owned relations consistent with assets."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.db.models.deletion import ProtectedError
from django.db.models.signals import m2m_changed, pre_delete, pre_save
from django.dispatch import receiver
from netbox.signals import post_clean

from .assets import asset_models, is_asset_model
from .monitoring_composition import validate_composition
from .monitoring_models import (
    MonitoringAssetOverride,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
    assigned_assets,
    validate_asset_reference,
)
from .monitoring_schema import PROFILE_FIELD
from .monitoring_transactions import asset_cleanup, configuration_write


@receiver(post_clean, dispatch_uid="netbox_monitoring.validate_monitoring_profile")
def validate_monitoring_profile(sender, instance, **kwargs):
    if not is_asset_model(type(instance)):
        return
    if PROFILE_FIELD in instance.custom_field_data:
        raise ValidationError(
            "monitoring_profile has been replaced by the Monitoring profiles card. Remove the obsolete custom field value."
        )
    if not instance.pk:
        return
    for assignment in MonitoringProfileAssignment.objects.filter(
        assigned_object_type=ContentType.objects.get_for_model(instance),
        assigned_object_id=instance.pk,
    ).select_related("profile"):
        if not assignment.profile.accepts(instance):
            raise ValidationError("The new asset type/platform is incompatible with an assigned monitoring profile.")


@receiver(pre_delete, sender=MonitoringProfileAssignment)
@receiver(pre_delete, sender=MonitoringCheckRule)
def validate_configuration_delete(sender, instance, using="default", origin=None, **kwargs):
    if asset_cleanup.get():
        return
    with configuration_write(using):
        if isinstance(instance, MonitoringProfileAssignment):
            validate_asset_reference(instance, require_change=True)
            assets = [instance.assigned_object]
        else:
            assets = assigned_assets(instance.profile)
        deleted = list(origin) if isinstance(origin, QuerySet) and origin.model is sender else instance
        try:
            for asset in assets:
                if asset is not None:
                    validate_composition(asset, deleted=deleted)
        except ValidationError as error:
            raise ProtectedError("; ".join(error.messages), [instance]) from error


def remove_asset_monitoring(sender, instance, using="default", **kwargs):
    ct = ContentType.objects.get_for_model(instance)
    token = asset_cleanup.set(True)
    try:
        with configuration_write(using):
            for model in (MonitoringAssetOverride, MonitoringProfileAssignment):
                for obj in model.objects.filter(assigned_object_type=ct, assigned_object_id=instance.pk):
                    obj.snapshot()
                    obj.delete()
    finally:
        asset_cleanup.reset(token)


@receiver(m2m_changed, sender=MonitoringProfile.object_types.through)
def validate_profile_object_types(sender, instance, action, reverse, pk_set, using="default", **kwargs):
    if action not in ("pre_add", "pre_remove", "pre_clear"):
        return
    profiles = (
        MonitoringProfile.objects.filter(pk__in=pk_set)
        if reverse and pk_set is not None
        else (instance.monitoring_profiles.all() if reverse else [instance])
    )
    with configuration_write(using):
        for profile in profiles:
            selected = set(profile.object_types.values_list("pk", flat=True))
            changed = {instance.pk} if reverse else set(pk_set or [])
            if action == "pre_add":
                selected |= changed
            elif action == "pre_remove":
                selected -= changed
            else:
                selected = selected - {instance.pk} if reverse else set()
            types = list(ContentType.objects.filter(pk__in=selected))
            if any(not is_asset_model(ct.model_class()) for ct in types):
                raise ValidationError("Only supported monitoring asset object types may be selected.")
            labels = {f"{ct.app_label}.{ct.model}" for ct in types}
            if any(asset._meta.label_lower not in labels for asset in assigned_assets(profile)):
                raise ValidationError("The new object types exclude assets already assigned to this profile.")


def validate_asset_save(sender, instance, using="default", **kwargs):
    with configuration_write(using):
        validate_monitoring_profile(sender, instance)


for model in asset_models():
    pre_save.connect(
        validate_asset_save, sender=model, dispatch_uid=f"netbox_monitoring.monitoring_save.{model._meta.label_lower}"
    )
    pre_delete.connect(
        remove_asset_monitoring,
        sender=model,
        dispatch_uid=f"netbox_monitoring.monitoring_cleanup.{model._meta.label_lower}",
    )
