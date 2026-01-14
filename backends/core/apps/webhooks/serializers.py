from rest_framework import serializers
from .models import WebhookEvent, AuditLog


class WebhookEventSerializer(serializers.ModelSerializer):
    """Serializer for WebhookEvent model"""
    
    class Meta:
        model = WebhookEvent
        fields = (
            'id', 'kind', 'target_url', 'payload', 'result_status',
            'attempts', 'last_attempt_at', 'created_at'
        )
        read_only_fields = ('id', 'created_at')


class AuditLogSerializer(serializers.ModelSerializer):
    """Serializer for AuditLog model"""
    
    class Meta:
        model = AuditLog
        fields = (
            'id', 'org_id', 'actor_user_id', 'action',
            'target_type', 'target_id', 'details', 'created_at'
        )
        read_only_fields = ('id', 'created_at')
