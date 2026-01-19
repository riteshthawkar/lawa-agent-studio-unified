"""
Admin API Models

Provides audit logging, tracking, and 2FA support for admin actions.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
from cryptography.fernet import Fernet
import uuid
import base64
import os


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


class Admin2FA(models.Model):
    """
    Two-Factor Authentication for admin users.

    Stores encrypted TOTP secrets and backup codes for admin accounts.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='admin_2fa'
    )

    # Encrypted TOTP secret (encrypted at rest)
    _encrypted_secret = models.BinaryField(
        db_column='encrypted_secret',
        help_text="Encrypted TOTP secret key"
    )

    # 2FA status
    is_enabled = models.BooleanField(
        default=False,
        help_text="Whether 2FA is enabled for this admin"
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="Whether the user has verified their 2FA setup"
    )

    # Backup codes (JSON list of hashed codes)
    backup_codes = models.JSONField(
        default=list,
        blank=True,
        help_text="Hashed backup codes for recovery"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    enabled_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Admin 2FA'
        verbose_name_plural = 'Admin 2FA'

    def __str__(self):
        status = "Enabled" if self.is_enabled else "Disabled"
        return f"{self.user.email} - 2FA {status}"

    @staticmethod
    def _get_encryption_key():
        """Get or generate encryption key for TOTP secrets."""
        key = getattr(settings, 'ADMIN_2FA_ENCRYPTION_KEY', None)
        if key:
            return key.encode() if isinstance(key, str) else key

        # Fall back to deriving from SECRET_KEY
        secret = settings.SECRET_KEY.encode()
        # Use first 32 bytes as Fernet key (base64 encoded)
        return base64.urlsafe_b64encode(secret[:32])

    @property
    def secret(self):
        """Decrypt and return the TOTP secret."""
        if not self._encrypted_secret:
            return None
        try:
            key = self._get_encryption_key()
            f = Fernet(key)
            return f.decrypt(bytes(self._encrypted_secret)).decode()
        except Exception:
            return None

    @secret.setter
    def secret(self, value):
        """Encrypt and store the TOTP secret."""
        if value:
            key = self._get_encryption_key()
            f = Fernet(key)
            self._encrypted_secret = f.encrypt(value.encode())
        else:
            self._encrypted_secret = None

    def generate_secret(self):
        """Generate a new TOTP secret."""
        import pyotp
        self.secret = pyotp.random_base32()
        return self.secret

    def get_totp_uri(self, issuer="Webbotify Admin"):
        """Get the TOTP provisioning URI for QR code generation."""
        import pyotp
        if not self.secret:
            return None
        totp = pyotp.TOTP(self.secret)
        return totp.provisioning_uri(name=self.user.email, issuer_name=issuer)

    def verify_code(self, code):
        """Verify a TOTP code."""
        import pyotp
        if not self.secret:
            return False
        totp = pyotp.TOTP(self.secret)
        # Allow 1 time step tolerance (30 seconds before/after)
        return totp.verify(code, valid_window=1)

    def generate_backup_codes(self, count=10):
        """Generate backup codes for recovery."""
        import hashlib
        import secrets

        codes = []
        hashed_codes = []

        for _ in range(count):
            # Generate 8-character alphanumeric code
            code = secrets.token_hex(4).upper()
            codes.append(code)
            # Store hashed version
            hashed = hashlib.sha256(code.encode()).hexdigest()
            hashed_codes.append(hashed)

        self.backup_codes = hashed_codes
        return codes  # Return plain codes to show user once

    def verify_backup_code(self, code):
        """Verify and consume a backup code."""
        import hashlib
        hashed = hashlib.sha256(code.upper().encode()).hexdigest()

        if hashed in self.backup_codes:
            # Remove used code
            self.backup_codes.remove(hashed)
            self.save(update_fields=['backup_codes'])
            return True
        return False

    def enable(self):
        """Enable 2FA for this admin."""
        self.is_enabled = True
        self.is_verified = True
        self.enabled_at = timezone.now()
        self.save()

    def disable(self):
        """Disable 2FA for this admin."""
        self.is_enabled = False
        self.is_verified = False
        self._encrypted_secret = None
        self.backup_codes = []
        self.enabled_at = None
        self.save()

    def record_use(self):
        """Record that 2FA was used."""
        self.last_used_at = timezone.now()
        self.save(update_fields=['last_used_at'])

    @classmethod
    def is_2fa_enabled(cls, user):
        """Check if 2FA is enabled for a user."""
        try:
            return cls.objects.get(user=user).is_enabled
        except cls.DoesNotExist:
            return False

    @classmethod
    def get_or_create_for_user(cls, user):
        """Get or create 2FA record for a user."""
        obj, created = cls.objects.get_or_create(user=user)
        return obj


# ===========================================
# Alerting System
# ===========================================

class AlertRule(models.Model):
    """
    Configurable alert rules for monitoring critical events.

    Admins can create rules to receive notifications when certain
    conditions are met (e.g., too many failed logins, job failures).
    """
    ALERT_TYPES = [
        ('failed_logins', 'Multiple Failed Login Attempts'),
        ('job_failures', 'Indexing Job Failures'),
        ('system_health', 'System Health Degradation'),
        ('quota_exceeded', 'Organization Quota Exceeded'),
        ('security_event', 'Security Event Detected'),
        ('high_error_rate', 'High Error Rate'),
        ('suspicious_activity', 'Suspicious Activity'),
    ]

    SEVERITY_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    NOTIFICATION_CHANNELS = [
        ('email', 'Email'),
        ('webhook', 'Webhook'),
        ('slack', 'Slack'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='medium')

    # Conditions (JSON)
    conditions = models.JSONField(
        default=dict,
        help_text="Alert conditions (e.g., {'threshold': 5, 'time_window_minutes': 10})"
    )

    # Notification settings
    notification_channel = models.CharField(
        max_length=20,
        choices=NOTIFICATION_CHANNELS,
        default='email'
    )
    notification_target = models.CharField(
        max_length=500,
        help_text="Email address, webhook URL, or Slack channel"
    )

    # Cooldown to prevent spam
    cooldown_minutes = models.IntegerField(
        default=30,
        help_text="Minimum minutes between repeated alerts"
    )

    is_enabled = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_alert_rules'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Alert Rule'
        verbose_name_plural = 'Alert Rules'

    def __str__(self):
        return f"{self.name} ({self.get_alert_type_display()})"

    def can_send_alert(self):
        """Check if cooldown period has passed since last alert."""
        if self.cooldown_minutes == 0:
            return True

        last_notification = self.notifications.order_by('-sent_at').first()
        if not last_notification:
            return True

        cooldown_end = last_notification.sent_at + timezone.timedelta(minutes=self.cooldown_minutes)
        return timezone.now() >= cooldown_end


class AlertNotification(models.Model):
    """
    Record of sent alert notifications.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name='notifications'
    )

    # Alert details
    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=20, choices=AlertRule.SEVERITY_LEVELS)

    # Delivery status
    sent_at = models.DateTimeField(auto_now_add=True)
    delivered = models.BooleanField(default=False)
    delivery_error = models.TextField(blank=True)

    # Context data
    context = models.JSONField(
        default=dict,
        help_text="Additional context data about the alert"
    )

    class Meta:
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['rule', 'sent_at']),
        ]
        verbose_name = 'Alert Notification'
        verbose_name_plural = 'Alert Notifications'

    def __str__(self):
        return f"{self.title} - {self.sent_at}"


class SystemAlert(models.Model):
    """
    Active system alerts displayed in the admin dashboard.
    """
    ALERT_LEVELS = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=255)
    message = models.TextField()
    level = models.CharField(max_length=20, choices=ALERT_LEVELS, default='warning')

    # Link to related object (optional)
    related_type = models.CharField(max_length=50, blank=True)
    related_id = models.CharField(max_length=100, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_alerts'
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    # Auto-resolve settings
    auto_resolve = models.BooleanField(
        default=False,
        help_text="Automatically resolve when condition clears"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Alert expires after this time"
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', 'level']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = 'System Alert'
        verbose_name_plural = 'System Alerts'

    def __str__(self):
        return f"[{self.get_level_display()}] {self.title}"

    def acknowledge(self, user):
        """Acknowledge this alert."""
        self.is_acknowledged = True
        self.acknowledged_by = user
        self.acknowledged_at = timezone.now()
        self.save()

    def resolve(self):
        """Resolve this alert."""
        self.is_active = False
        self.resolved_at = timezone.now()
        self.save()

    @classmethod
    def get_active_alerts(cls):
        """Get all active, non-expired alerts."""
        now = timezone.now()
        return cls.objects.filter(
            is_active=True
        ).exclude(
            expires_at__lt=now
        ).order_by('-level', '-created_at')

    @classmethod
    def create_alert(cls, title, message, level='warning', related_type='', related_id='',
                     auto_resolve=False, expires_hours=None):
        """Create a new system alert."""
        expires_at = None
        if expires_hours:
            expires_at = timezone.now() + timezone.timedelta(hours=expires_hours)

        return cls.objects.create(
            title=title,
            message=message,
            level=level,
            related_type=related_type,
            related_id=related_id,
            auto_resolve=auto_resolve,
            expires_at=expires_at
        )


# ===========================================
# Announcements
# ===========================================

class Announcement(models.Model):
    """
    System-wide announcements displayed to users.
    
    Admins can create announcements that appear as banners or modals
    in the user-facing application.
    """
    ANNOUNCEMENT_TYPES = [
        ('banner', 'Banner (Top of page)'),
        ('modal', 'Modal (Popup)'),
        ('toast', 'Toast (Corner notification)'),
    ]

    ANNOUNCEMENT_STYLES = [
        ('info', 'Information (Blue)'),
        ('warning', 'Warning (Yellow)'),
        ('success', 'Success (Green)'),
        ('error', 'Error (Red)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=255)
    message = models.TextField()
    
    # Display settings
    announcement_type = models.CharField(
        max_length=20,
        choices=ANNOUNCEMENT_TYPES,
        default='banner'
    )
    style = models.CharField(
        max_length=20,
        choices=ANNOUNCEMENT_STYLES,
        default='info'
    )
    
    # Optional link
    link_url = models.URLField(blank=True, help_text="Optional action link")
    link_text = models.CharField(max_length=100, blank=True, help_text="Text for the action link")
    
    # Display options
    is_dismissible = models.BooleanField(
        default=True,
        help_text="Users can dismiss this announcement"
    )
    show_to_all = models.BooleanField(
        default=True,
        help_text="Show to all users (otherwise only to specific tiers)"
    )
    target_tiers = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tier names to show to (if not showing to all)"
    )
    
    # Scheduling
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When to start showing (immediately if null)"
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When to stop showing (never if null)"
    )
    
    # Tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_announcements'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Stats
    view_count = models.IntegerField(default=0)
    dismiss_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Announcement'
        verbose_name_plural = 'Announcements'

    def __str__(self):
        return f"{self.title} ({self.get_announcement_type_display()})"

    @classmethod
    def get_active_announcements(cls, tier=None):
        """Get currently active announcements for a user's tier."""
        now = timezone.now()
        
        announcements = cls.objects.filter(
            is_active=True
        ).exclude(
            starts_at__gt=now  # Hasn't started yet
        ).exclude(
            expires_at__lt=now  # Already expired
        ).order_by('-created_at')
        
        if tier:
            # Filter by tier if specified
            announcements = announcements.filter(
                models.Q(show_to_all=True) | 
                models.Q(target_tiers__contains=[tier])
            )
        
        return announcements

    def record_view(self):
        """Record that the announcement was viewed."""
        self.view_count = models.F('view_count') + 1
        self.save(update_fields=['view_count'])

    def record_dismiss(self):
        """Record that the announcement was dismissed."""
        self.dismiss_count = models.F('dismiss_count') + 1
        self.save(update_fields=['dismiss_count'])


# ===========================================
# Feature Flags
# ===========================================

class FeatureFlag(models.Model):
    """
    Feature flags for toggling platform features without deployment.
    
    Enables admins to enable/disable features for all users, specific tiers,
    or even specific users (for beta testing).
    """
    ROLLOUT_STRATEGIES = [
        ('all', 'All Users'),
        ('tier', 'By Tier'),
        ('percentage', 'Percentage of Users'),
        ('users', 'Specific Users'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Basic info
    key = models.CharField(
        max_length=100,
        unique=True,
        help_text="Unique identifier for the feature flag (e.g., 'new_dashboard')"
    )
    name = models.CharField(max_length=255, help_text="Human-readable name")
    description = models.TextField(blank=True, help_text="Description of what this flag controls")
    
    # Status
    is_enabled = models.BooleanField(
        default=False,
        help_text="Whether this feature is enabled"
    )
    
    # Rollout strategy
    rollout_strategy = models.CharField(
        max_length=20,
        choices=ROLLOUT_STRATEGIES,
        default='all'
    )
    
    # Strategy-specific settings
    target_tiers = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tiers to enable for (when strategy is 'tier')"
    )
    rollout_percentage = models.IntegerField(
        default=100,
        help_text="Percentage of users to enable for (when strategy is 'percentage')"
    )
    target_user_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="List of user IDs to enable for (when strategy is 'users')"
    )
    
    # Metadata
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_feature_flags'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Optional: environment
    environment = models.CharField(
        max_length=20,
        default='all',
        help_text="Environment this flag applies to: 'all', 'development', 'staging', 'production'"
    )

    class Meta:
        ordering = ['key']
        verbose_name = 'Feature Flag'
        verbose_name_plural = 'Feature Flags'

    def __str__(self):
        status = "Enabled" if self.is_enabled else "Disabled"
        return f"{self.key} ({status})"

    def is_enabled_for_user(self, user):
        """Check if this feature is enabled for a specific user."""
        if not self.is_enabled:
            return False
        
        if self.rollout_strategy == 'all':
            return True
        
        elif self.rollout_strategy == 'tier':
            # Check user's tier
            from apps.organizations.models import Membership
            membership = Membership.objects.filter(user=user).first()
            if membership and hasattr(membership.organization, 'subscription'):
                user_tier = membership.organization.subscription.plan
                return user_tier in self.target_tiers
            return 'basic' in self.target_tiers
        
        elif self.rollout_strategy == 'percentage':
            # Use user ID to deterministically assign
            import hashlib
            hash_value = int(hashlib.md5(str(user.id).encode()).hexdigest(), 16)
            return (hash_value % 100) < self.rollout_percentage
        
        elif self.rollout_strategy == 'users':
            return str(user.id) in self.target_user_ids
        
        return False

    @classmethod
    def get_all_flags_for_user(cls, user):
        """Get all enabled feature flags for a user."""
        flags = cls.objects.filter(is_enabled=True)
        return {
            flag.key: flag.is_enabled_for_user(user)
            for flag in flags
        }

    @classmethod
    def is_flag_enabled(cls, key, user=None):
        """Check if a specific feature flag is enabled."""
        try:
            flag = cls.objects.get(key=key)
            if user:
                return flag.is_enabled_for_user(user)
            return flag.is_enabled
        except cls.DoesNotExist:
            return False
