"""Monitoring catalogue writes and backend-independent effective configuration."""

from django.apps import apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from netbox.api.viewsets import NetBoxModelViewSet
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..assets import asset_config_url
from ..models import MonitoringAssetOverride, MonitoringCheckKey, MonitoringCheckRule, MonitoringProfile
from ..monitoring_filtersets import (
    MonitoringAssetOverrideFilterSet,
    MonitoringCheckKeyFilterSet,
    MonitoringCheckRuleFilterSet,
    MonitoringProfileFilterSet,
)
from ..monitoring_models import asset_models, assigned_assets
from ..monitoring_permissions import can_manage_monitoring
from ..monitoring_resolver import resolve_monitoring
from ..monitoring_schema import ASSET_MODELS, PROFILE_FIELD
from .serializers import (
    MonitoringAssetOverrideSerializer,
    MonitoringCheckKeySerializer,
    MonitoringCheckRuleSerializer,
    MonitoringProfileSerializer,
)


class MonitoringMaintenancePermission(BasePermission):
    message = "Only the configured monitoring maintenance group may change monitoring configuration."

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or can_manage_monitoring(request.user)


class MonitoringViewSet(NetBoxModelViewSet):
    permission_classes = (*NetBoxModelViewSet.permission_classes, IsAuthenticated, MonitoringMaintenancePermission)


class MonitoringProfileViewSet(MonitoringViewSet):
    queryset = MonitoringProfile.objects.all()
    serializer_class = MonitoringProfileSerializer
    filterset_class = MonitoringProfileFilterSet

    @action(detail=True, methods=["get"])
    def impact(self, request, pk=None):
        profile = self.get_object()
        assets = list(assigned_assets(profile, request.user))
        return Response(
            {
                "profile_id": profile.pk,
                "visible_asset_count": len(assets),
                "assets": [
                    {
                        "object_type": asset._meta.label_lower,
                        "id": asset.pk,
                        "name": str(asset),
                        "config_url": asset_config_url(asset, request),
                    }
                    for asset in assets
                ],
            }
        )


class MonitoringCheckKeyViewSet(MonitoringViewSet):
    queryset = MonitoringCheckKey.objects.all()
    serializer_class = MonitoringCheckKeySerializer
    filterset_class = MonitoringCheckKeyFilterSet


class MonitoringCheckRuleViewSet(MonitoringViewSet):
    queryset = MonitoringCheckRule.objects.select_related("profile", "key")
    serializer_class = MonitoringCheckRuleSerializer
    filterset_class = MonitoringCheckRuleFilterSet


class MonitoringAssetOverrideViewSet(MonitoringViewSet):
    queryset = MonitoringAssetOverride.objects.select_related("profile", "rule", "key", "assigned_object_type")
    serializer_class = MonitoringAssetOverrideSerializer
    filterset_class = MonitoringAssetOverrideFilterSet


class MonitoringEffectiveView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, object_type, pk):
        if object_type not in ASSET_MODELS:
            raise NotFound("Unsupported monitoring asset type.")
        model = apps.get_model(object_type)
        asset = get_object_or_404(model.objects.restrict(request.user, "view"), pk=pk)
        try:
            return Response(resolve_monitoring(asset, request.user))
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages)


class MonitoringAssetConfigView(MonitoringEffectiveView):
    """One authenticated GET returns the complete configuration for an asset."""

    def get(self, request, object_type, pk):
        response = super().get(request, object_type, pk)
        if not response.data["configured"]:
            raise NotFound("Monitoring is not configured for this asset.")
        return response


class MonitoringAssetListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        profiles = {profile.pk: profile for profile in MonitoringProfile.objects.restrict(request.user, "view")}
        assets = []
        for model in asset_models():
            queryset = (
                model.objects.restrict(request.user, "view")
                .filter(**{f"custom_field_data__{PROFILE_FIELD}__isnull": False})
                .exclude(**{f"custom_field_data__{PROFILE_FIELD}": None})
                .order_by("pk")
            )
            for asset in queryset:
                profile = profiles.get(asset.custom_field_data.get(PROFILE_FIELD))
                if profile is not None:
                    assets.append(
                        {
                            "object_type": asset._meta.label_lower,
                            "id": asset.pk,
                            "name": str(asset),
                            "profile": {"id": profile.pk, "name": profile.name, "status": profile.status},
                            "config_url": asset_config_url(asset, request),
                        }
                    )
        paginator = LimitOffsetPagination()
        paginator.default_limit = 50
        paginator.max_limit = 1000
        page = paginator.paginate_queryset(assets, request, view=self)
        return paginator.get_paginated_response(page)
