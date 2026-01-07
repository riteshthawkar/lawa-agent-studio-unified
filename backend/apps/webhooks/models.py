import uuid
from django.db import models
from apps.core.models import BaseModel


class WebhookEvent(BaseModel):
    """Webhook event tracking"""
    kind = models.CharField(
        max_length=20,
        choices=[
            ('indexing_update', 'Indexing Update'),
        ]
    )
    target_url = models.URLField()
    payload = models.JSONField(default=dict)
    result_status = models.IntegerField(null=True, blank=True)
    attempts = models.IntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'webhook_events'
        verbose_name = 'Webhook Event'
        verbose_name_plural = 'Webhook Events'
        indexes = [
            models.Index(fields=['kind']),
            models.Index(fields=['result_status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Webhook {self.kind} - {self.target_url}"


class AuditLog(BaseModel):
    """Audit logging for security and compliance"""
    org_id = models.UUIDField()
    actor_user_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50)
    target_id = models.UUIDField()
    details = models.JSONField(default=dict)

    class Meta:
        db_table = 'audit_logs'
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        indexes = [
            models.Index(fields=['org_id']),
            models.Index(fields=['actor_user_id']),
            models.Index(fields=['action']),
            models.Index(fields=['created_at']),
            # Composite indexes for multi-tenant audit queries
            models.Index(fields=['org_id', 'created_at'], name='audit_logs_org_created_idx'),
            models.Index(fields=['org_id', 'action'], name='audit_logs_org_action_idx'),
        ]

    def __str__(self):
        return f"{self.action} - {self.target_type}:{self.target_id}"
