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


config = MonitoringConfig
