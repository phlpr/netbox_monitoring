"""Monitoring catalogue writes and backend-independent effective configuration."""

from django.apps import apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from netbox.api.viewsets import NetBoxModelViewSet
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..assets import asset_config_url, is_asset_model
from ..models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)
from ..monitoring_filtersets import (
    MonitoringAssetOverrideFilterSet,
    MonitoringCheckKeyFilterSet,
    MonitoringCheckRuleFilterSet,
    MonitoringProfileAssignmentFilterSet,
    MonitoringProfileFilterSet,
)
from ..monitoring_models import assigned_assets
from ..monitoring_resolver import resolve_monitoring
from .serializers import (
    MonitoringAssetOverrideSerializer,
    MonitoringCheckKeySerializer,
    MonitoringCheckRuleSerializer,
    MonitoringProfileAssignmentSerializer,
    MonitoringProfileSerializer,
)


class MonitoringViewSet(NetBoxModelViewSet):
    permission_classes = (*NetBoxModelViewSet.permission_classes, IsAuthenticated)


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


class MonitoringProfileAssignmentViewSet(MonitoringViewSet):
    queryset = MonitoringProfileAssignment.objects.select_related("profile", "assigned_object_type")
    serializer_class = MonitoringProfileAssignmentSerializer
    filterset_class = MonitoringProfileAssignmentFilterSet


class MonitoringEffectiveView(APIView):
    permission_classes = (IsAuthenticated,)
    include_overrides = True

    def get(self, request, object_type, pk):
        try:
            model = apps.get_model(object_type)
        except (LookupError, ValueError):
            model = None
        if not is_asset_model(model):
            raise NotFound("Unsupported monitoring asset type.")
        asset = get_object_or_404(model.objects.restrict(request.user, "view"), pk=pk)
        try:
            return Response(resolve_monitoring(asset, request.user, include_overrides=self.include_overrides))
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
        assets = []
        assignments = (
            MonitoringProfileAssignment.objects.restrict(request.user, "view")
            .filter(enabled=True)
            .select_related("profile", "assigned_object_type")
        )
        grouped = {}
        for assignment in assignments.order_by(
            "assigned_object_type__app_label",
            "assigned_object_type__model",
            "assigned_object_id",
            "-weight",
            "profile_id",
        ):
            identity = (assignment.assigned_object_type_id, assignment.assigned_object_id)
            if identity not in grouped:
                asset = assignment.assigned_object
                if asset is None:
                    continue
                grouped[identity] = {
                    "object_type": asset._meta.label_lower,
                    "id": asset.pk,
                    "name": str(asset),
                    "profiles": [],
                    "config_url": asset_config_url(asset, request),
                }
                assets.append(grouped[identity])
            grouped[identity]["profiles"].append(
                {
                    "id": assignment.profile_id,
                    "name": assignment.profile.name,
                    "status": assignment.profile.status,
                    "assignment_id": assignment.pk,
                    "weight": assignment.weight,
                }
            )
        paginator = LimitOffsetPagination()
        paginator.default_limit = 50
        paginator.max_limit = 1000
        page = paginator.paginate_queryset(assets, request, view=self)
        return paginator.get_paginated_response(page)


class MonitoringAssetBaseConfigView(MonitoringAssetConfigView):
    """Profile composition used by exception forms, before asset exceptions."""

    include_overrides = False
