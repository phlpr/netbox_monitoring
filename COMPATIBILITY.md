# Compatibility

NetBox Monitoring 0.2.0.dev1 requires Python 3.12 or later and NetBox 4.6.10 or later.
Version numbers track plugin releases independently of NetBox.

| NetBox | Python in CI | Additional local validation |
| --- | --- | --- |
| 4.6.10 | 3.12 | Integration and migration tests on Python 3.13 |
| 4.7.0 | 3.14 | Integration, migration, and Chromium browser flows |

CI runs the complete plugin test suite against the built wheel with PostgreSQL 16
and Redis 7. It checks forward/reverse migrations, migration state, native forms
and APIs, permissions, config resolution, generic object types, weighted composition, assignment cards, and selector-to-assignment migration.
It also runs `collectstatic` and an installed-wheel smoke test covering VM/Site
configuration, exceptions, and monitoring tabs. Tests run outside the source package
to prevent a checkout from masking missing wheel files.

Other NetBox versions, database versions, and browsers have not been validated.
The plugin currently specifies a minimum NetBox version without a maximum; loading
on a later version does not establish compatibility. Validate new versions in an
isolated environment before extending the table.

The plugin stores desired monitoring configuration. Monitoring adapters, execution,
credentials, and observed state are maintained separately. Legacy AESAI migration
is not part of the standalone plugin's database migrations.
