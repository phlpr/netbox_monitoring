"""Request context for native object permission checks on related objects."""

from contextvars import ContextVar

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
