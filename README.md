# NetBox Monitoring

Manage desired monitoring configuration in NetBox using reusable profiles, typed
checks, and justified exceptions for individual NetBox objects.

Configure monitoring independently of a specific backend, using central
maintenance permissions, plugin-owned profile assignments, and a shared check key
catalog. External adapters consume the configuration and apply it to a
monitoring backend.

## Status and compatibility

Release version: **0.2.0** (weighted profile assignments). Minimum NetBox version: **4.6.10**.
Python **3.12 or later** is required. Integration tests pass on NetBox **4.6.10** and **4.7.0** with PostgreSQL and Redis.
Browser flows are verified on 4.7.0. Other versions have not yet been verified.

GitHub Actions tests the built package and publishes through Trusted Publishing.
See [RELEASING.md](RELEASING.md) for the manual TestPyPI and tag-based PyPI flows,
[CHANGELOG.md](CHANGELOG.md) for release notes, and
[COMPATIBILITY.md](COMPATIBILITY.md) for the validation scope.
Monitoring adapters, check execution, credentials, deployment, and observed state
are outside this initial implementation.

## Features

- Multiple monitoring profiles per asset, managed in a dedicated Monitoring profiles
  card on object detail pages. Assignments have a weight (default 100) and an enabled flag.
  No native custom field is created.
- Profiles restricted by native Object type(s) and optional platform. Retired profiles can
  remain effective for existing assignments while being hidden from new choices.
- A globally unique check key catalog with descriptions and a single check type
  per key, shared across profiles and exceptions.
- Disk, CPU, memory, DNS, and process/service checks with validated JSON parameters
  and human-readable forms.
- Per-asset `change`, `add`, and `disable` exceptions, with a required reason,
  optional ticket, expiry, and enable/disable control.
- A deterministic resolver with provenance and a configuration hash. It rejects
  exports when the caller cannot read every relevant rule or active exception.
- UI lists, detail pages, editing, change previews, bulk editing/deletion, imports,
  global search, and Monitoring tabs on supported objects with an
  authorized Add asset Exception button prefilled for the current asset.
- Native tags, comments, custom fields, journals, and changelog integration.
- REST CRUD, profile impact reporting, monitored-asset discovery, and per-asset
  effective configuration endpoints.
- Protection against invalid scope changes, duplicate checks, deleting referenced
  assigned profiles, and changes that would invalidate active exceptions or create
  conflicting definitions at equal weights.

Profiles compose through weighted assignments; there is no separate revision
model. Saved changes immediately change the desired configuration. An external
adapter is responsible for applying that configuration to a monitoring backend.

## Install in NetBox

Use the same virtual environment as NetBox:

```bash
/opt/netbox/venv/bin/pip install netbox-monitoring
```

For development, install a local checkout in editable mode:

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

Restart your NetBox application and workers using your normal service procedure.
The plugin UI is under `/plugins/monitoring/`. Open an object's detail page and use
**Monitoring profiles → Assign profile** to select a profile and weight. Supported
objects are public, installed NetBox and plugin models supporting custom fields;
the plugin's own configuration models are excluded. No selector setup is needed.
`setup_monitoring_fields` is a deprecated compatibility command that makes no changes.

### Upgrade from 0.1.x

Back up the database and stop application processes and workers before upgrading.
Run migrations, collect static files, and restart them with the new plugin version.
The migration converts existing `monitoring_profile` values into enabled profile
assignments with weight **100**, including existing selections of disabled profiles.
It preserves unrelated custom field values, removes the old selector and its JSON
values, and retains existing asset exceptions. Invalid profile references, scope
mismatches, unrelated fields with the same name, or duplicate exceptions for an
asset/key stop the migration with an error so they can be corrected without losing data.

Adapters must support **schema version 2** before this upgrade. The `profiles` list
replaces the assumption of a single profile. A compatibility `profile` object is
included only when exactly one enabled assignment exists; otherwise it is `null`.
Exceptions now select an asset and key, without a profile or base-rule reference.
Old profile/rule IDs are retained internally as optional historical provenance.
Single-profile behavior and `config_hash` remain unchanged by the migration.

