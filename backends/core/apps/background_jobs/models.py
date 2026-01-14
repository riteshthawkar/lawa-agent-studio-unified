import uuid
from django.db import models
from apps.core.models import BaseModel


class OutboxEvent(BaseModel):
    """Outbox pattern for reliable background job processing"""
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending'
    )
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'outbox_events'
        verbose_name = 'Outbox Event'
        verbose_name_plural = 'Outbox Events'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['scheduled_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Outbox {self.event_type} - {self.status}"
