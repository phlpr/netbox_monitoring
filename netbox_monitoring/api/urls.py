from django.urls import path
from netbox.api.routers import NetBoxRouter

from .views import (
    MonitoringAssetBaseConfigView,
    MonitoringAssetConfigView,
    MonitoringAssetListView,
    MonitoringAssetOverrideViewSet,
    MonitoringCheckKeyViewSet,
    MonitoringCheckRuleViewSet,
    MonitoringEffectiveView,
    MonitoringProfileAssignmentViewSet,
    MonitoringProfileViewSet,
)

router = NetBoxRouter()
router.register("monitoring-profiles", MonitoringProfileViewSet)
router.register("monitoring-profile-assignments", MonitoringProfileAssignmentViewSet)
router.register("monitoring-check-keys", MonitoringCheckKeyViewSet)
router.register("monitoring-check-rules", MonitoringCheckRuleViewSet)
router.register("monitoring-asset-overrides", MonitoringAssetOverrideViewSet)
urlpatterns = router.urls + [
    path(
        "assets/<str:object_type>/<int:pk>/base-config/",
        MonitoringAssetBaseConfigView.as_view(),
        name="asset-base-config",
    ),
    path("assets/", MonitoringAssetListView.as_view(), name="monitored-assets"),
    path("assets/<str:object_type>/<int:pk>/config/", MonitoringAssetConfigView.as_view(), name="asset-config"),
    path(
        "monitoring-effective/<str:object_type>/<int:pk>/",
        MonitoringEffectiveView.as_view(),
        name="monitoring-effective",
    ),
]
