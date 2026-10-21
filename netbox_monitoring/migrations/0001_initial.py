import django.core.validators
import django.db.models.deletion
import netbox.models.deletion
import taggit.managers
import utilities.json
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("dcim", "0241_nullify_empty_cable_end"),
        ("extras", "0140_imageattachment_image_size"),
        ("users", "0016_default_ordering_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonitoringProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "custom_field_data",
                    models.JSONField(blank=True, default=dict, encoder=utilities.json.CustomFieldJSONEncoder),
                ),
                ("comments", models.TextField(blank=True)),
                ("description", models.TextField(blank=True)),
                ("name", models.CharField(max_length=200, unique=True)),
                ("selectable", models.BooleanField(default=True)),
                ("asset_type", models.CharField(default="any", max_length=30)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="users.owner"
                    ),
                ),
                (
                    "platform",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="dcim.platform",
                    ),
                ),
                ("tags", taggit.managers.TaggableManager(through="extras.TaggedItem", to="extras.Tag")),
            ],
            options={
                "verbose_name": "Monitoring Profile",
                "verbose_name_plural": "Monitoring Profiles",
                "ordering": ("name",),
            },
            bases=(netbox.models.deletion.DeleteMixin, models.Model),
        ),
        migrations.CreateModel(
            name="MonitoringCheckRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "custom_field_data",
                    models.JSONField(blank=True, default=dict, encoder=utilities.json.CustomFieldJSONEncoder),
                ),
                ("comments", models.TextField(blank=True)),
                ("description", models.TextField(blank=True)),
                (
                    "key",
                    models.CharField(
                        max_length=100,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[a-z][a-z0-9_.-]*$", "Use a stable lowercase check key."
                            )
                        ],
                    ),
                ),
                ("check_type", models.CharField(max_length=20)),
                ("target", models.CharField(blank=True, max_length=255)),
                ("parameters", models.JSONField(default=dict)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="users.owner"
                    ),
                ),
                ("tags", taggit.managers.TaggableManager(through="extras.TaggedItem", to="extras.Tag")),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checks",
                        to="netbox_monitoring.monitoringprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Monitoring Check Rule",
                "verbose_name_plural": "Monitoring Check Rules",
                "ordering": ("profile", "key"),
            },
            bases=(netbox.models.deletion.DeleteMixin, models.Model),
        ),
        migrations.CreateModel(
            name="MonitoringAssetOverride",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True, null=True)),
                ("last_updated", models.DateTimeField(auto_now=True, null=True)),
                (
                    "custom_field_data",
                    models.JSONField(blank=True, default=dict, encoder=utilities.json.CustomFieldJSONEncoder),
                ),
                ("comments", models.TextField(blank=True)),
                ("description", models.TextField(blank=True)),
                ("assigned_object_id", models.PositiveBigIntegerField()),
                (
                    "key",
                    models.CharField(
                        max_length=100,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[a-z][a-z0-9_.-]*$", "Use a stable lowercase check key."
                            )
                        ],
                    ),
                ),
                ("operation", models.CharField(default="change", max_length=20)),
                ("check_type", models.CharField(blank=True, max_length=20)),
                ("target", models.CharField(blank=True, max_length=255)),
                ("parameters", models.JSONField(blank=True, default=dict)),
                ("reason", models.TextField()),
                ("ticket", models.CharField(blank=True, max_length=200)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("enabled", models.BooleanField(default=True)),
                (
                    "assigned_object_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to="contenttypes.contenttype"
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="users.owner"
                    ),
                ),
                ("tags", taggit.managers.TaggableManager(through="extras.TaggedItem", to="extras.Tag")),
                (
                    "rule",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="overrides",
                        to="netbox_monitoring.monitoringcheckrule",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="overrides",
                        to="netbox_monitoring.monitoringprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Monitoring Asset Override",
                "verbose_name_plural": "Monitoring Asset Overrides",
                "ordering": ("profile", "assigned_object_type", "assigned_object_id", "key"),
            },
            bases=(netbox.models.deletion.DeleteMixin, models.Model),
        ),
        migrations.AddConstraint(
            model_name="monitoringcheckrule",
            constraint=models.UniqueConstraint(fields=("profile", "key"), name="netbox_monitoring_rule_key"),
        ),
        migrations.AddIndex(
            model_name="monitoringassetoverride",
            index=models.Index(
                fields=["assigned_object_type", "assigned_object_id"], name="netbox_monitoring_asset_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="monitoringassetoverride",
            constraint=models.UniqueConstraint(
                fields=("assigned_object_type", "assigned_object_id", "profile", "key"),
                name="netbox_monitoring_override_key",
            ),
        ),
    ]
