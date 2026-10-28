"""Mutable monitoring profiles, check rules and centrally maintained exceptions."""

from django.apps import apps
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from netbox.models import PrimaryModel
from utilities.querysets import RestrictedQuerySet

from .assets import asset_models, is_asset_model
from .choices import MonitoringProfileStatusChoices
from .monitoring_schema import (
    CHECK_TYPES,
    DEFAULT_ASSET_MODELS,
    OPERATIONS,
    PROFILE_FIELD,
    changed_parameters,
    validate_check,
)


def assigned_assets(profile, user=None):
    for model in asset_models():
        objects = model.objects.all() if user is None else model.objects.restrict(user, "view")
        yield from objects.filter(**{f"custom_field_data__{PROFILE_FIELD}": profile.pk})


class MonitoringModel(PrimaryModel):
    description = models.TextField(blank=True)
    # Keep the inherited field's migration state stable across NetBox 4.6/4.7:
    # 4.7 adds related_name="+" to OwnerMixin without changing its database column.
    owner = models.ForeignKey("users.Owner", on_delete=models.PROTECT, blank=True, null=True)

    class Meta:
        abstract = True

    def get_absolute_url(self):
        return reverse(f"plugins:netbox_monitoring:{self._meta.model_name}", args=[self.pk])

    def clean(self):
        super().clean()
        from .monitoring_permissions import monitoring_request

        request = monitoring_request.get()
        if not request:
            return
        for name in ("profile", "rule", "platform", "key"):
            related = getattr(self, name, None)
            if related and not type(related).objects.restrict(request.user, "view").filter(pk=related.pk).exists():
                raise ValidationError({name: "View permission is required for the selected object."})
        if isinstance(self, MonitoringAssetOverride) and self.assigned_object:
            asset = self.assigned_object
            if not type(asset).objects.restrict(request.user, "view").filter(pk=asset.pk).exists():
                raise ValidationError({"assigned_object_id": "View permission is required for the asset."})

    def save(self, *args, **kwargs):
        from .monitoring_permissions import monitoring_request, require_monitoring_manager

        request = monitoring_request.get()
        if request:
            require_monitoring_manager(request.user)
        # Serialize profile/rule/exception writes on the owning profile. This also
        # makes dependent override validation and the resulting write atomic.
        with transaction.atomic(using=kwargs.get("using") or self._state.db):
            profile_id = self.pk if isinstance(self, MonitoringProfile) else getattr(self, "profile_id", None)
            profile_ids = {profile_id} if profile_id else set()
            if self.pk and hasattr(self, "profile_id"):
                previous = type(self).objects.filter(pk=self.pk).values_list("profile_id", flat=True).first()
                if previous:
                    profile_ids.add(previous)
            list(MonitoringProfile.objects.select_for_update().filter(pk__in=profile_ids).order_by("pk"))
            key_id = self.pk if isinstance(self, MonitoringCheckKey) else getattr(self, "key_id", None)
            if key_id:
                locked_key = MonitoringCheckKey.objects.select_for_update().get(pk=key_id)
                if not isinstance(self, MonitoringCheckKey):
                    self.key = locked_key
            self.full_clean()
            return super().save(*args, **kwargs)


