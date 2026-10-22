"""Native serializers for object custom fields, events, and the REST API."""

from dcim.api.serializers import PlatformSerializer
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from netbox.api.fields import ChoiceField, ContentTypeField
from netbox.api.serializers import PrimaryModelSerializer
from rest_framework import serializers

from ..choices import MonitoringProfileStatusChoices
from ..models import MonitoringAssetOverride, MonitoringCheckRule, MonitoringProfile
from ..monitoring_schema import ASSET_MODELS


class MonitoringSerializerMixin:
    def validate(self, data):
        request = self.context.get("request")
        if request and not self.nested:
            for key in ("profile", "rule", "platform"):
                related = data.get(key, getattr(self.instance, key, None) if self.instance else None)
                if related and not type(related).objects.restrict(request.user, "view").filter(pk=related.pk).exists():
                    raise serializers.ValidationError({key: "View permission is required for the selected object."})
            if self.Meta.model is MonitoringAssetOverride:
                ct = data.get("assigned_object_type", getattr(self.instance, "assigned_object_type", None))
                asset_id = data.get("assigned_object_id", getattr(self.instance, "assigned_object_id", None))
                if ct and asset_id:
                    label = f"{ct.app_label}.{ct.model}"
                    if (
                        label not in ASSET_MODELS
                        or not ct.model_class().objects.restrict(request.user, "view").filter(pk=asset_id).exists()
                    ):
                        raise serializers.ValidationError(
                            {"assigned_object_id": "Select a supported asset you may view."}
                        )
        return super().validate(data)

    def save(self, **kwargs):
        try:
            with transaction.atomic():
                return super().save(**kwargs)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict if hasattr(error, "message_dict") else error.messages)


class MonitoringProfileSerializer(MonitoringSerializerMixin, PrimaryModelSerializer):
    platform = PlatformSerializer(nested=True, required=False, allow_null=True)
    status = ChoiceField(choices=MonitoringProfileStatusChoices, required=False)
    object_types = ContentTypeField(
        queryset=ContentType.objects.filter(
            Q(app_label="dcim", model="device") | Q(app_label="virtualization", model="virtualmachine")
        ),
        many=True,
        required=False,
    )

    class Meta:
        model = MonitoringProfile
        fields = (
            "id",
            "url",
            "display",
            "name",
            "description",
            "status",
            "object_types",
            "platform",
            "owner",
            "comments",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name")


class MonitoringCheckRuleSerializer(MonitoringSerializerMixin, PrimaryModelSerializer):
    profile = MonitoringProfileSerializer(nested=True)

    class Meta:
        model = MonitoringCheckRule
        fields = (
            "id",
            "url",
            "display",
            "profile",
            "key",
            "check_type",
            "target",
            "parameters",
            "enabled",
            "description",
            "comments",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "key", "check_type", "target")


class MonitoringAssetOverrideSerializer(MonitoringSerializerMixin, PrimaryModelSerializer):
    profile = MonitoringProfileSerializer(nested=True)
    rule = MonitoringCheckRuleSerializer(nested=True, required=False, allow_null=True)
    assigned_object_type = ContentTypeField(
        queryset=ContentType.objects.filter(
            Q(app_label="dcim", model="device") | Q(app_label="virtualization", model="virtualmachine"),
        )
    )
    active = serializers.BooleanField(source="is_active", read_only=True)

    class Meta:
        model = MonitoringAssetOverride
        fields = (
            "id",
            "url",
            "display",
            "profile",
            "rule",
            "assigned_object_type",
            "assigned_object_id",
            "key",
            "operation",
            "check_type",
            "target",
            "parameters",
            "reason",
            "ticket",
            "expires_at",
            "enabled",
            "active",
            "description",
            "comments",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "key", "operation")
