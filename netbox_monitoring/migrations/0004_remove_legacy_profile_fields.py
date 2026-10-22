from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_monitoring", "0003_convert_profile_scope"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="monitoringprofile",
            name="asset_type",
        ),
        migrations.RemoveField(
            model_name="monitoringprofile",
            name="selectable",
        ),
    ]
