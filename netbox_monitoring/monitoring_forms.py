"""Human-readable check forms; imports retain the structured API parameters."""

from dcim.models import Platform
from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.urls import reverse
from netbox.forms import NetBoxModelFilterSetForm, PrimaryModelBulkEditForm, PrimaryModelForm, PrimaryModelImportForm
from utilities.exceptions import AbortRequest
from utilities.forms.fields import ContentTypeMultipleChoiceField, CSVMultipleContentTypeField, DynamicModelChoiceField

try:
    from utilities.forms.fields import ChoiceField
except ImportError:  # NetBox 4.6 uses Django's choice field.
    ChoiceField = forms.ChoiceField
from utilities.forms.rendering import FieldSet

from .choices import MonitoringProfileStatusChoices
from .models import MonitoringAssetOverride, MonitoringCheckKey, MonitoringCheckRule, MonitoringProfile
from .monitoring_schema import CHECK_TYPES, DEFAULTS, METRICS, RECORD_TYPES, changed_parameters


class MonitoringSaveFormMixin:
    def save(self, commit=True):
        try:
            return super().save(commit=commit)
        except ValidationError as error:
            raise AbortRequest("; ".join(error.messages)) from error


class MonitoringProfileForm(MonitoringSaveFormMixin, PrimaryModelForm):
    platform = DynamicModelChoiceField(queryset=Platform.objects.all(), required=False)
    status = ChoiceField(choices=MonitoringProfileStatusChoices, initial="active")
    object_types = ContentTypeMultipleChoiceField(
        label="Object type(s)",
        queryset=ContentType.objects.filter(
            Q(app_label="dcim", model="device") | Q(app_label="virtualization", model="virtualmachine")
        ),
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
            self.initial["object_types"] = list(self.fields["object_types"].queryset.values_list("pk", flat=True))


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
        if isinstance(self.instance, MonitoringAssetOverride) and self.instance.rule_id:
            kind = self.instance.rule.check_type
            base = changed_parameters(self.instance.rule.parameters, self.instance.parameters)
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
        if "rule" in self.fields:
            self.fields["rule"].widget.attrs["data-monitoring-rule"] = ""
            self.fields["rule"].widget.attrs["data-monitoring-rules-url"] = reverse(
                "plugins-api:netbox_monitoring-api:monitoringcheckrule-list"
            )
        if "operation" in self.fields:
            self.fields["operation"].widget.attrs["data-monitoring-operation"] = ""

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


class MonitoringAssetOverrideForm(CheckParameterFormMixin, MonitoringSaveFormMixin, PrimaryModelForm, ParameterFields):
    profile = DynamicModelChoiceField(queryset=MonitoringProfile.objects.all())
    rule = DynamicModelChoiceField(
        queryset=MonitoringCheckRule.objects.all(), required=False, query_params={"profile_id": "$profile"}
    )
    assigned_object_type = forms.ModelChoiceField(
        queryset=ContentType.objects.filter(
            Q(app_label="dcim", model="device") | Q(app_label="virtualization", model="virtualmachine"),
        )
    )
    key = DynamicModelChoiceField(
        queryset=MonitoringCheckKey.objects.all(),
        required=False,
        help_text="For changes/disabling this is taken from the selected rule.",
    )

    class Meta:
        model = MonitoringAssetOverride
        fields = (
            "profile",
            "assigned_object_type",
            "assigned_object_id",
            "operation",
            "rule",
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
        rule = data.get("rule")
        operation = data.get("operation")
        if operation in ("change", "disable") and rule:
            data["key"] = rule.key
            data["target"] = ""
            if operation == "disable":
                data["parameters"] = {}
            else:
                params = self.build_parameters(rule.check_type, data)
                # Preserve explicit existing values when the baseline catches up.
                # Otherwise even a reason-only edit would erase their future intent.
                existing_keys = (
                    set(self.instance.parameters)
                    if (self.instance.pk and self.instance.rule_id == rule.pk and self.instance.operation == "change")
                    else set()
                )
                data["parameters"] = {
                    k: v for k, v in params.items() if v != rule.parameters.get(k) or k in existing_keys
                }
        elif operation == "add" and data.get("key"):
            data["parameters"] = self.build_parameters(data["key"].check_type, data)
        return data


class MonitoringProfileImportForm(MonitoringSaveFormMixin, PrimaryModelImportForm):
    object_types = CSVMultipleContentTypeField(
        queryset=ContentType.objects.filter(
            Q(app_label="dcim", model="device") | Q(app_label="virtualization", model="virtualmachine")
        )
    )

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
    parameters = forms.JSONField(required=False)

    class Meta:
        model = MonitoringAssetOverride
        fields = (
            "profile",
            "assigned_object_type",
            "assigned_object_id",
            "operation",
            "rule",
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
    profile_id = DynamicModelChoiceField(queryset=MonitoringProfile.objects.all(), required=False)
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
