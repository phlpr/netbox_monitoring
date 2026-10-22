from django.urls import reverse


def asset_config_url(asset, request=None):
    path = reverse(
        "plugins-api:netbox_monitoring-api:asset-config",
        kwargs={
            "object_type": asset._meta.label_lower,
            "pk": asset.pk,
        },
    )
    return request.build_absolute_uri(path) if request else path
