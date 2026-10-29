from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem

menu = PluginMenu(
    label="Monitoring",
    icon_class="mdi mdi-monitor-eye",
    groups=(
        (
            "Monitoring configuration",
            tuple(
                PluginMenuItem(
                    link=f"plugins:netbox_monitoring:{model}_list",
                    link_text=label,
                    auth_required=True,
                    permissions=(f"netbox_monitoring.view_{model}",),
                    buttons=(
                        PluginMenuButton(
                            link=f"plugins:netbox_monitoring:{model}_add",
                            title="Add",
                            icon_class="mdi mdi-plus-thick",
                            permissions=(f"netbox_monitoring.add_{model}",),
                        ),
                        PluginMenuButton(
                            link=f"plugins:netbox_monitoring:{model}_import",
                            title="Import",
                            icon_class="mdi mdi-upload",
                            permissions=(f"netbox_monitoring.add_{model}",),
                        ),
                    ),
                )
                for model, label in (
                    ("monitoringprofile", "Profiles"),
                    ("monitoringprofileassignment", "Profile Assignments"),
                    ("monitoringcheckkey", "Check Keys"),
                    ("monitoringcheckrule", "Check Rules"),
                    ("monitoringassetoverride", "Asset Exceptions"),
                )
            ),
        ),
    ),
)