A downgrade can restore the selector only while assignments still fit the old
single-profile model (enabled, weight 100, one per asset) and exceptions can be
represented by its rules. Otherwise restore the database backup together with the
old plugin version. Disabling the plugin hides its card and leaves only plugin-owned
assignment records; it creates no selector remnants in native custom fields.

## Permissions

Create the configured **Monitoring Administrators** group in NetBox and grant its
members the appropriate native model/object permissions for:

- `netbox_monitoring.monitoringprofile`
- `netbox_monitoring.monitoringcheckkey`
- `netbox_monitoring.monitoringcheckrule`
- `netbox_monitoring.monitoringassetoverride`

Central group membership and native permissions are both required for UI and API
writes to these catalogue and exception models. Group membership alone grants no object access. Superusers retain access.
Read permissions on related platforms, profiles, checks, and assets are also
validated where applicable.

Asset editors manage assignments with view/change permission on the target asset,
view permission on the selected profile, and the appropriate add/change/delete
permission on `netbox_monitoring.monitoringprofileassignment`. They do not need
membership in the central maintenance group. Assignment reads also require access
to the asset and profile. Give adapter accounts view permissions on the assets,
active assignments, profiles, check keys, all profile checks, and all active exceptions
they must export.
A missing permission results in an error instead of a partial configuration.

The configured group and permission grants are managed by the administrator; neither is created automatically.

Profile status uses the native NetBox choice format with `active` (green) and
`disabled` (gray). It can be configured through
`FIELD_CHOICES["netbox_monitoring.MonitoringProfile.status"]`. Object type selection
uses the native multi-select for all supported object types, including Devices,
Virtual Machines, Sites, Racks, Interfaces, and IP Addresses. New profiles initially
select Devices and Virtual Machines; choose the types appropriate to the profile.
The optional platform filter applies only to objects with a platform field.
Existing `selectable` and `asset_type` values are migrated automatically without
changing asset assignments. Ownership is rendered in the native Ownership section.

## Configuration example

Create a Check Key named `disk.all`, select type `disk`, and describe its purpose.
The type determines parameter validation and form fields. Referenced keys cannot
change their stable name or type; descriptions remain editable. The same key can
be used by multiple profiles.

Create the profile `Linux Standard`, then add a rule referencing that key (the
REST API accepts its ID or a lookup such as `{"name": "disk.all"}`):

```json
{
  "key": {"name": "disk.all"},
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

Keys identify rules and exception references. Key names are globally unique;
select them from Check Keys instead of entering free text. Check type is stored
only on the key and exposed as a derived, read-only API field on rules and
exceptions. The resolved export keeps string key names and the check type. Targets identify what is checked.
Changes merge only at the top parameter level; lists are replaced in full. A
`change` cannot alter type or target. An `add` selects its own catalog key and target;
`disable` selects a key in the effective profile configuration and carries no parameter changes.

### Multiple profiles and weights

Checks with different keys combine. For the same key, the assignment with the
**highest weight** supplies the complete check definition, including target,
parameters, and enabled state. Parameters from different profiles are not blended.
At equal highest weights, identical definitions are accepted; different definitions
are rejected as a conflict. Increasing the weight resolves the conflict explicitly.
Asset exceptions are applied afterwards, by key, to the winning check.

For example, assign `Linux Standard` at weight 100 (`disk.all`: Warning 80,
Critical 90) and `Database Servers` at weight 200 (`disk.all`: Warning 85,
Critical 95 plus `process.postgres`). The asset receives the database disk check
and the additional process check. An asset exception `{"warning": 88}` then changes
only Warning to 88 while Critical remains 95. Removing the database assignment
falls back to the standard disk check, followed by the same asset exception.

Disabling an assignment removes that profile from composition. Profile status
`disabled` only blocks new assignments; existing assignments keep working.
Active change/disable exceptions require a matching effective check. Assignment or
rule changes/deletions that would leave them without one are rejected. Disable or
remove the exception first, or provide the key through another profile.

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
/api/plugins/monitoring/monitoring-profile-assignments/
/api/plugins/monitoring/monitoring-check-keys/
/api/plugins/monitoring/monitoring-check-rules/
/api/plugins/monitoring/monitoring-asset-overrides/
/api/plugins/monitoring/assets/
/api/plugins/monitoring/assets/<app_label.model>/<id>/config/
/api/plugins/monitoring/assets/<app_label.model>/<id>/base-config/
/api/plugins/monitoring/monitoring-effective/<app_label.model>/<id>/
```

