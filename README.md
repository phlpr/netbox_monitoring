# NetBox Monitoring

An independent NetBox plugin for managing desired monitoring configuration using
reusable profiles, typed check rules, and justified exceptions for individual
devices and virtual machines.

The initial implementation extracts the monitoring functionality previously
developed in `netbox_aesai`. NetBox remains the source of desired configuration;
backend adapters, check execution, and deployment are separate concerns.

## Development status

Version `0.1.0.dev1` targets NetBox **4.6.10 or later** and Python **3.12 or later**.
This repository is under initial development. CI pipelines and PyPI publication
will be added separately.

## Local installation

Install this checkout into the same virtual environment as NetBox:

```bash
/opt/netbox/venv/bin/pip install -e /path/to/netbox_monitoring
```

Add the plugin to NetBox's `configuration.py`:

```python
PLUGINS = [
    # Other installed plugins...
    "netbox_monitoring",
]

PLUGINS_CONFIG = {
    "netbox_monitoring": {
        "monitoring_admin_group": "Monitoring Administrators",
    },
}
```

## License

[MIT](LICENSE).
