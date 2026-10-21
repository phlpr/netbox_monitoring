from copy import deepcopy

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from netbox_monitoring.monitoring_schema import DEFAULTS, changed_parameters, validate_check


class CheckSchemaTests(SimpleTestCase):
    def test_defaults_are_valid_for_all_five_types(self):
        for kind, target in (("disk", "*"), ("cpu", ""), ("memory", ""), ("dns", "example.com"), ("process", "sshd")):
            with self.subTest(kind=kind):
                validate_check(kind, target, deepcopy(DEFAULTS[kind]))

    def test_threshold_direction_and_percent_bounds(self):
        for metric, warning, critical in (
            ("used_percent", 90, 80),
            ("free_percent", 10, 20),
            ("used_percent", 80, 101),
            ("free_gib", 2, 2),
        ):
            with self.subTest(metric=metric):
                with self.assertRaises(ValidationError):
                    validate_check("disk", "*", {"metric": metric, "warning": warning, "critical": critical})
        validate_check("disk", "/data", {"metric": "free_gib", "warning": 10, "critical": 5})

    def test_rejects_unknown_missing_and_nonfinite_parameters(self):
        for patch in (
            {"typo": 80},
            {"warning": True},
            {"warning": float("nan")},
            {"critical": float("inf")},
            {"exclude_paths": ["/tmp", "/tmp"]},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                validate_check("disk", "*", DEFAULTS["disk"] | patch)
        with self.assertRaises(ValidationError):
            validate_check("cpu", "", {"metric": "load_1"})

    def test_cpu_memory_dns_and_process_semantics(self):
        bad_checks = (
            ("cpu", "cpu0", DEFAULTS["cpu"]),
            ("memory", "", DEFAULTS["memory"] | {"window_seconds": 0}),
            ("dns", "bad;command", DEFAULTS["dns"]),
            ("dns", "example.com", DEFAULTS["dns"] | {"resolver": "not-an-ip"}),
            ("dns", "example.com", DEFAULTS["dns"] | {"measurement_location": "anywhere"}),
            ("process", "[", DEFAULTS["process"] | {"matcher": "regex"}),
            ("process", "sshd", DEFAULTS["process"] | {"max_count": 0}),
            ("process", "sshd", DEFAULTS["process"] | {"matcher": "service", "min_count": 2}),
        )
        for kind, target, parameters in bad_checks:
            with self.subTest(kind=kind, parameters=parameters), self.assertRaises(ValidationError):
                validate_check(kind, target, parameters)

    def test_patch_is_shallow_and_does_not_mutate_inputs(self):
        base = DEFAULTS["disk"] | {"exclude_paths": ["/tmp", "/run"]}
        patch = {"exclude_paths": ["/var"]}
        result = changed_parameters(base, patch)
        self.assertEqual(result["exclude_paths"], ["/var"])
        result["exclude_paths"].append("/other")
        self.assertEqual(base["exclude_paths"], ["/tmp", "/run"])
        self.assertEqual(patch["exclude_paths"], ["/var"])
        with self.assertRaises(ValidationError):
            validate_check("disk", "*", {}, partial=True)
