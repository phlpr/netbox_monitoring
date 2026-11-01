"""Monitoring CRUD, change previews and asset configuration tabs."""

import json
from urllib.parse import urlencode

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from netbox.views import generic
from utilities.forms import restrict_form_fields
from utilities.views import ViewTab, get_viewname, register_model_view

from . import models
from . import monitoring_filtersets as filters
from . import monitoring_forms as forms
from . import monitoring_tables as tables
from .assets import asset_config_url, asset_models, asset_object_types
from .monitoring_models import assigned_assets
from .monitoring_resolver import resolve_monitoring


class MonitoringObjectView(LoginRequiredMixin, generic.ObjectView):
    template_name = "netbox_monitoring/monitoring_object.html"

    def get_extra_context(self, request, instance):
        if isinstance(instance, models.MonitoringCheckKey):
            return {
                "detail_rows": [
                    ("Name", instance.name),
                    ("Check Type", instance.get_check_type_display()),
                    ("Description", instance.description),
                ]
            }
        names = (
            ("name", "description", "status", "object_types", "platform")
            if isinstance(instance, models.MonitoringProfile)
            else (
                ("profile", "key", "check_type", "target", "parameters", "enabled")
                if isinstance(instance, models.MonitoringCheckRule)
                else (
                    "profile",
                    "assigned_object",
                    "key",
                    "operation",
                    "rule",
                    "check_type",
                    "target",
                    "parameters",
                    "reason",
                    "ticket",
                    "expires_at",
                    "enabled",
                )
            )
        )
        if isinstance(instance, models.MonitoringProfileAssignment):
            names = ("assigned_object", "profile", "weight", "enabled", "description")
        elif isinstance(instance, models.MonitoringAssetOverride):
            names = tuple(name for name in names if name not in ("profile", "rule"))
        rows = []
        for name in names:
            value = getattr(instance, name)
            if name == "object_types":
                value = ", ".join(str(ct) for ct in value.all())
            if (
                name == "platform"
                and value
                and not type(value).objects.restrict(request.user, "view").filter(pk=value.pk).exists()
            ):
                continue
            if name == "parameters":
                value = json.dumps(value, indent=2, sort_keys=True)
            rows.append((name.replace("_", " ").title(), value))
        context = {"detail_rows": rows}
        if isinstance(instance, models.MonitoringProfile):
            context["checks_table"] = tables.MonitoringCheckRuleTable(
                instance.checks.restrict(request.user, "view"),
            )
            context["assigned_assets"] = list(assigned_assets(instance, request.user))
        return context


class MonitoringEditView(LoginRequiredMixin, generic.ObjectEditView):
    template_name = "netbox_monitoring/monitoring_edit.html"
    htmx_template_name = "netbox_monitoring/monitoring_form.html"

    def alter_object(self, obj, request, url_args, url_kwargs):
        obj = super().alter_object(obj, request, url_args, url_kwargs)
        if obj.pk or not isinstance(obj, (models.MonitoringProfileAssignment, models.MonitoringAssetOverride)):
            return obj
        target = self.get_extra_addanother_params(request)
        if not target:
            return obj
        try:
            object_type_id = int(target["assigned_object_type"])
            object_id = int(target["assigned_object_id"])
        except (TypeError, ValueError):
            raise Http404("Invalid monitoring asset.") from None
        ct = get_object_or_404(asset_object_types(), pk=object_type_id)
        assets = ct.model_class().objects.restrict(request.user, "view")
        if isinstance(obj, models.MonitoringProfileAssignment):
            assets = assets.restrict(request.user, "change")
        obj.assigned_object = get_object_or_404(assets, pk=object_id)
        return obj

    def get_extra_addanother_params(self, request):
        if self.queryset.model in (models.MonitoringProfileAssignment, models.MonitoringAssetOverride):
            names = ("assigned_object_type", "assigned_object_id")
            if all(request.GET.get(name) for name in names):
                return {name: request.GET[name] for name in names}
        return super().get_extra_addanother_params(request)

    def get_extra_context(self, request, instance):
        if isinstance(instance, (models.MonitoringProfileAssignment, models.MonitoringAssetOverride)):
            asset = instance.assigned_object
            visible = (
                asset is not None and type(asset).objects.restrict(request.user, "view").filter(pk=asset.pk).exists()
            )
            return {"affected_assets": [asset] if visible else []}
        profile = (
            instance
            if isinstance(instance, models.MonitoringProfile)
            else (instance.profile if getattr(instance, "profile_id", None) else None)
        )
        return {"affected_assets": list(assigned_assets(profile, request.user)) if profile and profile.pk else []}

    def post(self, request, *args, **kwargs):
        if "_preview" not in request.POST:
            return super().post(request, *args, **kwargs)
        instance = self.alter_object(self.get_object(**kwargs), request, args, kwargs)
        before = (
            {field.name: getattr(instance, field.name) for field in instance._meta.concrete_fields}
            if instance.pk
            else {}
        )
        before_types = (
            list(instance.object_types.all())
            if isinstance(instance, models.MonitoringProfile) and instance.pk
            else None
        )
        form = self.form(data=request.POST, files=request.FILES, instance=instance)
        restrict_form_fields(form, request.user)
        changes = []
        if form.is_valid():
            for name, previous in before.items():
                current = getattr(form.instance, name)
                if current != previous:
                    changes.append((name.replace("_", " ").title(), str(previous), str(current)))
            if before_types is not None:
                proposed_types = list(form.cleaned_data.get("object_types", before_types))
                if {ct.pk for ct in before_types} != {ct.pk for ct in proposed_types}:
                    changes.append(
                        (
                            "Object types",
                            ", ".join(str(ct) for ct in before_types),
                            ", ".join(str(ct) for ct in proposed_types),
                        )
                    )
        return render(
            request,
            self.template_name,
            {
                "model": self.queryset.model,
                "object": instance,
                "form": form,
                "preview": True,
                "changes": changes,
                "return_url": self.get_return_url(request, instance),
                **self.get_extra_context(request, form.instance),
            },
        )


