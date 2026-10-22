# NetBox Monitoring

Manage desired monitoring configuration in NetBox using reusable profiles, typed
checks, and justified exceptions for individual devices and virtual machines.

This standalone plugin extracts the monitoring functionality from
`netbox_aesai` (`0.7.0.dev2`). It retains its check parameters, resolver output,
central maintenance permissions, and native NetBox integration. It has no runtime
dependency on AESAI, Nagios, or op5.

## Status and compatibility

Initial development version: **0.1.0.dev1**. Minimum NetBox version: **4.6.10**.
Python **3.12 or later** is required. Integration tests target NetBox 4.6.10 with
PostgreSQL and Redis; newer NetBox versions have not yet been verified.

CI pipelines and PyPI publication are deferred. Install from a local checkout.
Monitoring adapters, check execution, credentials, deployment, and observed state
are outside this initial implementation.

## Features

- One optional monitoring profile per asset, selected through a native Object
  custom field when creating or editing a Device or Virtual Machine.
- Profiles restricted by native Object type(s) and optional platform. Retired profiles can
  remain effective for existing assignments while being hidden from new choices.
- Disk, CPU, memory, DNS, and process/service checks with validated JSON parameters
  and human-readable forms.
- Per-asset `change`, `add`, and `disable` exceptions, with a required reason,
  optional ticket, expiry, and enable/disable control.
- A deterministic resolver with provenance and a configuration hash. It rejects
  exports when the caller cannot read every relevant rule or active exception.
- UI lists, detail pages, editing, change previews, bulk editing/deletion, imports,
  global search, and Monitoring tabs on Devices and Virtual Machines.
- Native tags, comments, custom fields, journals, and changelog integration.
- REST CRUD, profile impact reporting, and effective configuration endpoints.
- Protection against invalid scope changes, duplicate checks, deleting referenced
  rules or assigned profiles, and switching profiles with active exceptions.

Profiles have no inheritance, multiple-profile composition, or separate revision
model. Saved changes immediately change the desired configuration. An external
adapter is responsible for applying that configuration to a monitoring backend.

## Install in NetBox

Use the same virtual environment as NetBox:

```bash
/opt/netbox/venv/bin/pip install -e /path/to/netbox_monitoring
```

Add to your existing `configuration.py` settings:

```python
PLUGINS = [
    # Other installed plugins...
    "netbox_monitoring",
]

PLUGINS_CONFIG = {
    # Other plugin settings...
    "netbox_monitoring": {
        "monitoring_admin_group": "Monitoring Administrators",
    },
}
```

Apply the plugin migration and collect its form JavaScript:

```bash
cd /opt/netbox/netbox
/opt/netbox/venv/bin/python manage.py migrate
/opt/netbox/venv/bin/python manage.py collectstatic --no-input
```

Preview the native profile selector, then create it explicitly:

```bash
/opt/netbox/venv/bin/python manage.py setup_monitoring_fields
/opt/netbox/venv/bin/python manage.py setup_monitoring_fields --apply
```

Restart your NetBox application and workers using your normal service procedure.
The plugin UI is under `/plugins/monitoring/`.

The setup command creates `monitoring_profile` as a single Object field pointing
to `netbox_monitoring.monitoringprofile`, available on `dcim.device` and
`virtualization.virtualmachine`. It has no default and assigns no profiles to
existing assets. Only profiles with status `active` appear in the selector. Profiles with status
`disabled` remain effective for existing assignments. Compatible
existing fields are left unchanged; incompatible fields cause an error.

## Permissions

Create the configured **Monitoring Administrators** group in NetBox and grant its
members the appropriate native model/object permissions for:

- `netbox_monitoring.monitoringprofile`
- `netbox_monitoring.monitoringcheckrule`
- `netbox_monitoring.monitoringassetoverride`

Central group membership and native permissions are both required for UI and API
writes. Group membership alone grants no object access. Superusers retain access.
Read permissions on related platforms, profiles, checks, and assets are also
validated where applicable.

Asset users select profiles with their normal asset permissions plus view access
to the relevant monitoring objects. Give adapter accounts view permissions on the
assets, profiles, all profile checks, and all active exceptions they must export.
A missing permission results in an error instead of a partial configuration.

The configured group and permission grants are managed by the administrator; the
setup command creates neither automatically.

Profile status uses the native NetBox choice format with `active` (green) and
`disabled` (gray). It can be configured through
`FIELD_CHOICES["netbox_monitoring.MonitoringProfile.status"]`. Object type selection
uses the native multi-select, currently supporting Devices and Virtual Machines.
Existing `selectable` and `asset_type` values are migrated automatically without
changing asset assignments. Ownership is rendered in the native Ownership section.

## Configuration example

Create the profile `Linux Standard`, then add a rule:

```json
{
  "key": "disk.all",
  "check_type": "disk",
  "target": "*",
  "parameters": {
    "metric": "used_percent",
    "warning": 80,
    "critical": 90,
    "exclude_paths": []
  },
  "enabled": true
}
```

Assign that profile to two VMs. For one VM, add a `change` exception referencing
`disk.all` with parameters `{"warning": 85}` and a reason. That VM uses Warning 85
and Critical 90. A subsequent change of the profile's Critical threshold is
inherited by both VMs, while the exception's explicit Warning remains 85.