For example, use `dcim.device`, `virtualization.virtualmachine`, `dcim.site`,
or `ipam.ipaddress` as the object type.

`GET /api/plugins/monitoring/assets/` discovers configured assets visible to the
caller, with a `config_url` for each asset and limit/offset pagination. An
existing assignment to a disabled profile remains listed because its monitoring
configuration stays effective. An asset without an enabled assignment is omitted.
Each discovery entry includes the visible enabled `profiles` with assignment IDs
and weights; the config endpoint still requires access to every effective assignment.

One GET to an asset's `/config/` URL returns its fully merged configuration,
including active exceptions and provenance. It returns 404 for assets without an
enabled assignment and refuses incomplete exports when permissions are missing. The
Monitoring tab links directly to this endpoint. Existing `monitoring-effective`
URLs remain available and retain their `configured=false` response for
unconfigured assets.

The configuration endpoint returns `schema_version`, asset identity, `configured`,
`profiles` (ID, name, status, assignment ID, weight), sorted checks, and per-check
provenance (winning profile, rule, assignment, weight, and applied exception).
The `/base-config/` endpoint provides profile composition before asset exceptions
for exception forms; use `/config/` for adapter exports. Configured assets
also include `config_hash`: SHA-256 of the canonical check behavior, excluding
provenance, database IDs, reasons, tickets, and expiry timestamps. The hash changes
when expiry changes the resulting checks. An unconfigured asset returns
`configured=false`, `profiles=[]`, `profile=null`, and an empty check list.

Profile impact reports include only assets visible to the caller. The exception
API supports `active=true` / `active=false` filtering in addition to the stored
`enabled` flag. Native serializers are exposed from
`netbox_monitoring.api.serializers` for Object custom fields and NetBox events.

Existing standalone-plugin free-text keys are migrated to catalog entries.
Repeated names with the same type share an entry. A repeated name with conflicting
types stops the migration and must be resolved first. Rule/exception IDs,
parameters, and effective string key names are retained. Schema and key data
migrations support reversal.

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
account needs permission to create the test database. Set `MONITORING_TEST_DATABASE=test_netbox_monitoring_<suffix>` to isolate additional
NetBox version runs. Run tests sequentially
against these shared test services. Without a base configuration, the connection
settings from NetBox's `configuration_testing.py` are used.

Tests cover check semantics, inheritance and expiry, hashes, lifecycle protection,
permission combinations, native forms and serializers, event data, REST CRUD,
weighted assignments, conflict detection, selector migration and cleanup, imports,
previews, changelog, and monitoring tabs.
Sites and IP addresses additionally cover generic assignments, scope protection,
exceptions, config exports, discovery, and native object permissions. Templates,
migrations, management commands, and form JavaScript are included in the wheel.

`tests/browser/monitoring.cjs` also checks the native profile form, key-driven
parameter controls, the asset exception baseline, and creating a weighted assignment
from the native card with Playwright/Chromium.
`tests.browser_fixture.prepare()` and `cleanup()` provide disposable fixtures and
a private session; they refuse to run outside a `test_netbox_monitoring_` database.
Set `MONITORING_BROWSER_STATE` to a private JSON path, run a development server
against that isolated database (default browser URL: `http://127.0.0.1:8026`), then
run the script with Playwright available to Node. The fixture setup/cleanup is
invoked through NetBox's shell, and never creates accounts in the live database.

## License

[MIT](LICENSE).