class MonitoringProfile(MonitoringModel):
    name = models.CharField(max_length=200, unique=True)
    status = models.CharField(
        max_length=50,
        choices=MonitoringProfileStatusChoices,
        default="active",
        help_text="Disabled profiles remain effective for existing assignments.",
    )
    object_types = models.ManyToManyField("contenttypes.ContentType", related_name="monitoring_profiles")
    platform = models.ForeignKey("dcim.Platform", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    clone_fields = ("description", "status", "object_types", "platform", "owner", "comments")

    class Meta:
        ordering = ("name",)
        verbose_name = "Monitoring Profile"
        verbose_name_plural = "Monitoring Profiles"

    def __str__(self):
        return self.name

    def get_status_color(self):
        return MonitoringProfileStatusChoices.colors.get(self.status, "gray")

    def selected_object_types(self):
        values = getattr(self, "_m2m_values", {}).get("object_types")
        if values is not None:
            from django.contrib.contenttypes.models import ContentType

            return list(ContentType.objects.filter(pk__in=[getattr(value, "pk", value) for value in values]))
        if self.pk:
            return list(self.object_types.all())
        from django.contrib.contenttypes.models import ContentType

        return [ContentType.objects.get_for_model(apps.get_model(label)) for label in DEFAULT_ASSET_MODELS]

    def accepts(self, asset):
        return (
            is_asset_model(type(asset))
            and any(f"{ct.app_label}.{ct.model}" == asset._meta.label_lower for ct in self.selected_object_types())
            and (self.platform_id is None or not hasattr(asset, "platform_id") or self.platform_id == asset.platform_id)
        )

    def clean(self):
        super().clean()
        types = self.selected_object_types()
        if not types or any(not is_asset_model(ct.model_class()) for ct in types):
            raise ValidationError({"object_types": "Select at least one supported asset object type."})
        if self.pk:
            if any(not self.accepts(asset) for asset in assigned_assets(self)):
                raise ValidationError("The new scope excludes assets already assigned to this profile.")

    def save(self, *args, **kwargs):
        adding = self._state.adding
        with transaction.atomic():
            types = self.selected_object_types()
            result = super().save(*args, **kwargs)
            if adding:
                self.object_types.set(types)
            return result


class MonitoringCheckKey(MonitoringModel):
    name = models.CharField(
        max_length=100,
        unique=True,
        validators=[RegexValidator(r"^[a-z][a-z0-9_.-]*$", "Use a stable lowercase check key.")],
    )
    check_type = models.CharField(max_length=20, choices=CHECK_TYPES)
    clone_fields = ("description", "check_type", "owner", "comments")

    class Meta:
        ordering = ("name",)
        verbose_name = "Monitoring Check Key"
        verbose_name_plural = "Monitoring Check Keys"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if (old.name, old.check_type) != (self.name, self.check_type) and (
                self.rules.exists() or self.asset_overrides.exists()
            ):
                raise ValidationError("A referenced key cannot change its stable name or check type. Create a new key.")


class MonitoringRuleQuerySet(RestrictedQuerySet):
    def restrict(self, user, action="view"):
        return (
            super()
            .restrict(user, action)
            .filter(
                profile__in=MonitoringProfile.objects.restrict(user, "view"),
                key__in=MonitoringCheckKey.objects.restrict(user, "view"),
            )
        )


class MonitoringCheckRule(MonitoringModel):
    objects = MonitoringRuleQuerySet.as_manager()
    profile = models.ForeignKey(MonitoringProfile, on_delete=models.CASCADE, related_name="checks")
    key = models.ForeignKey(MonitoringCheckKey, on_delete=models.PROTECT, related_name="rules")
    target = models.CharField(max_length=255, blank=True)
    parameters = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    clone_fields = ("profile", "key", "target", "parameters", "enabled", "description", "comments")

    class Meta:
        ordering = ("profile", "key")
        verbose_name = "Monitoring Check Rule"
        verbose_name_plural = "Monitoring Check Rules"
        constraints = [models.UniqueConstraint(fields=("profile", "key"), name="netbox_monitoring_rule_key")]

    def __str__(self):
        return f"{self.profile}: {self.key}"

    @property
    def check_type(self):
        return self.key.check_type if self.key_id else ""

    def clean(self):
        super().clean()
        if not self.key_id:
            return
        validate_check(self.check_type, self.target, self.parameters)
        if not self.profile_id:
            return
        peers = type(self).objects.filter(profile_id=self.profile_id).exclude(pk=self.pk)
        if peers.filter(key__check_type=self.check_type, target=self.target).exists():
            raise ValidationError({"target": "This profile already contains a check of this type for this target."})
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if (old.profile_id, old.key_id) != (self.profile_id, self.key_id) and self.overrides.exists():
                raise ValidationError("A referenced check cannot change its profile or stable key.")
            for override in self.overrides.all():
                if override.operation == "change":
                    validate_check(
                        self.check_type, self.target, changed_parameters(self.parameters, override.parameters)
                    )
        if self.profile.overrides.filter(operation="add", key=self.key).exists():
            raise ValidationError({"key": "An asset exception already adds a check with this key."})
        if self.profile.overrides.filter(operation="add", key__check_type=self.check_type, target=self.target).exists():
            raise ValidationError({"target": "An asset exception already adds this check target."})


class MonitoringOverrideQuerySet(RestrictedQuerySet):
    def restrict(self, user, action="view"):
        qs = super().restrict(user, action).filter(profile__in=MonitoringProfile.objects.restrict(user, "view"))
        condition = models.Q(pk__in=[])
        for model in asset_models():
            condition |= models.Q(
                assigned_object_type__app_label=model._meta.app_label,
                assigned_object_type__model=model._meta.model_name,
                assigned_object_id__in=model.objects.restrict(user, "view").values("pk"),
            )
        return (
            qs.filter(condition)
            .filter(
                models.Q(rule__isnull=True) | models.Q(rule__in=MonitoringCheckRule.objects.restrict(user, "view")),
            )
            .filter(key__in=MonitoringCheckKey.objects.restrict(user, "view"))
        )


class MonitoringAssetOverride(MonitoringModel):
    objects = MonitoringOverrideQuerySet.as_manager()
    profile = models.ForeignKey(MonitoringProfile, on_delete=models.PROTECT, related_name="overrides")
    rule = models.ForeignKey(
        MonitoringCheckRule, on_delete=models.PROTECT, related_name="overrides", null=True, blank=True
    )
    assigned_object_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.PROTECT, related_name="+")
    assigned_object_id = models.PositiveBigIntegerField()
    assigned_object = GenericForeignKey("assigned_object_type", "assigned_object_id")
    key = models.ForeignKey(MonitoringCheckKey, on_delete=models.PROTECT, related_name="asset_overrides")
    operation = models.CharField(max_length=20, choices=OPERATIONS, default="change")
    target = models.CharField(max_length=255, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    reason = models.TextField()
    ticket = models.CharField(max_length=200, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ("profile", "assigned_object_type", "assigned_object_id", "key")
        verbose_name = "Monitoring Asset Override"
        verbose_name_plural = "Monitoring Asset Overrides"
        constraints = [
            models.UniqueConstraint(
                fields=("assigned_object_type", "assigned_object_id", "profile", "key"),
                name="netbox_monitoring_override_key",
            )
        ]
        indexes = [
            models.Index(fields=("assigned_object_type", "assigned_object_id"), name="netbox_monitoring_asset_idx")
        ]

    def __str__(self):
        return f"{self.profile}: {self.key} ({self.assigned_object_type.app_label}.{self.assigned_object_type.model}:{self.assigned_object_id})"

    @property
    def check_type(self):
        return self.key.check_type if self.key_id else ""

    @property
    def is_active(self):
        return self.enabled and (self.expires_at is None or self.expires_at > timezone.now())

    def clean(self):
        super().clean()
        if not self.assigned_object_type_id or not self.profile_id:
            return
        if not is_asset_model(self.assigned_object_type.model_class()):
            raise ValidationError({"assigned_object_type": "Select a public object type supporting custom fields."})
        asset = self.assigned_object
        if asset is None:
            raise ValidationError({"assigned_object_id": "The target asset does not exist."})
        if self.is_active and asset.custom_field_data.get(PROFILE_FIELD) != self.profile_id:
            raise ValidationError({"profile": "The asset must select this monitoring profile first."})
        if not self.reason.strip():
            raise ValidationError({"reason": "Explain why this exception is required."})
        if self.operation == "add":
            if not self.key_id:
                return
            if self.rule_id:
                raise ValidationError({"rule": "Additional checks must not reference a base rule."})
            validate_check(self.check_type, self.target, self.parameters)
            if self.profile.checks.filter(key=self.key).exists():
                raise ValidationError({"key": "This key is already used by a profile check."})
            if self.profile.checks.filter(key__check_type=self.check_type, target=self.target).exists():
                raise ValidationError({"target": "This target is already checked by the profile."})
            if (
                type(self)
                .objects.filter(
                    profile=self.profile,
                    assigned_object_type=self.assigned_object_type,
                    assigned_object_id=self.assigned_object_id,
                    operation="add",
                    key__check_type=self.check_type,
                    target=self.target,
                )
                .exclude(pk=self.pk)
                .exists()
            ):
                raise ValidationError({"target": "Another exception already adds this target."})
        else:
            if not self.rule_id or self.rule.profile_id != self.profile_id:
                raise ValidationError({"rule": "Select a check belonging to this profile."})
            if self.key_id != self.rule.key_id:
                raise ValidationError({"key": "Use the stable key of the selected profile check."})
            if self.target:
                raise ValidationError("Target is defined by the base rule; leave it empty.")
            if self.operation == "disable":
                if self.parameters:
                    raise ValidationError({"parameters": "Disabling a check must not also change parameters."})
            else:
                validate_check(self.rule.check_type, self.rule.target, self.parameters, partial=True)
                validate_check(
                    self.rule.check_type, self.rule.target, changed_parameters(self.rule.parameters, self.parameters)
                )
