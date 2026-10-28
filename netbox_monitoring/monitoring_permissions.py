"""Central monitoring maintenance and request-scoped relation validation."""

from contextvars import ContextVar

from django.core.exceptions import PermissionDenied
from netbox.plugins import get_plugin_config

monitoring_request = ContextVar("netbox_monitoring_request", default=None)


class MonitoringRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = monitoring_request.set(request)
        try:
            return self.get_response(request)
        finally:
            monitoring_request.reset(token)


def can_manage_monitoring(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    name = get_plugin_config("netbox_monitoring", "monitoring_admin_group")
    return bool(name and user.groups.filter(name=name).exists())


def require_monitoring_manager(user):
    if not can_manage_monitoring(user):
        raise PermissionDenied("Only the configured monitoring maintenance group may change monitoring configuration.")


class MonitoringWriteMixin:
    def dispatch(self, request, *args, **kwargs):
        # Let LoginRequiredMixin handle anonymous users normally.
        if request.user.is_authenticated and self.queryset.model._meta.model_name != "monitoringprofileassignment":
            require_monitoring_manager(request.user)
        return super().dispatch(request, *args, **kwargs)
