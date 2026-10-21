"""Backend-independent check semantics, shared by forms, API and resolution."""

import math
import re
from copy import deepcopy
from ipaddress import ip_address

from django.core.exceptions import ValidationError

ASSET_MODELS = ("dcim.device", "virtualization.virtualmachine")
PROFILE_FIELD = "monitoring_profile"
CHECK_TYPES = (
    ("disk", "Disk space"),
    ("dns", "DNS resolution"),
    ("cpu", "CPU"),
    ("memory", "Memory"),
    ("process", "Process / service"),
)
OPERATIONS = (("change", "Change parameters"), ("add", "Add check"), ("disable", "Disable check"))
METRICS = {
    "disk": ("used_percent", "free_percent", "free_gib"),
    "cpu": ("utilization_percent", "load_1", "load_5", "load_15"),
    "memory": ("available_percent", "available_gib"),
}
RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "SRV", "PTR", "NS", "SOA")
ALLOWED = {
    "disk": {"metric", "warning", "critical", "exclude_paths"},
    "cpu": {"metric", "warning", "critical", "window_seconds"},
    "memory": {"metric", "warning", "critical", "window_seconds"},
    "dns": {"record_type", "resolver", "expected_answers", "timeout_seconds", "measurement_location"},
    "process": {"matcher", "min_count", "max_count"},
}
DEFAULTS = {
    "disk": {"metric": "used_percent", "warning": 80, "critical": 90, "exclude_paths": []},
    "cpu": {"metric": "utilization_percent", "warning": 80, "critical": 95, "window_seconds": 300},
    "memory": {"metric": "available_percent", "warning": 20, "critical": 10, "window_seconds": 300},
    "dns": {
        "record_type": "A",
        "resolver": "system",
        "expected_answers": [],
        "timeout_seconds": 5,
        "measurement_location": "asset",
    },
    "process": {"matcher": "exact", "min_count": 1, "max_count": None},
}


def fail(message):
    raise ValidationError({"parameters": message})


def number(value, name, minimum=0, maximum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{name} must be a finite number.")
    if integer and not isinstance(value, int):
        fail(f"{name} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        fail(f"{name} is outside the allowed range.")


def string_list(value, name):
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        fail(f"{name} must be a list of non-empty strings.")
    if len(value) != len(set(value)):
        fail(f"{name} contains duplicate entries.")


def validate_check(check_type, target, parameters, partial=False):
    if not isinstance(check_type, str) or check_type not in ALLOWED:
        raise ValidationError({"check_type": "Unknown monitoring check type."})
    if not isinstance(parameters, dict):
        fail("Parameters must be a JSON object.")
    if any(not isinstance(key, str) for key in parameters):
        fail("Parameter names must be strings.")
    unknown = set(parameters) - ALLOWED[check_type]
    if unknown:
        fail(f"Unknown parameters: {', '.join(sorted(unknown))}.")
    if partial:
        # Full semantic validation follows after merging with the base rule.
        if not parameters:
            fail("A parameter change must contain at least one parameter.")
        return
    required = ALLOWED[check_type] - {"exclude_paths", "expected_answers", "max_count"}
    missing = required - set(parameters)
    if missing:
        fail(f"Missing parameters: {', '.join(sorted(missing))}.")
    if not isinstance(target, str) or len(target) > 255:
        raise ValidationError({"target": "Target must be a string of at most 255 characters."})
    if check_type in ("disk", "dns", "process") and not target.strip():
        raise ValidationError({"target": "This check requires a target."})
    if check_type in ("cpu", "memory") and target:
        raise ValidationError({"target": "CPU and memory checks apply to the asset; leave target empty."})
    if check_type in METRICS:
        metric = parameters["metric"]
        if metric not in METRICS[check_type]:
            fail("The selected metric is not supported by this check type.")
        upper = 100 if metric.endswith("percent") else None
        warning, critical = parameters["warning"], parameters["critical"]
        number(warning, "Warning", maximum=upper)
        number(critical, "Critical", maximum=upper)
        low = metric.startswith(("free_", "available_"))
        if (low and warning <= critical) or (not low and warning >= critical):
            fail("Warning must exceed Critical for free/available metrics and be below Critical for used/load metrics.")
        if check_type == "disk":
            string_list(parameters.get("exclude_paths", []), "Excluded paths")
        else:
            number(parameters["window_seconds"], "Window seconds", minimum=1, maximum=86400, integer=True)
    elif check_type == "dns":
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", target):
            raise ValidationError({"target": "Enter a DNS name without whitespace or command syntax."})
        if parameters["record_type"] not in RECORD_TYPES:
            fail("Unsupported DNS record type.")
        resolver = parameters["resolver"]
        if not isinstance(resolver, str):
            fail('Resolver must be an IP address string or "system".')
        if resolver != "system":
            try:
                ip_address(resolver)
            except (ValueError, TypeError):
                fail('Resolver must be an IP address or "system".')
        string_list(parameters.get("expected_answers", []), "Expected answers")
        number(parameters["timeout_seconds"], "Timeout seconds", minimum=1, maximum=300, integer=True)
        if parameters["measurement_location"] not in ("asset", "monitor"):
            fail("Measurement location must be asset or monitor.")
    else:
        if parameters["matcher"] not in ("exact", "regex", "service"):
            fail("Process matcher must be exact, regex or service.")
        if parameters["matcher"] == "regex":
            try:
                re.compile(target)
            except re.error:
                raise ValidationError({"target": "Invalid process regular expression."})
        number(parameters["min_count"], "Minimum count", integer=True)
        maximum = parameters.get("max_count")
        if maximum is not None:
            number(maximum, "Maximum count", integer=True)
            if maximum < parameters["min_count"]:
                fail("Maximum process count must be at least the minimum.")
        if parameters["matcher"] == "service" and (parameters["min_count"] != 1 or maximum not in (None, 1)):
            fail("Service checks require a running service (minimum 1; maximum empty or 1).")


def changed_parameters(base, patch):
    result = deepcopy(base)
    result.update(deepcopy(patch))
    return result