# Separate classes preserve conventional model/action names for NetBox links.
for model in (
    models.MonitoringProfile,
    models.MonitoringProfileAssignment,
    models.MonitoringCheckKey,
    models.MonitoringCheckRule,
    models.MonitoringAssetOverride,
):
    name = model.__name__
    queryset = model.objects.all()
    globals()[f"{name}View"] = type(f"{name}View", (MonitoringObjectView,), {"queryset": queryset})
    globals()[f"{name}ListView"] = type(
        f"{name}ListView",
        (LoginRequiredMixin, generic.ObjectListView),
        {
            "queryset": queryset,
            "table": getattr(tables, f"{name}Table"),
            "filterset": getattr(filters, f"{name}FilterSet"),
            "filterset_form": getattr(forms, f"{name}FilterForm"),
        },
    )
    globals()[f"{name}EditView"] = type(
        f"{name}EditView",
        (MonitoringEditView,),
        {
            "queryset": queryset,
            "form": getattr(forms, f"{name}Form"),
        },
    )
    globals()[f"{name}DeleteView"] = type(
        f"{name}DeleteView",
        (LoginRequiredMixin, generic.ObjectDeleteView),
        {"queryset": queryset},
    )
    globals()[f"{name}BulkEditView"] = type(
        f"{name}BulkEditView",
        (LoginRequiredMixin, generic.BulkEditView),
        {
            "queryset": queryset,
            "table": getattr(tables, f"{name}Table"),
            "filterset": getattr(filters, f"{name}FilterSet"),
            "form": getattr(forms, f"{name}BulkEditForm"),
        },
    )
    globals()[f"{name}BulkDeleteView"] = type(
        f"{name}BulkDeleteView",
        (LoginRequiredMixin, generic.BulkDeleteView),
        {
            "queryset": queryset,
            "table": getattr(tables, f"{name}Table"),
            "filterset": getattr(filters, f"{name}FilterSet"),
        },
    )
    globals()[f"{name}BulkImportView"] = type(
        f"{name}BulkImportView",
        (LoginRequiredMixin, generic.BulkImportView),
        {
            "queryset": queryset,
            "model_form": getattr(forms, f"{name}ImportForm"),
        },
    )


def monitoring_tab_context(view, request, instance):
    from .template_content import assignment_card_context

    context = assignment_card_context(request, instance)
    try:
        context["monitoring"] = resolve_monitoring(instance, request.user)
        if context["monitoring"]["configured"]:
            context["monitoring_config_url"] = asset_config_url(instance)
            if request.user.has_perm("netbox_monitoring.add_monitoringassetoverride"):
                query = urlencode(
                    {
                        "assigned_object_type": ContentType.objects.get_for_model(instance).pk,
                        "assigned_object_id": instance.pk,
                        "return_url": reverse(get_viewname(instance, "monitoring"), args=[instance.pk]),
                    }
                )
                context["exception_add_url"] = (
                    reverse("plugins:netbox_monitoring:monitoringassetoverride_add") + "?" + query
                )
        for check in context["monitoring"]["checks"]:
            check["parameters_text"] = json.dumps(check["parameters"], sort_keys=True)
    except ValidationError as error:
        context["monitoring_error"] = "; ".join(error.messages)
    return context


def register_monitoring_tabs():
    for model in asset_models():
        view = type(
            f"MonitoringTab_{model._meta.model_name}",
            (LoginRequiredMixin, generic.ObjectView),
            {
                "queryset": model.objects.all(),
                "template_name": "netbox_monitoring/object_monitoring.html",
                "additional_permissions": ("netbox_monitoring.view_monitoringprofile",),
                "tab": ViewTab(label="Monitoring", permission="netbox_monitoring.view_monitoringprofile"),
                "get_extra_context": monitoring_tab_context,
            },
        )
        register_model_view(model, name="monitoring", path="monitoring")(view)
