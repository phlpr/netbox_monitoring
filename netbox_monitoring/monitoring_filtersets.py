"""Monitoring catalogue and exception filters."""

import django_filters
from django.db.models import Q
from django.utils import timezone
from netbox.filtersets import NetBoxModelFilterSet

from .models import MonitoringAssetOverride, MonitoringCheckRule, MonitoringProfile


class MonitoringProfileFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = MonitoringProfile
        fields = ("id", "name", "status", "object_types", "platform")

    def search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value.strip()) | Q(description__icontains=value.strip()))


class MonitoringCheckRuleFilterSet(NetBoxModelFilterSet):
    profile_id = django_filters.ModelMultipleChoiceFilter(
        field_name="profile", queryset=MonitoringProfile.objects.all()
    )

    class Meta:
        model = MonitoringCheckRule
        fields = ("id", "profile_id", "key", "check_type", "target", "enabled")

    def search(self, queryset, name, value):
        return queryset.filter(
            Q(key__icontains=value.strip())
            | Q(target__icontains=value.strip())
            | Q(description__icontains=value.strip())
        )


class MonitoringAssetOverrideFilterSet(NetBoxModelFilterSet):
    profile_id = django_filters.ModelMultipleChoiceFilter(
        field_name="profile", queryset=MonitoringProfile.objects.all()
    )
    active = django_filters.BooleanFilter(method="filter_active")

    class Meta:
        model = MonitoringAssetOverride
        fields = ("id", "profile_id", "assigned_object_type", "assigned_object_id", "key", "operation", "enabled")

    def filter_active(self, queryset, name, value):
        condition = Q(enabled=True) & (Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        return queryset.filter(condition) if value else queryset.exclude(condition)

    def search(self, queryset, name, value):
        return queryset.filter(
            Q(key__icontains=value.strip()) | Q(reason__icontains=value.strip()) | Q(ticket__icontains=value.strip())
        )
