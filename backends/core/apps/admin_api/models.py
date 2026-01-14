"""
Admin API Models

Provides audit logging and tracking for admin actions.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid


class AdminAuditLog(models.Model):
    """
    Tracks all admin actions for security auditing and compliance.
    Retention: 90 days (configurable via ADMIN_AUDIT_RETENTION_DAYS setting)
    """
    
    ACTION_TYPES = [
        # User actions
        ('user.view', 'Viewed User'),
        ('user.update', 'Updated User'),
        ('user.suspend', 'Suspended User'),
        ('user.activate', 'Activated User'),
        ('user.delete', 'Deleted User'),
        ('user.verify_email', 'Verified Email'),
        ('user.unverify_email', 'Unverified Email'),
        ('user.reset_password', 'Triggered Password Reset'),
        ('user.resend_verification', 'Resent Verification'),
        ('user.impersonate', 'Impersonated User'),
        
        # Organization actions
        ('org.view', 'Viewed Organization'),
        ('org.update', 'Updated Organization'),
        ('org.quota_update', 'Updated Quotas'),
        ('org.subscription_change', 'Changed Subscription'),
        
        # System actions
        ('system.config_change', 'Changed System Config'),
        ('system.feature_toggle', 'Toggled Feature'),
        
        # Bulk actions
        ('bulk.suspend', 'Bulk Suspended Users'),
        ('bulk.activate', 'Bulk Activated Users'),
        ('bulk.delete', 'Bulk Deleted Users'),
        
        # Export actions
        ('export.users', 'Exported Users'),
        ('export.organizations', 'Exported Organizations'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Who performed the action
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='admin_audit_logs'
    )
    admin_email = models.EmailField(help_text="Stored separately in case admin is deleted")
    
    # What action was performed
    action = models.CharField(max_length=50, choices=ACTION_TYPES, db_index=True)
    
    # Target of the action (user_id, org_id, etc.)
    target_type = models.CharField(max_length=50, blank=True, help_text="Type of target: user, organization, etc.")
    target_id = models.CharField(max_length=100, blank=True, help_text="ID of the target object")
    target_label = models.CharField(max_length=255, blank=True, help_text="Human-readable label (email, org name)")
    
    # Additional details
    details = models.JSONField(default=dict, blank=True, help_text="Additional action details")
    
    # Request context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['admin', 'created_at']),
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]
        verbose_name = 'Admin Audit Log'
        verbose_name_plural = 'Admin Audit Logs'
    
    def __str__(self):
        return f"{self.admin_email} - {self.action} - {self.created_at}"
    
    @classmethod
    def log(cls, admin, action, target_type='', target_id='', target_label='', 
            details=None, request=None):
        """
        Convenience method to create an audit log entry.
        
        Usage:
            AdminAuditLog.log(
                admin=request.user,
                action='user.suspend',
                target_type='user',
                target_id=str(user.id),
                target_label=user.email,
                details={'reason': 'Spam'},
                request=request
            )
        """
        ip_address = None
        user_agent = ''
        
        if request:
            # Get IP address
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        
        return cls.objects.create(
            admin=admin,
            admin_email=admin.email if admin else 'system',
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else '',
            target_label=target_label,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent
        )
    
    @classmethod
    def cleanup_old_logs(cls, days=90):
        """Remove logs older than specified days. Default: 90 days."""
        retention_days = getattr(settings, 'ADMIN_AUDIT_RETENTION_DAYS', days)
        cutoff_date = timezone.now() - timezone.timedelta(days=retention_days)
        deleted_count, _ = cls.objects.filter(created_at__lt=cutoff_date).delete()
        return deleted_count


class LoginHistory(models.Model):
    """
    Tracks user login attempts for security monitoring.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='login_history'
    )
    
    # Login details
    success = models.BooleanField(default=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Location (optional - from IP geolocation)
    country = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    
    # Timestamp
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
        ]
        verbose_name = 'Login History'
        verbose_name_plural = 'Login Histories'
    
    def __str__(self):
        status = "Success" if self.success else "Failed"
        return f"{self.user.email} - {status} - {self.created_at}"
    
    @classmethod
    def record_login(cls, user, request, success=True):
        """Record a login attempt."""
        ip_address = None
        user_agent = ''
        
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        
        return cls.objects.create(
            user=user,
            success=success,
            ip_address=ip_address,
            user_agent=user_agent
        )
