import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModelMixin
from apps.residents.models import Resident


def complaint_attachment_path(instance, filename):
    return f'complaints/{instance.tenant_id}/{instance.id}/{filename}'


class Complaint(TenantModelMixin):
    """A resident's complaint/maintenance ticket (PRD Module 12). Raised
    against a Resident (never a raw property/room — the PRD's examples are
    all resident-reported issues), tracked through an exact linear workflow
    (invariant 8 style): Open -> Assigned -> In Progress -> Resolved ->
    Closed, no skipping stages."""

    class Category(models.TextChoices):
        ELECTRICAL = 'electrical', _('Electrical')
        PLUMBING = 'plumbing', _('Plumbing')
        INTERNET_WIFI = 'internet_wifi', _('Internet / WiFi')
        HOUSEKEEPING = 'housekeeping', _('Housekeeping')
        SECURITY = 'security', _('Security')
        FURNITURE = 'furniture', _('Furniture')
        OTHER = 'other', _('Other')

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')
        URGENT = 'urgent', _('Urgent')

    class Status(models.TextChoices):
        OPEN = 'open', _('Open')
        ASSIGNED = 'assigned', _('Assigned')
        IN_PROGRESS = 'in_progress', _('In Progress')
        RESOLVED = 'resolved', _('Resolved')
        CLOSED = 'closed', _('Closed')

    # PRD Module 12 workflow diagram — exact edges (invariant 8 style): no
    # skipping stages, no reopening a Resolved/Closed complaint.
    TRANSITIONS = {
        Status.OPEN: {Status.ASSIGNED},
        Status.ASSIGNED: {Status.IN_PROGRESS},
        Status.IN_PROGRESS: {Status.RESOLVED},
        Status.RESOLVED: {Status.CLOSED},
        Status.CLOSED: set(),
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.ForeignKey(Resident, on_delete=models.PROTECT, related_name='complaints')
    category = models.CharField(max_length=20, choices=Category.choices)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    description = models.TextField()
    attachment = models.FileField(upload_to=complaint_attachment_path, null=True, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='complaints_assigned',
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='complaints_raised'
    )

    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_category_display()} complaint: {self.resident}'

    def can_transition_to(self, new_status):
        return new_status in self.TRANSITIONS.get(self.status, set())


class ComplaintComment(TenantModelMixin):
    """One entry in a complaint's comment thread (PRD: 'Comments thread —
    resident + staff'). `author` is a generic User FK so a resident-authored
    comment drops in with zero schema change once resident self-service login
    exists (see Module 11 Decisions) — only staff can post today."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='complaint_comments'
    )
    body = models.TextField()

    class Meta:
        db_table = 'complaint_comments'
        ordering = ['created_at']

    def __str__(self):
        return f'Comment on {self.complaint_id} by {self.author}'


class Visitor(TenantModelMixin):
    """A logged visitor entry/exit against a resident (PRD Module 13). Front
    desk (Receptionist) logs entry and exit directly — `manage_visitors` is
    the one permission in the whole matrix that includes Receptionist, since
    this is their primary job. `approved_by` is an optional Owner/Manager
    confirmation stamp layered on top (PRD: 'with Owner/Manager confirmation
    if required') — see Decisions for why it doesn't gate entry."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resident = models.ForeignKey(Resident, on_delete=models.PROTECT, related_name='visitors')
    visitor_name = models.CharField(max_length=200)
    mobile_number = models.CharField(max_length=15)
    purpose = models.CharField(max_length=255)
    entry_time = models.DateTimeField()
    exit_time = models.DateTimeField(null=True, blank=True)
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='visitors_logged'
    )
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='visitors_checked_out',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='visitors_approved',
    )

    class Meta:
        db_table = 'visitors'
        ordering = ['-entry_time']

    def __str__(self):
        return f'{self.visitor_name} visiting {self.resident}'

    @property
    def is_checked_in(self):
        return self.exit_time is None
