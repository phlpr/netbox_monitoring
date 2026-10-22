import django.core.validators
import django.db.models.deletion
import netbox.models.deletion
import taggit.managers
import utilities.json
from django.db import migrations, models


def populate_catalog(apps, schema_editor):
    alias = schema_editor.connection.alias
    Key = apps.get_model("netbox_monitoring", "MonitoringCheckKey")
    Rule = apps.get_model("netbox_monitoring", "MonitoringCheckRule")
    Override = apps.get_model("netbox_monitoring", "MonitoringAssetOverride")
    rules = {rule.pk: rule for rule in Rule.objects.using(alias).all()}
    overrides = list(Override.objects.using(alias).all())
    definitions = {}

    def register(name, kind, description):
        if name in definitions and definitions[name][0] != kind:
            raise RuntimeError(
                f"Monitoring key {name!r} has conflicting check types. Resolve the conflict before migration."
            )
        definitions.setdefault(name, (kind, description))

    for rule in rules.values():
        register(rule.key, rule.check_type, rule.description)
    for override in overrides:
        if override.operation == "add":
            register(override.key, override.check_type, override.description)
        elif override.rule_id not in rules or override.key != rules[override.rule_id].key:
            raise RuntimeError(f"Monitoring exception {override.pk} has an inconsistent rule/key reference.")
    keys = {
        name: Key.objects.using(alias).create(name=name, check_type=kind, description=description)
        for name, (kind, description) in definitions.items()
    }
    for rule in rules.values():
        Rule.objects.using(alias).filter(pk=rule.pk).update(catalog_key_id=keys[rule.key].pk)
    for override in overrides:
        Override.objects.using(alias).filter(pk=override.pk).update(catalog_key_id=keys[override.key].pk)


def restore_legacy_keys(apps, schema_editor):
    alias = schema_editor.connection.alias
    for model in ("MonitoringCheckRule", "MonitoringAssetOverride"):
        Model = apps.get_model("netbox_monitoring", model)
        for obj in Model.objects.using(alias).select_related("catalog_key"):
            kind = obj.catalog_key.check_type
            if model == "MonitoringAssetOverride" and obj.operation != "add":
                kind = ""
            Model.objects.using(alias).filter(pk=obj.pk).update(key=obj.catalog_key.name, check_type=kind)


class Migration(migrations.Migration):
    dependencies = [
        ("extras", "0140_imageattachment_image_size"),
        ("netbox_monitoring", "0004_remove_legacy_profile_fields"),
        ("users", "0016_default_ordering_indexes"),
    ]
    operations = [
        migrations.CreateModel(
            name="MonitoringCheckKey",
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
                    "name",
                    models.CharField(
                        max_length=100,
                        unique=True,
                        validators=[
                            django.core.validators.RegexValidator(
                                "^[a-z][a-z0-9_.-]*$", "Use a stable lowercase check key."
                            )
                        ],
                    ),
                ),
                ("check_type", models.CharField(max_length=20)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="users.owner"
                    ),
                ),
                ("tags", taggit.managers.TaggableManager(through="extras.TaggedItem", to="extras.Tag")),
            ],
            options={
                "verbose_name": "Monitoring Check Key",
                "verbose_name_plural": "Monitoring Check Keys",
                "ordering": ("name",),
            },
            bases=(netbox.models.deletion.DeleteMixin, models.Model),
        ),
        migrations.AddField(
            model_name="monitoringcheckrule",
            name="catalog_key",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rules",
                to="netbox_monitoring.monitoringcheckkey",
            ),
        ),
        migrations.AlterField(
            model_name="monitoringcheckrule",
            name="key",
            field=models.CharField(
                max_length=100,
                default="",
                validators=[
                    django.core.validators.RegexValidator("^[a-z][a-z0-9_.-]*$", "Use a stable lowercase check key.")
                ],
            ),
        ),
        migrations.AlterField(
            model_name="monitoringcheckrule",
            name="check_type",
            field=models.CharField(max_length=20, default="", blank=False),
        ),
        migrations.AddField(
            model_name="monitoringassetoverride",
            name="catalog_key",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="asset_overrides",
                to="netbox_monitoring.monitoringcheckkey",
            ),
        ),
        migrations.AlterField(
            model_name="monitoringassetoverride",
            name="key",
            field=models.CharField(
                max_length=100,
                default="",
                validators=[
                    django.core.validators.RegexValidator("^[a-z][a-z0-9_.-]*$", "Use a stable lowercase check key.")
                ],
            ),
        ),
        migrations.AlterField(
            model_name="monitoringassetoverride",
            name="check_type",
            field=models.CharField(max_length=20, default="", blank=True),
        ),
        migrations.RemoveConstraint(model_name="monitoringcheckrule", name="netbox_monitoring_rule_key"),
        migrations.RemoveConstraint(model_name="monitoringassetoverride", name="netbox_monitoring_override_key"),
        migrations.RunPython(populate_catalog, restore_legacy_keys),
        migrations.RemoveField(model_name="monitoringcheckrule", name="key"),
        migrations.RemoveField(model_name="monitoringcheckrule", name="check_type"),
        migrations.RenameField(model_name="monitoringcheckrule", old_name="catalog_key", new_name="key"),
        migrations.AlterField(
            model_name="monitoringcheckrule",
            name="key",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rules",
                to="netbox_monitoring.monitoringcheckkey",
            ),
        ),
        migrations.AddConstraint(
            model_name="monitoringcheckrule",
            constraint=models.UniqueConstraint(fields=("profile", "key"), name="netbox_monitoring_rule_key"),
        ),
        migrations.RemoveField(model_name="monitoringassetoverride", name="key"),
        migrations.RemoveField(model_name="monitoringassetoverride", name="check_type"),
        migrations.RenameField(model_name="monitoringassetoverride", old_name="catalog_key", new_name="key"),
        migrations.AlterField(
            model_name="monitoringassetoverride",
            name="key",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="asset_overrides",
                to="netbox_monitoring.monitoringcheckkey",
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
