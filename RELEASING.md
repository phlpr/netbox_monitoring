# Releasing netbox-monitoring

Publishing follows the same flow as netbox-geoview: GitHub Actions builds and tests
the package, publishes with Trusted Publishing, and creates a GitHub release from
the tagged changelog entry after a successful PyPI upload.

## One-time setup

Configure a Pending Trusted Publisher in each index's account publishing settings
when the project does not exist yet. The first successful upload creates it.

| Setting | PyPI | TestPyPI |
| --- | --- | --- |
| Project | `netbox-monitoring` | `netbox-monitoring` |
| GitHub owner | `phlpr` | `phlpr` |
| Repository | `netbox_monitoring` | `netbox_monitoring` |
| Workflow filename | `publish-pypi.yml` | `publish-testpypi.yml` |
| GitHub environment | `pypi` | `testpypi` |

Create/use the matching GitHub environments and any desired deployment rules.
Authentication uses GitHub OIDC; publishing jobs alone receive `id-token: write`.
No long-lived PyPI API token is required. TestPyPI and PyPI are separate indices.

## Prepare a release

1. Select a new unpublished version and update `netbox_monitoring/version.py`.
2. Update README.md and COMPATIBILITY.md for the exact tested support scope.
3. Move changes from `## Unreleased` into exactly one nonempty
   `## X.Y.Z - YYYY-MM-DD` changelog section matching the package version.
4. Run the plugin suite with `scripts/test.sh` on supported NetBox versions and
   the browser checks documented in the README when affected flows change.
5. Build and validate fresh distributions (use an empty output directory):

   ```bash
   python -m build
   python -m twine check --strict dist/*
   python scripts/check_distribution.py
   python scripts/release_notes.py v0.1.0 \
     --repository phlpr/netbox_monitoring \
     --version-file netbox_monitoring/version.py \
     --output /tmp/monitoring-release-notes.md
   ```

6. Push the release preparation commits, wait for green CI, and merge to `main`.

## CI

`Tests` runs on pull requests and pushes to `main` and is reusable by publishing
workflows. It validates Python/JavaScript and release tooling, builds one wheel
and sdist, checks their metadata/resources, and tests that wheel on the matrix
in COMPATIBILITY.md. Publishing downloads the same tested `dist` artifact.

The integration jobs use dedicated PostgreSQL/Redis services and install the
wheel without editable mode. Their copied tests and scripts run outside the source
checkout. Migration drift, weighted assignments, static collection, and the smoke test
must also pass. This is distinct from GeoView's lightweight unit-only CI.

## TestPyPI

Run `Publish to TestPyPI` manually from GitHub Actions on `main` after it contains
the workflow. It runs all checks before uploading the distributions.

Install the exact version in a disposable NetBox environment with its normal
dependencies already installed:

```bash
python -m pip install --no-deps --index-url https://test.pypi.org/simple/ \
  netbox-monitoring==0.1.0
```

Run NetBox migrations, `check`, `setup_monitoring_fields --apply`, and
`collectstatic --no-input`. Use the isolated configuration in `tests/configuration.py`
and execute `tests.wheel_smoke.verify_install()` through `manage.py shell`.
Verify imports resolve to `site-packages` and compare downloaded distribution
hashes with the workflow's `dist` artifact. Keep the live development database and
editable environment separate from this verification.

If uploading succeeds but a later operation fails, rerun failed jobs rather than
uploading the same files again. Both indices reject reused distribution filenames.

## PyPI and GitHub release

After the TestPyPI check, create and push `vX.Y.Z` only when the production release
is intended. `Publish to PyPI` checks the full suite plus tag/version/changelog
agreement, uploads the tested distributions, then creates the GitHub release from
the validated changelog section. Existing GitHub releases are left unchanged.

The initial release has no previous-version comparison link. Later releases link
to the preceding version in the changelog. No production release is triggered
by merging code or running the TestPyPI workflow.
