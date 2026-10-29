# Changelog

All notable changes to NetBox Monitoring are documented here.

## Unreleased

## 0.2.0 - 2026-10-29

First production PyPI release. Version 0.1.0 was published on TestPyPI only.

### Added

- Replace the native profile selector with plugin-owned weighted assignments and
  a Monitoring profiles card on supported object detail pages.
- Combine multiple profiles deterministically: higher weights select entire check
  definitions; conflicting definitions at equal weights are rejected.
- Let asset editors manage assignments with native assignment and asset permissions.
- Apply asset exceptions by stable check key after profile composition.
- Export schema version 2 with assignment weights and winning check provenance.

### Fixed

- Revalidate current profile status, key type, asset platform, and prefetched
  dependencies under the configuration write lock.
- Bind asset-scoped assignment and exception forms to their target on the server,
  including previews and Add Another, and hide target fields and their labels.

### Upgrade notes

- Back up the database, stop application processes/workers, run migrations, collect
  static files, and restart with the upgraded plugin.
- Migrate existing selector values to enabled assignments at weight 100, preserving
  behavior and removing the native field and its JSON values. Invalid legacy data
  causes an explicit migration error. The old setup command no longer creates fields.
- Update adapters for multiple `profiles`; singular `profile` is null when multiple
  assignments are enabled. Exception writes use asset/key instead of profile/rule.
- Downgrade requires assignments representable by the previous single selector;
  otherwise restore the matching database backup and plugin version.

## 0.1.0 (TestPyPI only) - 2026-10-28

### Added

- Extract monitoring configuration from AESAI into an independent NetBox plugin.
- Maintain reusable profiles with native statuses, object types, platform scope,
  ownership, tags, comments, custom fields, journals, and change logging.
- Maintain a unique check key catalog for disk, CPU, memory, DNS, and process checks.
- Apply justified per-asset change, add, and disable exceptions with expiry.
- Resolve complete configurations with provenance and deterministic behavior hashes.
- Support public custom-field object types with native monitoring tabs, profile
  selection, exception actions, discovery, impact reporting, and config APIs.
- Provide CRUD, imports, bulk operations, search, previews, permission validation,
  assignment protection, and reversible standalone-plugin migrations.
- Add CI testing the built wheel on NetBox 4.6.10 and 4.7.0, manual TestPyPI
  publishing, tag-based PyPI publishing, and changelog-based GitHub release notes.

### Compatibility

- Require Python 3.12 or later and NetBox 4.6.10 or later. Validated NetBox versions
  and test scope are documented in COMPATIBILITY.md.
- Keep inherited owner field metadata consistent across NetBox 4.6 and 4.7.

### Upgrade notes

- Run NetBox migrations, collect static files, and apply `setup_monitoring_fields`.
- Existing standalone development profiles, checks, exceptions, and assignments
  are preserved. Disabled profiles block new assignments only.
- Migration of legacy AESAI tables and removal of its monitoring integration are
  separate steps; see the README before an AESAI cutover.
