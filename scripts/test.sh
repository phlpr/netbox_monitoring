#!/usr/bin/env bash
set -euo pipefail

: "${NETBOX_ROOT:?Set NETBOX_ROOT to a NetBox source checkout containing netbox/manage.py}"
plugin_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${plugin_root}:${NETBOX_ROOT}/netbox${PYTHONPATH:+:${PYTHONPATH}}"
export NETBOX_CONFIGURATION=tests.configuration
exec "${PYTHON:-python}" "${NETBOX_ROOT}/netbox/manage.py" test tests --keepdb --noinput "$@"
