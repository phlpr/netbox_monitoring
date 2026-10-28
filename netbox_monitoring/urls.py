from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import path
from netbox.views import generic

from . import models, monitoring_views

app_name = "netbox_monitoring"


class MonitoringObjectChangeLogView(LoginRequiredMixin, generic.ObjectChangeLogView):
    base_template = "netbox_monitoring/monitoring_object.html"


class MonitoringObjectJournalView(LoginRequiredMixin, generic.ObjectJournalView):
    base_template = "netbox_monitoring/monitoring_object.html"


urlpatterns = []
for prefix, model in (
    ("monitoring-profiles", models.MonitoringProfile),
    ("monitoring-profile-assignments", models.MonitoringProfileAssignment),
    ("monitoring-check-keys", models.MonitoringCheckKey),
    ("monitoring-check-rules", models.MonitoringCheckRule),
    ("monitoring-asset-overrides", models.MonitoringAssetOverride),
):
    key = model._meta.model_name
    for suffix, view_suffix, url_suffix in (
        ("", "ListView", "_list"),
        ("add/", "EditView", "_add"),
        ("import/", "BulkImportView", "_import"),
        ("import/", "BulkImportView", "_bulk_import"),
        ("edit/", "BulkEditView", "_bulk_edit"),
        ("delete/", "BulkDeleteView", "_bulk_delete"),
        ("<int:pk>/", "View", ""),
        ("<int:pk>/edit/", "EditView", "_edit"),
        ("<int:pk>/delete/", "DeleteView", "_delete"),
    ):
        urlpatterns.append(
            path(
                f"{prefix}/{suffix}",
                getattr(monitoring_views, f"{model.__name__}{view_suffix}").as_view(),
                name=f"{key}{url_suffix}",
            )
        )
    urlpatterns += [
        path(
            f"{prefix}/<int:pk>/changelog/",
            MonitoringObjectChangeLogView.as_view(),
            name=f"{key}_changelog",
            kwargs={"model": model},
        ),
        path(
            f"{prefix}/<int:pk>/journal/",
            MonitoringObjectJournalView.as_view(),
            name=f"{key}_journal",
            kwargs={"model": model},
        ),
    ]
