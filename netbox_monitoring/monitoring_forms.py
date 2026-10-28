"""Human-readable check forms; imports retain the structured API parameters."""

from dcim.models import Platform
from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.urls import reverse
from netbox.forms import NetBoxModelFilterSetForm, PrimaryModelBulkEditForm, PrimaryModelForm, PrimaryModelImportForm
from utilities.exceptions import AbortRequest
from utilities.forms.fields import (
    ContentTypeChoiceField,
    ContentTypeMultipleChoiceField,
    CSVContentTypeField,
    CSVMultipleContentTypeField,
    DynamicModelChoiceField,
)

try:
    from utilities.forms.fields import ChoiceField
except ImportError:  # NetBox 4.6 uses Django's choice field.
    ChoiceField = forms.ChoiceField
from utilities.forms.rendering import FieldSet

from .assets import asset_object_types
from .choices import MonitoringProfileStatusChoices
from .models import (
    MonitoringAssetOverride,
    MonitoringCheckKey,
    MonitoringCheckRule,
    MonitoringProfile,
    MonitoringProfileAssignment,
)
from .monitoring_composition import compose
from .monitoring_permissions import monitoring_request
from .monitoring_schema import CHECK_TYPES, DEFAULTS, METRICS, RECORD_TYPES, changed_parameters


class MonitoringSaveFormMixin:
    def save(self, commit=True):
        try:
            return super().save(commit=commit)
        except ValidationError as error:
            raise AbortRequest("; ".join(error.messages)) from error


