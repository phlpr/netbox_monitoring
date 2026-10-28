"""Monitoring catalogue and exception filters."""

import django_filters
from django.db.models import Q
from django.utils import timezone
from netbox.filtersets import NetBoxModelFilterSet

from .models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)


class MonitoringProfileFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = MonitoringProfile
        fields = ("id", "name", "status", "object_types", "platform")

    def search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value.strip()) | Q(description__icontains=value.strip()))


class MonitoringCheckKeyFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = MonitoringCheckKey
        fields = ("id", "name", "check_type")

    def search(self, queryset, name, value):
        return queryset.filter(Q(name__icontains=value.strip()) | Q(description__icontains=value.strip()))


class MonitoringCheckRuleFilterSet(NetBoxModelFilterSet):
    check_type = django_filters.CharFilter(field_name="key__check_type")
    key_id = django_filters.ModelMultipleChoiceFilter(field_name="key", queryset=MonitoringCheckKey.objects.all())
    profile_id = django_filters.ModelMultipleChoiceFilter(
        field_name="profile", queryset=MonitoringProfile.objects.all()
    )

    class Meta:
        model = MonitoringCheckRule
        fields = ("id", "profile_id", "key_id", "target", "enabled")

    def search(self, queryset, name, value):
        return queryset.filter(
            Q(key__name__icontains=value.strip())
            | Q(target__icontains=value.strip())
            | Q(description__icontains=value.strip())
        )


class MonitoringAssetOverrideFilterSet(NetBoxModelFilterSet):
    key_id = django_filters.ModelMultipleChoiceFilter(field_name="key", queryset=MonitoringCheckKey.objects.all())
    active = django_filters.BooleanFilter(method="filter_active")

    class Meta:
        model = MonitoringAssetOverride
        fields = ("id", "assigned_object_type", "assigned_object_id", "key_id", "operation", "enabled")

    def filter_active(self, queryset, name, value):
        condition = Q(enabled=True) & (Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        return queryset.filter(condition) if value else queryset.exclude(condition)

    def search(self, queryset, name, value):
        return queryset.filter(
            Q(key__name__icontains=value.strip())
            | Q(reason__icontains=value.strip())
            | Q(ticket__icontains=value.strip())
        )


class MonitoringProfileAssignmentFilterSet(NetBoxModelFilterSet):
    profile_id = django_filters.ModelMultipleChoiceFilter(
        field_name="profile", queryset=MonitoringProfile.objects.all()
    )

    class Meta:
        model = MonitoringProfileAssignment
        fields = ("id", "profile_id", "assigned_object_type", "assigned_object_id", "weight", "enabled")

    def search(self, queryset, name, value):
        return queryset.filter(Q(profile__name__icontains=value.strip()) | Q(description__icontains=value.strip()))
