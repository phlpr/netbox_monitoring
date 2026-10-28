"""Plugin-owned profile assignment card on supported asset detail pages."""

from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from netbox.plugins import PluginTemplateExtension

from .assets import asset_models
from .models import MonitoringProfileAssignment


def assignment_card_context(request, asset):
    if not request.user.is_authenticated:
        return {}
    can_change = type(asset).objects.restrict(request.user, "change").filter(pk=asset.pk).exists()
    ct = ContentType.objects.get_for_model(asset)
    assignments = (
        MonitoringProfileAssignment.objects.restrict(request.user, "view")
        .filter(
            assigned_object_type=ct,
            assigned_object_id=asset.pk,
        )
        .select_related("profile")
        .order_by("-weight", "profile__name")
    )
    rows = []
    for assignment in assignments:
        rows.append(
            {
                "assignment": assignment,
                "can_edit": can_change
                and request.user.has_perm("netbox_monitoring.change_monitoringprofileassignment", assignment),
                "can_delete": can_change
                and request.user.has_perm("netbox_monitoring.delete_monitoringprofileassignment", assignment),
            }
        )
    context = {"monitoring_assignments": rows}
    if can_change and request.user.has_perm("netbox_monitoring.add_monitoringprofileassignment"):
        query = urlencode(
            {
                "assigned_object_type": ct.pk,
                "assigned_object_id": asset.pk,
                "return_url": asset.get_absolute_url(),
            }
        )
        context["assignment_add_url"] = (
            reverse("plugins:netbox_monitoring:monitoringprofileassignment_add") + "?" + query
        )
    return context


class MonitoringProfilesCard(PluginTemplateExtension):
    models = [model._meta.label_lower for model in asset_models()]

    def right_page(self):
        return self.render(
            "netbox_monitoring/profile_assignments_card.html",
            extra_context=assignment_card_context(
                self.context["request"],
                self.context["object"],
            ),
        )


template_extensions = [MonitoringProfilesCard]
