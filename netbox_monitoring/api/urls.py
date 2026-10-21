from django.urls import path
from netbox.api.routers import NetBoxRouter

from .views import (
    MonitoringAssetOverrideViewSet,
    MonitoringCheckRuleViewSet,
    MonitoringEffectiveView,
    MonitoringProfileViewSet,
)

router = NetBoxRouter()
router.register("monitoring-profiles", MonitoringProfileViewSet)
router.register("monitoring-check-rules", MonitoringCheckRuleViewSet)
router.register("monitoring-asset-overrides", MonitoringAssetOverrideViewSet)
urlpatterns = router.urls + [
    path(
        "monitoring-effective/<str:object_type>/<int:pk>/",
        MonitoringEffectiveView.as_view(),
        name="monitoring-effective",
    ),
]
