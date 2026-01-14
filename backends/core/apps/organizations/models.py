import uuid
from django.db import models
from django.core.validators import RegexValidator
from apps.core.models import BaseModel


class Organization(BaseModel):
    """Organization model for multi-tenancy"""
    name = models.CharField(max_length=255)
    slug = models.SlugField(
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^[a-z0-9-]+$',
                message='Slug must contain only lowercase letters, numbers, and hyphens'
            )
        ]
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('suspended', 'Suspended'),
        ],
        default='active'
    )
    plan_tier = models.CharField(
        max_length=20,
        choices=[
            ('basic', 'Basic'),        # Free tier
            ('premium', 'Premium'),    # Paid tier
            ('enterprise', 'Enterprise'),  # Custom/contact us
        ],
        default='basic'
    )

    class Meta:
        db_table = 'organizations'
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return self.name


class Membership(BaseModel):
    """User membership in organizations"""
    user = models.ForeignKey('lawa_auth.User', on_delete=models.CASCADE, related_name='memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(
        max_length=20,
        choices=[
            ('owner', 'Owner'),
            ('admin', 'Admin'),
            ('member', 'Member'),
        ],
        default='member'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'memberships'
        verbose_name = 'Membership'
        verbose_name_plural = 'Memberships'
        unique_together = [['user', 'organization']]
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['organization']),
            models.Index(fields=['role']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.organization.name} ({self.role})"
