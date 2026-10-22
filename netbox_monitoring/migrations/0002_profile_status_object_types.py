from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("netbox_monitoring", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="monitoringprofile",
            name="object_types",
            field=models.ManyToManyField(related_name="monitoring_profiles", to="contenttypes.contenttype"),
        ),
        migrations.AddField(
            model_name="monitoringprofile",
            name="status",
            field=models.CharField(default="active", max_length=50),
        ),
    ]
