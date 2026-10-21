"""Standard NetBox monitoring tables."""

import json

import django_tables2 as tables
from netbox.tables import PrimaryModelTable, columns

from .models import MonitoringAssetOverride, MonitoringCheckRule, MonitoringProfile


class MonitoringProfileTable(PrimaryModelTable):
    name = tables.Column(linkify=True)
    selectable = columns.BooleanColumn()
    platform = tables.Column(linkify=True)

    class Meta(PrimaryModelTable.Meta):
        model = MonitoringProfile
        fields = (
            "pk",
            "id",
            "name",
            "description",
            "selectable",
            "asset_type",
            "platform",
            "owner",
            "comments",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("name", "description", "selectable", "asset_type", "platform")


class MonitoringCheckRuleTable(PrimaryModelTable):
    key = tables.Column(linkify=True)
    profile = tables.Column(linkify=True)
    enabled = columns.BooleanColumn()
    parameters = tables.Column()

    def render_parameters(self, value):
        return json.dumps(value, sort_keys=True)

    def value_parameters(self, value):
        return json.dumps(value, sort_keys=True)

    class Meta(PrimaryModelTable.Meta):
        model = MonitoringCheckRule
        fields = (
            "pk",
            "id",
            "profile",
            "key",
            "check_type",
            "target",
            "parameters",
            "enabled",
            "description",
            "comments",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("profile", "key", "check_type", "target", "enabled")


class MonitoringAssetOverrideTable(PrimaryModelTable):
    key = tables.Column(linkify=True)
    profile = tables.Column(linkify=True)
    rule = tables.Column(linkify=True)
    enabled = columns.BooleanColumn()

    class Meta(PrimaryModelTable.Meta):
        model = MonitoringAssetOverride
        fields = (
            "pk",
            "id",
            "profile",
            "key",
            "assigned_object_type",
            "assigned_object_id",
            "operation",
            "rule",
            "check_type",
            "target",
            "parameters",
            "reason",
            "ticket",
            "expires_at",
            "enabled",
            "comments",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = (
            "profile",
            "key",
            "assigned_object_type",
            "assigned_object_id",
            "operation",
            "reason",
            "expires_at",
            "enabled",
        )

    def value_parameters(self, value):
        return json.dumps(value, sort_keys=True)
