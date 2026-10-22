from django.db import migrations


def convert_profiles(apps, schema_editor, reverse=False):
    alias = schema_editor.connection.alias
    Profile = apps.get_model("netbox_monitoring", "MonitoringProfile")
    ContentType = apps.get_model("contenttypes", "ContentType")
    types = {
        name: ContentType.objects.using(alias).get(app_label=app, model=name)
        for app, name in (("dcim", "device"), ("virtualization", "virtualmachine"))
    }
    for profile in Profile.objects.using(alias).all():
        if reverse:
            labels = set(profile.object_types.values_list("model", flat=True))
            profile.selectable = profile.status == "active"
            profile.asset_type = next(iter(labels)) if len(labels) == 1 else "any"
            profile.save(update_fields=["selectable", "asset_type"])
        else:
            profile.status = "active" if profile.selectable else "disabled"
            profile.save(update_fields=["status"])
            profile.object_types.set(
                list(types.values()) if profile.asset_type == "any" else [types[profile.asset_type]]
            )
    Field = apps.get_model("extras", "CustomField")
    Field.objects.using(alias).filter(
        name="monitoring_profile",
        related_object_type__app_label="netbox_monitoring",
        related_object_type__model="monitoringprofile",
    ).update(related_object_filter={"selectable": True} if reverse else {"status": "active"})


def forwards(apps, schema_editor):
    convert_profiles(apps, schema_editor)


def backwards(apps, schema_editor):
    convert_profiles(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [
        ("netbox_monitoring", "0002_profile_status_object_types"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