class AssetTargetFormMixin:
    """Keep asset-scoped forms bound to the target supplied by the view."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.assigned_object_type_id and self.instance.assigned_object_id:
            self.initial["assigned_object_type"] = self.instance.assigned_object_type_id
            self.initial["assigned_object_id"] = self.instance.assigned_object_id
            for name in ("assigned_object_type", "assigned_object_id"):
                # Django also ignores submitted values for disabled fields.
                self.fields[name].disabled = True


class MonitoringProfileForm(MonitoringSaveFormMixin, PrimaryModelForm):
    platform = DynamicModelChoiceField(queryset=Platform.objects.all(), required=False)
    status = ChoiceField(choices=MonitoringProfileStatusChoices, initial="active")
    object_types = ContentTypeMultipleChoiceField(
        label="Object type(s)",
        queryset=asset_object_types(),
    )
    fieldsets = (
        FieldSet("name", "status", "object_types", "platform", "description", "tags", name="Monitoring Profile"),
    )

    class Meta:
        model = MonitoringProfile
        fields = ("name", "description", "status", "object_types", "platform", "owner", "comments", "tags")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and "object_types" not in self.initial:
            self.initial["object_types"] = [ct.pk for ct in self.instance.selected_object_types()]


class MonitoringCheckKeyForm(MonitoringSaveFormMixin, PrimaryModelForm):
    fieldsets = (FieldSet("name", "check_type", "description", "tags", name="Monitoring Check Key"),)

    class Meta:
        model = MonitoringCheckKey
        fields = ("name", "check_type", "description", "owner", "comments", "tags")


class CheckParameterFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kind = getattr(self.instance, "check_type", "")
        key_id = self.data.get(self.add_prefix("key")) if self.is_bound else self.initial.get("key")
        if key_id:
            try:
                selected_key = MonitoringCheckKey.objects.filter(pk=getattr(key_id, "pk", key_id)).first()
            except (ValueError, TypeError):
                selected_key = None
            if selected_key:
                kind = selected_key.check_type
        base = DEFAULTS.get(kind, {})
        if isinstance(self.instance, MonitoringAssetOverride):
            check = self.effective_base()
            if check:
                kind = check["check_type"]
                base = changed_parameters(check["parameters"], self.instance.parameters)
            elif self.instance.pk:
                base = changed_parameters(DEFAULTS.get(kind, {}), self.instance.parameters)
        elif self.instance.pk:
            base = self.instance.parameters
        for key, value in base.items():
            if key in self.fields:
                self.initial[key] = "\n".join(value) if isinstance(value, list) else value
        self.initial["parameter_kind"] = kind
        self.fields["parameter_kind"].widget.attrs["data-monitoring-kind"] = ""
        self.fields["key"].widget.attrs.update(
            {
                "data-monitoring-key": "",
                "data-monitoring-keys-url": reverse("plugins-api:netbox_monitoring-api:monitoringcheckkey-list"),
            }
        )
        if "operation" in self.fields:
            import json

            self.fields["operation"].widget.attrs["data-monitoring-operation"] = ""
            self.fields["assigned_object_type"].widget.attrs["data-monitoring-object-types"] = json.dumps(
                {str(ct.pk): f"{ct.app_label}.{ct.model}" for ct in asset_object_types()}
            )
            self.fields["assigned_object_type"].widget.attrs["data-monitoring-assets-url"] = reverse(
                "plugins-api:netbox_monitoring-api:monitored-assets"
            )

    def effective_base(self, data=None):
        values = data if data is not None else (self.data if self.is_bound else self.initial)

        def selected(name):
            if self.fields[name].disabled:
                return self.initial.get(name)
            return values.get(name, getattr(self.instance, name, None))

        ct = selected("assigned_object_type")
        asset_id = selected("assigned_object_id")
        key = selected("key")
        if not ct or not asset_id or not key:
            return None
        try:
            ct = ct if isinstance(ct, ContentType) else ContentType.objects.filter(pk=ct).first()
            asset = ct.model_class().objects.filter(pk=asset_id).first() if ct and ct.model_class() else None
            key = key if isinstance(key, MonitoringCheckKey) else MonitoringCheckKey.objects.filter(pk=key).first()
        except (ValueError, TypeError):
            return None
        if asset is None or key is None:
            return None
        from .assets import is_asset_model

        if not is_asset_model(type(asset)):
            return None
        request = monitoring_request.get()
        if request and not type(asset).objects.restrict(request.user, "view").filter(pk=asset.pk).exists():
            return None
        _, checks = compose(asset, user=request.user if request else None, include_overrides=False)
        return next((check for check in checks if check["key"] == key.name), None)

    def build_parameters(self, kind, data):
        if kind in METRICS:
            params = {key: data.get(key) for key in ("metric", "warning", "critical")}
            if kind == "disk":
                params["exclude_paths"] = self.lines(data.get("exclude_paths"))
            else:
                params["window_seconds"] = data.get("window_seconds")
        elif kind == "dns":
            params = {
                key: data.get(key) for key in ("record_type", "resolver", "timeout_seconds", "measurement_location")
            }
            params["expected_answers"] = self.lines(data.get("expected_answers"))
        else:
            params = {key: data.get(key) for key in ("matcher", "min_count", "max_count")}
        return params

    @staticmethod
    def lines(value):
        return [line.strip() for line in (value or "").splitlines() if line.strip()]


class ParameterFields(forms.Form):
    parameter_kind = forms.CharField(required=False, widget=forms.HiddenInput)
    metric = forms.ChoiceField(
        choices=(("", "---------"),)
        + tuple(
            (value, value.replace("_", " ").title())
            for value in dict.fromkeys(v for values in METRICS.values() for v in values)
        ),
        required=False,
    )
    warning = forms.FloatField(required=False, min_value=0)
    critical = forms.FloatField(required=False, min_value=0)
    window_seconds = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=86400,
        initial=300,
        help_text="Evaluation window; the export adapter must support this meaning.",
    )
    exclude_paths = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="One excluded filesystem path per line."
    )
    record_type = forms.ChoiceField(choices=tuple((t, t) for t in RECORD_TYPES), required=False, initial="A")
    resolver = forms.CharField(required=False, initial="system", help_text="DNS server IP or system.")
    expected_answers = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Expected DNS answers, one per line. Empty means successful resolution.",
    )
    timeout_seconds = forms.IntegerField(required=False, min_value=1, max_value=300, initial=5)
    measurement_location = forms.ChoiceField(
        choices=(("asset", "On the asset"), ("monitor", "From the monitoring server")), required=False, initial="asset"
    )
    matcher = forms.ChoiceField(
        choices=(("exact", "Exact process name"), ("regex", "Regular expression"), ("service", "Running OS service")),
        required=False,
        initial="exact",
    )
    min_count = forms.IntegerField(required=False, min_value=0, initial=1)
    max_count = forms.IntegerField(required=False, min_value=0)
    parameters = forms.JSONField(required=False, widget=forms.HiddenInput)


class MonitoringCheckRuleForm(CheckParameterFormMixin, MonitoringSaveFormMixin, PrimaryModelForm, ParameterFields):
    profile = DynamicModelChoiceField(queryset=MonitoringProfile.objects.all())
    key = DynamicModelChoiceField(queryset=MonitoringCheckKey.objects.all(), quick_add=True)

    class Meta:
        model = MonitoringCheckRule
        fields = ("profile", "key", "target", "parameters", "enabled", "description", "comments", "tags")

    def clean(self):
        data = super().clean() or self.cleaned_data
        kind = data["key"].check_type if data.get("key") else None
        if kind:
            data["parameters"] = self.build_parameters(kind, data)
        return data


class MonitoringAssetOverrideForm(
    CheckParameterFormMixin, AssetTargetFormMixin, MonitoringSaveFormMixin, PrimaryModelForm, ParameterFields
):
    assigned_object_type = ContentTypeChoiceField(queryset=asset_object_types())
    key = DynamicModelChoiceField(queryset=MonitoringCheckKey.objects.all())

    class Meta:
        model = MonitoringAssetOverride
        fields = (
            "assigned_object_type",
            "assigned_object_id",
            "operation",
            "key",
            "target",
            "parameters",
            "reason",
            "ticket",
            "expires_at",
            "enabled",
            "description",
            "comments",
            "tags",
        )

    def clean(self):
        data = super().clean() or self.cleaned_data
        operation = data.get("operation")
        key = data.get("key")
        if operation in ("change", "disable") and key:
            data["target"] = ""
            if operation == "disable":
                data["parameters"] = {}
            else:
                check = self.effective_base(data)
                if check is None:
                    if data.get("enabled"):
                        raise ValidationError("Select a key present in the asset's effective profile configuration.")
                    check = {"parameters": DEFAULTS[key.check_type]}
                params = self.build_parameters(key.check_type, data)
                existing_keys = (
                    set(self.instance.parameters)
                    if (self.instance.pk and self.instance.key_id == key.pk and self.instance.operation == "change")
                    else set()
                )
                data["parameters"] = {
                    k: v for k, v in params.items() if v != check["parameters"].get(k) or k in existing_keys
                }
        elif operation == "add" and key:
            data["parameters"] = self.build_parameters(key.check_type, data)
        return data


class MonitoringProfileAssignmentForm(AssetTargetFormMixin, MonitoringSaveFormMixin, PrimaryModelForm):
    profile = DynamicModelChoiceField(queryset=MonitoringProfile.objects.all(), query_params={"status": "active"})
    assigned_object_type = ContentTypeChoiceField(queryset=asset_object_types())
    fieldsets = (
        FieldSet(
            "assigned_object_type",
            "assigned_object_id",
            "profile",
            "weight",
            "enabled",
            "description",
            "tags",
            name="Monitoring profile assignment",
        ),
    )

    class Meta:
        model = MonitoringProfileAssignment
        fields = (
            "assigned_object_type",
            "assigned_object_id",
            "profile",
            "weight",
            "enabled",
            "description",
            "owner",
            "comments",
            "tags",
        )


class MonitoringProfileImportForm(MonitoringSaveFormMixin, PrimaryModelImportForm):
    object_types = CSVMultipleContentTypeField(queryset=asset_object_types())

    class Meta:
        model = MonitoringProfile
        fields = ("name", "description", "status", "object_types", "platform", "comments")


class MonitoringCheckKeyImportForm(MonitoringSaveFormMixin, PrimaryModelImportForm):
    class Meta:
        model = MonitoringCheckKey
        fields = ("name", "check_type", "description", "comments")


class MonitoringCheckRuleImportForm(MonitoringSaveFormMixin, PrimaryModelImportForm):
    parameters = forms.JSONField()

    class Meta:
        model = MonitoringCheckRule
        fields = ("profile", "key", "target", "parameters", "enabled", "description", "comments")


class MonitoringAssetOverrideImportForm(MonitoringSaveFormMixin, PrimaryModelImportForm):
    assigned_object_type = CSVContentTypeField(queryset=asset_object_types())
    parameters = forms.JSONField(required=False)

    class Meta:
        model = MonitoringAssetOverride
        fields = (
            "assigned_object_type",
            "assigned_object_id",
            "operation",
            "key",
            "target",
            "parameters",
            "reason",
            "ticket",
            "expires_at",
            "enabled",
            "comments",
        )

    def clean_parameters(self):
        return self.cleaned_data.get("parameters") or {}


class MonitoringProfileFilterForm(NetBoxModelFilterSetForm):
    model = MonitoringProfile
    status = forms.MultipleChoiceField(choices=MonitoringProfileStatusChoices, required=False)


class MonitoringCheckRuleFilterForm(NetBoxModelFilterSetForm):
    model = MonitoringCheckRule
    profile_id = DynamicModelChoiceField(queryset=MonitoringProfile.objects.all(), required=False)
    check_type = forms.ChoiceField(choices=(("", "---------"),) + CHECK_TYPES, required=False)


class MonitoringCheckKeyFilterForm(NetBoxModelFilterSetForm):
    model = MonitoringCheckKey
    check_type = forms.ChoiceField(choices=(("", "---------"),) + CHECK_TYPES, required=False)


class MonitoringAssetOverrideFilterForm(NetBoxModelFilterSetForm):
    model = MonitoringAssetOverride
    enabled = forms.NullBooleanField(required=False)


class MonitoringBulkEditForm(PrimaryModelBulkEditForm):
    description = forms.CharField(required=False, widget=forms.Textarea)
    nullable_fields = ("description",)


class MonitoringProfileBulkEditForm(MonitoringBulkEditForm):
    model = MonitoringProfile
    status = ChoiceField(choices=(("", "---------"),) + tuple(MonitoringProfileStatusChoices), required=False)


class MonitoringCheckRuleBulkEditForm(MonitoringBulkEditForm):
    model = MonitoringCheckRule
    enabled = forms.NullBooleanField(required=False)


class MonitoringCheckKeyBulkEditForm(MonitoringBulkEditForm):
    model = MonitoringCheckKey


class MonitoringAssetOverrideBulkEditForm(MonitoringBulkEditForm):
    model = MonitoringAssetOverride
    enabled = forms.NullBooleanField(required=False)


class MonitoringProfileAssignmentImportForm(MonitoringSaveFormMixin, PrimaryModelImportForm):
    assigned_object_type = CSVContentTypeField(queryset=asset_object_types())

    class Meta:
        model = MonitoringProfileAssignment
        fields = (
            "assigned_object_type",
            "assigned_object_id",
            "profile",
            "weight",
            "enabled",
            "description",
            "comments",
        )


class MonitoringProfileAssignmentFilterForm(NetBoxModelFilterSetForm):
    model = MonitoringProfileAssignment
    profile_id = DynamicModelChoiceField(queryset=MonitoringProfile.objects.all(), required=False)
    enabled = forms.NullBooleanField(required=False)


class MonitoringProfileAssignmentBulkEditForm(MonitoringBulkEditForm):
    model = MonitoringProfileAssignment
    weight = forms.IntegerField(required=False, min_value=0)
    enabled = forms.NullBooleanField(required=False)
