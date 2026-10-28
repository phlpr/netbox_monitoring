from netbox.plugins import PluginConfig

from .version import __version__


class MonitoringConfig(PluginConfig):
    name = "netbox_monitoring"
    verbose_name = "Monitoring"
    description = "Backend-independent monitoring profiles, checks, and asset overrides"
    version = __version__
    author = "Philipp Prohaszka"
    base_url = "monitoring"
    min_version = "4.6.10"
    default_settings = {"monitoring_admin_group": "Monitoring Administrators"}
    middleware = ["netbox_monitoring.monitoring_permissions.MonitoringRequestMiddleware"]

    def ready(self):
        super().ready()
        from . import monitoring_signals  # noqa: F401 -- register lifecycle validation
        from .monitoring_views import register_monitoring_tabs

        register_monitoring_tabs()


config = MonitoringConfig
