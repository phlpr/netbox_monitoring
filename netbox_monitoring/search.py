"""Register monitoring models with NetBox global search."""

from netbox.search import SearchIndex, register_search

from .models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)


@register_search
class MonitoringProfileIndex(SearchIndex):
    model = MonitoringProfile
    fields = (("name", 100), ("description", 500), ("comments", 5000))
    display_attrs = ("status", "description")


@register_search
class MonitoringCheckKeyIndex(SearchIndex):
    model = MonitoringCheckKey
    fields = (("name", 100), ("description", 500), ("comments", 5000))
    display_attrs = ("check_type", "description")


@register_search
class MonitoringCheckRuleIndex(SearchIndex):
    model = MonitoringCheckRule
    fields = (("key", 100), ("target", 200), ("description", 500), ("comments", 5000))
    display_attrs = ("profile", "check_type", "target", "enabled")


@register_search
class MonitoringAssetOverrideIndex(SearchIndex):
    model = MonitoringAssetOverride
    fields = (("key", 100), ("reason", 500), ("ticket", 500), ("comments", 5000))
    display_attrs = ("operation", "expires_at", "enabled")


@register_search
class MonitoringProfileAssignmentIndex(SearchIndex):
    model = MonitoringProfileAssignment
    fields = (("profile", 100), ("description", 500), ("comments", 5000))
    display_attrs = ("profile", "weight", "enabled")


indexes = (
    MonitoringProfileAssignmentIndex,
    MonitoringProfileIndex,
    MonitoringCheckKeyIndex,
    MonitoringCheckRuleIndex,
    MonitoringAssetOverrideIndex,
)