Keys identify rules and exception references. Targets identify what is checked.
Changes merge only at the top parameter level; lists are replaced in full. A
`change` cannot alter type or target. An `add` supplies its own type and target;
`disable` references an existing rule and carries no parameter changes.

### Check parameters

The JSON API and imports use the following parameter names. Human forms assemble
these objects automatically. Optional parameters are marked with `?`.

| Type | Target | Parameters |
| --- | --- | --- |
| `disk` | Path, drive, or `*` | `metric`, `warning`, `critical`, `exclude_paths?` |
| `cpu` | Empty | `metric`, `warning`, `critical`, `window_seconds` |
| `memory` | Empty | `metric`, `warning`, `critical`, `window_seconds` |
| `dns` | DNS name | `record_type`, `resolver`, `expected_answers?`, `timeout_seconds`, `measurement_location` |
| `process` | Name, regex, or service | `matcher`, `min_count`, `max_count?` |

Disk metrics: `used_percent`, `free_percent`, `free_gib`. CPU metrics:
`utilization_percent`, `load_1`, `load_5`, `load_15`. Memory metrics:
`available_percent`, `available_gib`.

Usage/load thresholds require Warning < Critical; free/available metrics require
Warning > Critical. Percentages range from 0 to 100. Evaluation windows are whole
seconds from 1 to 86400. DNS resolvers are an IP address or `system`, timeouts are
whole seconds from 1 to 300, and measurement locations are `asset` or `monitor`.
Process matchers are `exact`, `regex`, or `service`; service checks require one
running service. Unknown parameters are rejected.

An exception applies only while enabled and before `expires_at`. After expiry,
the profile behavior resumes. Disabled checks remain visible with
`enabled=false` in the resolved output. Adapters need a periodic reconciliation
cycle to pick up expiry even when no NetBox object was edited.

## REST API

All endpoints require authentication and use normal NetBox API tokens:

```text
/api/plugins/monitoring/monitoring-profiles/
/api/plugins/monitoring/monitoring-profiles/<id>/impact/
/api/plugins/monitoring/monitoring-check-rules/
/api/plugins/monitoring/monitoring-asset-overrides/
/api/plugins/monitoring/monitoring-effective/dcim.device/<id>/
/api/plugins/monitoring/monitoring-effective/virtualization.virtualmachine/<id>/
```

The effective endpoint returns `schema_version`, asset identity, `configured`,
profile information, sorted checks, and per-check provenance. Configured assets
also include `config_hash`: SHA-256 of the canonical check behavior, excluding
provenance, database IDs, reasons, tickets, and expiry timestamps. The hash changes
when expiry changes the resulting checks. An unconfigured asset returns
`configured=false`, `profile=null`, and an empty check list, matching the AESAI
resolver contract.

Profile impact reports include only assets visible to the caller. The exception
API supports `active=true` / `active=false` filtering in addition to the stored
`enabled` flag. Native serializers are exposed from
`netbox_monitoring.api.serializers` for Object custom fields and NetBox events.

## Moving an existing AESAI installation

This initial extraction creates independent tables and content types. It does
**not** automatically transfer existing AESAI data or remove the monitoring code
from the original plugin. The source snapshot is left unchanged.

A production cutover needs an explicit data migration: copy profiles, rules,
exceptions, tags, and monitoring custom fields; map profile and rule IDs; update
asset selector values and the selector's related content type; and recreate
permissions for the new app label. Historical changelog records retain their
original content types. Verify resolved configurations before and after cutover.

The two monitoring implementations must not be active together: both validate the
same `monitoring_profile` field and register the same asset tab. Disable/remove
the legacy monitoring integration as part of cutover. The new setup command
refuses a selector still referencing `netbox_aesai.monitoringprofile`; it never
silently reinterprets legacy IDs as new profile IDs.

Automated legacy data migration and changes to the original AESAI plugin are
separate follow-up work.

## Development and checks

Install the plugin and development tools in an environment containing NetBox's
requirements:

```bash
python -m pip install -e '.[dev]'
ruff check netbox_monitoring tests
python -m build
```

Run native integration tests against a NetBox source checkout:

```bash
export NETBOX_ROOT=/path/to/netbox
export PYTHON=/path/to/netbox/venv/bin/python
# Optional: reuse local database/Redis connection settings without copying secrets.
export MONITORING_BASE_CONFIGURATION=/path/to/netbox/netbox/netbox/configuration.py
./scripts/test.sh -v 2
```

The test configuration always uses **test_netbox_monitoring** for the database
and Redis databases **12** and **13**, and enables only this plugin. The database
account needs permission to create the test database. Run tests sequentially
against these shared test services. Without a base configuration, the connection
settings from NetBox's `configuration_testing.py` are used.

Tests cover check semantics, inheritance and expiry, hashes, lifecycle protection,
permission combinations, native forms and serializers, event data, REST CRUD,
selector setup, imports, previews, changelog, and Device/VM tabs. Templates,
migrations, management commands, and form JavaScript are included in the wheel.

## License

[MIT](LICENSE).
