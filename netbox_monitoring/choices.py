from utilities.choices import ChoiceSet


class MonitoringProfileStatusChoices(ChoiceSet):
    key = "MonitoringProfile.status"
    STATUS_ACTIVE = "active"
    STATUS_DISABLED = "disabled"
    CHOICES = [
        (STATUS_ACTIVE, "Active", "green"),
        (STATUS_DISABLED, "Disabled", "gray"),
    ]
