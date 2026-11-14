"""Compose weighted profile checks and asset exceptions without mutating them."""

from copy import deepcopy

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .monitoring_schema import changed_parameters, validate_check


def _visible(objects, model, user, description):
    if user is None:
        return objects
    ids = {obj.pk for obj in objects}
    visible = set(model.objects.restrict(user, "view").filter(pk__in=ids).values_list("pk", flat=True))
    if visible != ids:
        raise PermissionDenied(f"A complete configuration requires view permission for every {description}.")
    return objects


def compose(asset, user=None, now=None, candidate=None, deleted=None, include_overrides=True):
    from .monitoring_models import (
        MonitoringAssetOverride,
        MonitoringCheckRule,
        MonitoringProfile,
        MonitoringProfileAssignment,
    )

    now = now or timezone.now()
    deleted_objects = list(deleted) if deleted is not None and not hasattr(deleted, "_meta") else [deleted]
    ct = ContentType.objects.get_for_model(asset)
    identity = (ct.pk, asset.pk)
    assignments = list(
        MonitoringProfileAssignment.objects.filter(
            assigned_object_type=ct,
            assigned_object_id=asset.pk,
        ).select_related("profile")
    )
    if isinstance(candidate, MonitoringProfileAssignment):
        assignments = [obj for obj in assignments if obj.pk != candidate.pk]
        if (candidate.assigned_object_type_id, candidate.assigned_object_id) == identity:
            assignments.append(candidate)
    removed_assignments = {obj.pk for obj in deleted_objects if isinstance(obj, MonitoringProfileAssignment)}
    assignments = [obj for obj in assignments if obj.pk not in removed_assignments]
    assignments = sorted((obj for obj in assignments if obj.enabled), key=lambda obj: (-obj.weight, obj.profile_id))
    _visible(assignments, MonitoringProfileAssignment, user, "active profile assignment")
    profiles = [assignment.profile for assignment in assignments]
    _visible(profiles, MonitoringProfile, user, "assigned profile")
    for profile in profiles:
        if not profile.accepts(asset):
            raise ValidationError(f"Profile {profile.name} is incompatible with this asset.")
    rules = list(MonitoringCheckRule.objects.filter(profile_id__in=[p.pk for p in profiles]).select_related("key"))
    if isinstance(candidate, MonitoringCheckRule):
        rules = [obj for obj in rules if obj.pk != candidate.pk]
        if candidate.profile_id in {p.pk for p in profiles}:
            rules.append(candidate)
    removed_rules = {obj.pk for obj in deleted_objects if isinstance(obj, MonitoringCheckRule)}
    rules = [obj for obj in rules if obj.pk not in removed_rules]
    _visible(rules, MonitoringCheckRule, user, "profile check and key")
    by_profile = {assignment.profile_id: assignment for assignment in assignments}
    candidates = {}
    for rule in rules:
        validate_check(rule.check_type, rule.target, rule.parameters)
        assignment = by_profile[rule.profile_id]
        check = {
            "key": rule.key.name,
            "check_type": rule.check_type,
            "target": rule.target,
            "parameters": deepcopy(rule.parameters),
            "enabled": rule.enabled,
        }
        candidates.setdefault(rule.key.name, []).append((assignment, rule, check))
    checks = {}
    for key, variants in candidates.items():
        highest = max(assignment.weight for assignment, _, _ in variants)
        winners = [(a, r, c) for a, r, c in variants if a.weight == highest]
        first = winners[0][2]
        if any(check != first for _, _, check in winners[1:]):
            names = ", ".join(sorted(assignment.profile.name for assignment, _, _ in winners))
            raise ValidationError(
                f"Conflicting definitions for {key} at weight {highest}: {names}. Use distinct weights."
            )
        assignment, rule, check = sorted(winners, key=lambda item: item[0].profile_id)[0]
        check["source"] = {
            "profile_id": assignment.profile_id,
            "profile_name": assignment.profile.name,
            "assignment_id": assignment.pk,
            "weight": assignment.weight,
            "rule_id": rule.pk,
        }
        checks[key] = check
    if include_overrides:
        overrides = list(
            MonitoringAssetOverride.objects.filter(
                assigned_object_type=ct,
                assigned_object_id=asset.pk,
            ).select_related("key")
        )
        if isinstance(candidate, MonitoringAssetOverride):
            overrides = [obj for obj in overrides if obj.pk != candidate.pk]
            if (candidate.assigned_object_type_id, candidate.assigned_object_id) == identity:
                overrides.append(candidate)
        overrides = [obj for obj in overrides if obj.enabled and (obj.expires_at is None or obj.expires_at > now)]
        _visible(overrides, MonitoringAssetOverride, user, "active exception and key")
        if overrides and not assignments:
            raise ValidationError("Active asset exceptions require at least one enabled profile assignment.")
        for override in sorted(overrides, key=lambda obj: obj.key.name):
            key = override.key.name
            if override.operation == "add":
                if key in checks:
                    raise ValidationError(f"Exception key collision: {key}.")
                if any(
                    c["check_type"] == override.check_type and c["target"] == override.target for c in checks.values()
                ):
                    raise ValidationError(f"An effective check already monitors target {override.target}.")
                checks[key] = {
                    "key": key,
                    "check_type": override.check_type,
                    "target": override.target,
                    "parameters": deepcopy(override.parameters),
                    "enabled": True,
                    "source": {},
                }
            else:
                if key not in checks:
                    raise ValidationError(f"Active exception {key} requires a matching effective profile check.")
                if override.operation == "disable":
                    checks[key]["enabled"] = False
                else:
                    checks[key]["parameters"] = changed_parameters(checks[key]["parameters"], override.parameters)
            check = checks[key]
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
    return assignments, [checks[key] for key in sorted(checks)]


def validate_composition(asset, candidate=None, deleted=None):
    try:
        compose(asset, candidate=candidate, deleted=deleted)
    except ValidationError as error:
        from .monitoring_permissions import monitoring_request

        request = monitoring_request.get()
        if request:
            try:
                compose(asset, user=request.user)
            except PermissionDenied:
                raise ValidationError(
                    "This change conflicts with existing monitoring configuration or active exceptions. "
                    "Ask a user with permission to view the complete monitoring configuration to review it."
                ) from error
            except ValidationError:
                pass
        raise
