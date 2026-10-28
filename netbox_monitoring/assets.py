from django.apps import apps
from django.db.models import Q
from django.urls import reverse
from netbox.models.features import CustomFieldsMixin, model_is_public


def is_asset_model(model):
    """Monitoring targets are public, installed custom-field models.

    Exclude our own configuration objects to avoid recursive monitoring and
    permission resolution. Inspect model classes without querying during ready().
    """
    return (
        model is not None
        and model._meta.app_label != "netbox_monitoring"
        and not model._meta.proxy
        and model_is_public(model)
        and issubclass(model, CustomFieldsMixin)
    )


def asset_models():
    return sorted(
        (model for model in apps.get_models() if is_asset_model(model)), key=lambda model: model._meta.label_lower
    )


def asset_object_types():
    from core.models import ObjectType

    condition = Q(pk__in=[])
    for model in asset_models():
        condition |= Q(app_label=model._meta.app_label, model=model._meta.model_name)
    return ObjectType.objects.with_feature("custom_fields").filter(condition, public=True)


def asset_config_url(asset, request=None):
    path = reverse(
        "plugins-api:netbox_monitoring-api:asset-config",
        kwargs={
            "object_type": asset._meta.label_lower,
            "pk": asset.pk,
        },
    )
    return request.build_absolute_uri(path) if request else path
