"""Resolve desired monitoring configuration with explicit provenance."""

import hashlib
import json
from copy import deepcopy

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from .monitoring_models import MonitoringAssetOverride, MonitoringCheckRule, MonitoringProfile
from .monitoring_schema import PROFILE_FIELD, changed_parameters, validate_check


def resolve_monitoring(asset, user, now=None):
    now = now or timezone.now()
    if not type(asset).objects.restrict(user, "view").filter(pk=asset.pk).exists():
        raise PermissionDenied("View permission is required for the asset.")
    profile_id = asset.custom_field_data.get(PROFILE_FIELD)
    result = {
        "schema_version": 1,
        "asset": {"object_type": asset._meta.label_lower, "id": asset.pk, "name": str(asset)},
        "configured": profile_id is not None,
        "profile": None,
        "checks": [],
    }
    if profile_id is None:
        return result
    profile = MonitoringProfile.objects.restrict(user, "view").filter(pk=profile_id).first()
    if profile is None:
        raise PermissionDenied("The monitoring profile is missing or not visible.")
    if not profile.accepts(asset):
        raise ValidationError("The monitoring profile is incompatible with this asset.")
    rules = list(MonitoringCheckRule.objects.restrict(user, "view").filter(profile=profile).order_by("key"))
    if len(rules) != profile.checks.count():
        raise PermissionDenied("A complete configuration requires view permission for every profile check.")
    ct = ContentType.objects.get_for_model(asset)
    active = MonitoringAssetOverride.objects.filter(
        profile=profile,
        assigned_object_type=ct,
        assigned_object_id=asset.pk,
        enabled=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    overrides = list(active.restrict(user, "view").select_related("rule").order_by("key"))
    if len(overrides) != active.count():
        raise PermissionDenied("A complete configuration requires view permission for every active exception.")
    checks = {}
    for rule in rules:
        validate_check(rule.check_type, rule.target, rule.parameters)
        checks[rule.key] = {
            "key": rule.key,
            "check_type": rule.check_type,
            "target": rule.target,
            "parameters": deepcopy(rule.parameters),
            "enabled": rule.enabled,
            "source": {"profile_id": profile.pk, "rule_id": rule.pk},
        }
    for override in overrides:
        if override.operation == "add":
            if override.key in checks:
                raise ValidationError(f"Exception key collision: {override.key}.")
            checks[override.key] = {
                "key": override.key,
                "check_type": override.check_type,
                "target": override.target,
                "parameters": deepcopy(override.parameters),
                "enabled": True,
                "source": {"profile_id": profile.pk},
            }
        else:
            check = checks.get(override.key)
            if check is None or check["source"]["rule_id"] != override.rule_id:
                raise ValidationError("An exception refers to a missing or different profile check.")
            if override.operation == "disable":
                check["enabled"] = False
            else:
                check["parameters"] = changed_parameters(check["parameters"], override.parameters)
        check = checks[override.key]
        validate_check(check["check_type"], check["target"], check["parameters"])
        check["source"].update(
            {
                "override_id": override.pk,
                "operation": override.operation,
                "changed_parameters": sorted(override.parameters),
                "reason": override.reason,
                "ticket": override.ticket,
                "expires_at": override.expires_at.isoformat() if override.expires_at else None,
            }
        )
    result["profile"] = {"id": profile.pk, "name": profile.name, "selectable": profile.selectable}
    result["checks"] = [checks[key] for key in sorted(checks)]
    # Hash the desired behavior, excluding explanations, database IDs and expiry
    # timestamps. Expiry affects the hash when the resulting behavior changes.
    behavior = [{k: v for k, v in check.items() if k != "source"} for check in result["checks"]]
    result["config_hash"] = hashlib.sha256(
        json.dumps(behavior, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result
