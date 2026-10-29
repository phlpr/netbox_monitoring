"""Standard NetBox monitoring tables."""

import json

import django_tables2 as tables
from netbox.tables import PrimaryModelTable, columns

from .models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)


class MonitoringProfileTable(PrimaryModelTable):
    name = tables.Column(linkify=True)
    status = columns.ChoiceFieldColumn()
    object_types = columns.ContentTypesColumn()
    platform = tables.Column(linkify=True)

    class Meta(PrimaryModelTable.Meta):
        model = MonitoringProfile
        fields = (
            "pk",
            "id",
            "name",
            "description",
            "status",
            "object_types",
            "platform",
            "owner",
            "comments",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("name", "status", "object_types", "platform", "description")


class MonitoringCheckKeyTable(PrimaryModelTable):
    name = tables.Column(linkify=True)

    class Meta(PrimaryModelTable.Meta):
        model = MonitoringCheckKey
        fields = (
            "pk",
            "id",
            "name",
            "description",
            "check_type",
            "owner",
            "comments",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("name", "description", "check_type")


class MonitoringCheckRuleTable(PrimaryModelTable):
    key = tables.Column(linkify=lambda record: record.get_absolute_url())
    check_type = tables.Column(order_by="key__check_type")
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
    key = tables.Column(linkify=lambda record: record.get_absolute_url())
    check_type = tables.Column(order_by="key__check_type")
    enabled = columns.BooleanColumn()

    class Meta(PrimaryModelTable.Meta):
        model = MonitoringAssetOverride
        fields = (
            "pk",
            "id",
            "key",
            "assigned_object_type",
            "assigned_object_id",
            "operation",
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


class MonitoringProfileAssignmentTable(PrimaryModelTable):
    profile = tables.Column(linkify=True)
    assigned_object = tables.Column(linkify=True, orderable=False)
    weight = tables.Column(linkify=lambda record: record.get_absolute_url())
    enabled = columns.BooleanColumn()

    class Meta(PrimaryModelTable.Meta):
        model = MonitoringProfileAssignment
        fields = (
            "pk",
            "id",
            "assigned_object",
            "assigned_object_type",
            "assigned_object_id",
            "profile",
            "weight",
            "enabled",
            "description",
            "owner",
            "comments",
            "created",
            "last_updated",
            "actions",
        )
        default_columns = ("assigned_object", "profile", "weight", "enabled", "description")
