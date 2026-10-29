"""Resolve desired monitoring configuration with explicit provenance."""

import hashlib
import json

from django.core.exceptions import PermissionDenied

from .monitoring_composition import compose


def resolve_monitoring(asset, user, now=None, include_overrides=True):
    if not type(asset).objects.restrict(user, "view").filter(pk=asset.pk).exists():
        raise PermissionDenied("View permission is required for the asset.")
    assignments, checks = compose(asset, user=user, now=now, include_overrides=include_overrides)
    profiles = [
        {
            "id": assignment.profile_id,
            "name": assignment.profile.name,
            "status": assignment.profile.status,
            "assignment_id": assignment.pk,
            "weight": assignment.weight,
        }
        for assignment in assignments
    ]
    result = {
        "schema_version": 2,
        "asset": {"object_type": asset._meta.label_lower, "id": asset.pk, "name": str(asset)},
        "configured": bool(assignments),
        "profiles": profiles,
        # Compatibility for consumers of single-profile exports; use profiles in v2.
        "profile": {k: v for k, v in profiles[0].items() if k in ("id", "name", "status")}
        if len(profiles) == 1
        else None,
        "checks": checks,
    }
    if not assignments:
        return result
    behavior = [{k: v for k, v in check.items() if k != "source"} for check in checks]
    result["config_hash"] = hashlib.sha256(
        json.dumps(behavior, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result
