"""
System Health and Monitoring Services

Provides health checks and system status information for the admin dashboard.
"""
import logging
from django.db import connection
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class SystemHealthService:
    """
    Service for checking system health and gathering operational metrics.
    """
    
    @classmethod
    def get_full_health_status(cls):
        """Get comprehensive health status of all system components."""
        # Cache individual checks to avoid redundant calls
        db_status = cls.check_database()
        cache_status = cls.check_cache()
        storage_status = cls.check_storage()
        
        # Calculate overall health using cached results
        overall = cls._calculate_overall_from_results(db_status, cache_status)
        
        return {
            'database': db_status,
            'cache': cache_status,
            'external_apis': cls.check_external_apis(),
            'queues': cls.get_queue_status(),
            'storage': storage_status,
            'overall': overall,
            'checked_at': timezone.now().isoformat()
        }
    
    @classmethod
    def check_database(cls):
        """Check database connectivity and basic performance."""
        try:
            start = timezone.now()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            latency_ms = (timezone.now() - start).total_seconds() * 1000
            
            return {
                'status': 'healthy',
                'latency_ms': round(latency_ms, 2),
                'message': 'Database connection successful'
            }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                'status': 'unhealthy',
                'latency_ms': None,
                'message': str(e)
            }
    
    @classmethod
    def check_cache(cls):
        """Check cache (Redis) connectivity."""
        try:
            start = timezone.now()
            test_key = 'health_check_test'
            cache.set(test_key, 'test_value', 10)
            result = cache.get(test_key)
            cache.delete(test_key)
            latency_ms = (timezone.now() - start).total_seconds() * 1000
            
            if result == 'test_value':
                return {
                    'status': 'healthy',
                    'latency_ms': round(latency_ms, 2),
                    'message': 'Cache connection successful'
                }
            else:
                return {
                    'status': 'degraded',
                    'latency_ms': round(latency_ms, 2),
                    'message': 'Cache read/write mismatch'
                }
        except Exception as e:
            logger.error(f"Cache health check failed: {e}")
            return {
                'status': 'unhealthy',
                'latency_ms': None,
                'message': str(e)
            }
    
    @classmethod
    def check_external_apis(cls):
        """Check external API connectivity (OpenAI, Pinecone, Stripe)."""
        results = {}
        
        # Check OpenAI
        try:
            import openai
            # Just check if the client can be created with valid config
            openai_key = getattr(settings, 'OPENAI_API_KEY', None)
            results['openai'] = {
                'status': 'configured' if openai_key else 'not_configured',
                'message': 'API key configured' if openai_key else 'API key missing'
            }
        except Exception as e:
            results['openai'] = {'status': 'error', 'message': str(e)}
        
        # Check Pinecone
        try:
            pinecone_key = getattr(settings, 'PINECONE_API_KEY', None)
            results['pinecone'] = {
                'status': 'configured' if pinecone_key else 'not_configured',
                'message': 'API key configured' if pinecone_key else 'API key missing'
            }
        except Exception as e:
            results['pinecone'] = {'status': 'error', 'message': str(e)}
        
        # Check Stripe
        try:
            stripe_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
            results['stripe'] = {
                'status': 'configured' if stripe_key else 'not_configured',
                'message': 'API key configured' if stripe_key else 'API key missing'
            }
        except Exception as e:
            results['stripe'] = {'status': 'error', 'message': str(e)}
        
        return results
    
    @classmethod
    def get_queue_status(cls):
        """Get indexing job queue status."""
        from apps.indexing.models import IndexingJob
        
        try:
            now = timezone.now()
            last_hour = now - timedelta(hours=1)
            last_24h = now - timedelta(hours=24)
            
            pending = IndexingJob.objects.filter(status='pending').count()
            running = IndexingJob.objects.filter(status='running').count()
            completed_1h = IndexingJob.objects.filter(
                status='completed',
                updated_at__gte=last_hour
            ).count()
            failed_24h = IndexingJob.objects.filter(
                status='failed',
                updated_at__gte=last_24h
            ).count()
            
            # Calculate average duration for completed jobs in last 24h
            from django.db.models import Avg, F
            avg_duration = IndexingJob.objects.filter(
                status='completed',
                updated_at__gte=last_24h,
                started_at__isnull=False,
                completed_at__isnull=False
            ).annotate(
                duration=F('completed_at') - F('started_at')
            ).aggregate(avg=Avg('duration'))
            
            avg_duration_seconds = None
            if avg_duration['avg']:
                avg_duration_seconds = avg_duration['avg'].total_seconds()
            
            return {
                'status': 'healthy' if failed_24h == 0 else 'degraded',
                'pending': pending,
                'running': running,
                'completed_last_hour': completed_1h,
                'failed_last_24h': failed_24h,
                'avg_duration_seconds': avg_duration_seconds
            }
        except Exception as e:
            logger.error(f"Queue status check failed: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    @classmethod
    def check_storage(cls):
        """Check file storage accessibility with actual write/read test."""
        try:
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            import time
            
            # Perform an actual write/read test
            test_filename = f'health_check_{int(time.time())}.txt'
            test_content = b'health_check_test'
            
            try:
                # Attempt to write
                path = default_storage.save(test_filename, ContentFile(test_content))
                
                # Attempt to read back
                if default_storage.exists(path):
                    # Cleanup
                    default_storage.delete(path)
                    return {
                        'status': 'healthy',
                        'backend': type(default_storage).__name__,
                        'message': 'Storage read/write successful'
                    }
                else:
                    return {
                        'status': 'degraded',
                        'backend': type(default_storage).__name__,
                        'message': 'File write succeeded but verification failed'
                    }
            except Exception as write_error:
                # Fallback: just check if storage is accessible
                return {
                    'status': 'degraded',
                    'backend': type(default_storage).__name__,
                    'message': f'Storage accessible but write test failed: {str(write_error)[:100]}'
                }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'message': str(e)
            }
    
    @classmethod
    def calculate_overall_health(cls):
        """Calculate overall system health based on component statuses."""
        db = cls.check_database()
        cache_status = cls.check_cache()
        return cls._calculate_overall_from_results(db, cache_status)
    
    @classmethod
    def _calculate_overall_from_results(cls, db_result, cache_result):
        """Calculate overall health from pre-fetched results (avoids redundant calls)."""
        if db_result['status'] == 'unhealthy':
            return 'critical'
        elif cache_result['status'] == 'unhealthy':
            return 'degraded'
        else:
            return 'healthy'
    
    @classmethod
    def get_error_summary(cls):
        """Get summary of recent errors from logs (placeholder)."""
        # In a production system, this would query an error tracking service
        # like Sentry or parse log files
        return {
            'last_hour': 0,
            'last_24h': 0,
            'top_errors': []
        }


class SystemMetricsService:
    """
    Service for gathering system usage metrics.
    """

    @classmethod
    def get_usage_metrics(cls):
        """Get usage metrics for the system."""
        from apps.auth.models import User
        from apps.organizations.models import Organization
        from apps.chat.models import ChatMessage
        from apps.sites.models import Site
        from apps.chatbot.models import Chatbot

        now = timezone.now()
        last_7d = now - timedelta(days=7)
        last_30d = now - timedelta(days=30)

        return {
            'users': {
                'total': User.objects.count(),
                'active_7d': User.objects.filter(last_login__gte=last_7d).count(),
                'new_30d': User.objects.filter(created_at__gte=last_30d).count()
            },
            'organizations': {
                'total': Organization.objects.count(),
                'active': Organization.objects.filter(status='active').count()
            },
            'sites': {
                'total': Site.objects.count(),
                'active': Site.objects.filter(status='active').count()
            },
            'chatbots': {
                'total': Chatbot.objects.count(),
                'active': Chatbot.objects.filter(status='active').count()
            },
            'messages': {
                'last_7d': ChatMessage.objects.filter(created_at__gte=last_7d).count(),
                'last_30d': ChatMessage.objects.filter(created_at__gte=last_30d).count()
            },
            'generated_at': now.isoformat()
        }


class AlertService:
    """
    Service for managing alerts and sending notifications.
    """

    @staticmethod
    def check_failed_logins(user_id=None, ip_address=None, time_window_minutes=10, threshold=5):
        """
        Check for multiple failed login attempts.

        Args:
            user_id: Optional user ID to check
            ip_address: Optional IP address to check
            time_window_minutes: Time window to look back
            threshold: Number of failures to trigger alert

        Returns:
            dict with 'triggered' boolean and 'details' if triggered
        """
        from apps.admin_api.models import LoginHistory

        since = timezone.now() - timedelta(minutes=time_window_minutes)

        query = LoginHistory.objects.filter(
            success=False,
            created_at__gte=since
        )

        if user_id:
            query = query.filter(user_id=user_id)
        if ip_address:
            query = query.filter(ip_address=ip_address)

        failed_count = query.count()

        if failed_count >= threshold:
            return {
                'triggered': True,
                'details': {
                    'failed_count': failed_count,
                    'time_window_minutes': time_window_minutes,
                    'threshold': threshold,
                    'user_id': str(user_id) if user_id else None,
                    'ip_address': ip_address
                }
            }

        return {'triggered': False}

    @staticmethod
    def check_job_failures(org_id=None, time_window_hours=1, threshold=3):
        """
        Check for indexing job failures.

        Args:
            org_id: Optional organization ID to check
            time_window_hours: Time window to look back
            threshold: Number of failures to trigger alert

        Returns:
            dict with 'triggered' boolean and 'details' if triggered
        """
        from apps.indexing.models import IndexingJob

        since = timezone.now() - timedelta(hours=time_window_hours)

        query = IndexingJob.objects.filter(
            status='failed',
            updated_at__gte=since
        )

        if org_id:
            query = query.filter(organization_id=org_id)

        failed_count = query.count()

        if failed_count >= threshold:
            sample_jobs = list(query.values('id', 'site__name', 'error_message')[:5])

            return {
                'triggered': True,
                'details': {
                    'failed_count': failed_count,
                    'time_window_hours': time_window_hours,
                    'threshold': threshold,
                    'org_id': str(org_id) if org_id else None,
                    'sample_jobs': sample_jobs
                }
            }

        return {'triggered': False}

    @staticmethod
    def check_system_health():
        """
        Check overall system health metrics.

        Returns:
            dict with 'triggered' boolean and 'details' if triggered
        """
        import psutil

        issues = []

        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 90:
            issues.append({
                'metric': 'cpu',
                'value': cpu_percent,
                'threshold': 90,
                'message': f'CPU usage is {cpu_percent}%'
            })

        memory = psutil.virtual_memory()
        if memory.percent > 90:
            issues.append({
                'metric': 'memory',
                'value': memory.percent,
                'threshold': 90,
                'message': f'Memory usage is {memory.percent}%'
            })

        disk = psutil.disk_usage('/')
        if disk.percent > 90:
            issues.append({
                'metric': 'disk',
                'value': disk.percent,
                'threshold': 90,
                'message': f'Disk usage is {disk.percent}%'
            })

        if issues:
            return {
                'triggered': True,
                'details': {
                    'issues': issues,
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'disk_percent': disk.percent
                }
            }

        return {'triggered': False}

    @staticmethod
    def check_quota_exceeded(org_id=None):
        """
        Check for organizations exceeding their quotas.

        Args:
            org_id: Optional organization ID to check

        Returns:
            dict with 'triggered' boolean and 'details' if triggered
        """
        from apps.organizations.models import Organization

        if org_id:
            orgs = Organization.objects.filter(id=org_id)
        else:
            orgs = Organization.objects.all()

        exceeded = []

        for org in orgs:
            usage = org.get_usage() if hasattr(org, 'get_usage') else {}
            limits = org.get_limits() if hasattr(org, 'get_limits') else {}

            for key, limit in limits.items():
                if limit and key in usage:
                    if usage[key] >= limit:
                        exceeded.append({
                            'org_id': str(org.id),
                            'org_name': org.name,
                            'resource': key,
                            'usage': usage[key],
                            'limit': limit
                        })

        if exceeded:
            return {
                'triggered': True,
                'details': {
                    'exceeded_count': len(exceeded),
                    'exceeded_orgs': exceeded[:10]
                }
            }

        return {'triggered': False}

    @classmethod
    def evaluate_rule(cls, rule):
        """
        Evaluate an alert rule and determine if it should trigger.

        Args:
            rule: AlertRule instance

        Returns:
            dict with 'triggered' boolean and 'details' if triggered
        """
        conditions = rule.conditions or {}

        if rule.alert_type == 'failed_logins':
            return cls.check_failed_logins(
                time_window_minutes=conditions.get('time_window_minutes', 10),
                threshold=conditions.get('threshold', 5)
            )

        elif rule.alert_type == 'job_failures':
            return cls.check_job_failures(
                time_window_hours=conditions.get('time_window_hours', 1),
                threshold=conditions.get('threshold', 3)
            )

        elif rule.alert_type == 'system_health':
            return cls.check_system_health()

        elif rule.alert_type == 'quota_exceeded':
            return cls.check_quota_exceeded()

        return {'triggered': False}

    @classmethod
    def send_notification(cls, rule, title, message, context=None):
        """
        Send a notification for an alert rule.

        Args:
            rule: AlertRule instance
            title: Notification title
            message: Notification message
            context: Additional context data

        Returns:
            AlertNotification instance
        """
        from apps.admin_api.models import AlertNotification
        import requests

        notification = AlertNotification.objects.create(
            rule=rule,
            title=title,
            message=message,
            severity=rule.severity,
            context=context or {}
        )

        try:
            if rule.notification_channel == 'email':
                cls._send_email_notification(rule, title, message)
            elif rule.notification_channel == 'webhook':
                cls._send_webhook_notification(rule, title, message, context)
            elif rule.notification_channel == 'slack':
                cls._send_slack_notification(rule, title, message, context)

            notification.delivered = True
            notification.save(update_fields=['delivered'])

        except Exception as e:
            logger.error(f"Failed to send notification for rule {rule.id}: {e}")
            notification.delivery_error = str(e)
            notification.save(update_fields=['delivery_error'])

        return notification

    @staticmethod
    def _send_email_notification(rule, title, message):
        """Send email notification using Resend."""
        try:
            import resend

            resend.api_key = getattr(settings, 'RESEND_API_KEY', None)
            if not resend.api_key:
                logger.warning("RESEND_API_KEY not configured, skipping email")
                return

            from_email = getattr(settings, 'ALERT_FROM_EMAIL', 'alerts@webbotify.com')

            resend.Emails.send({
                "from": from_email,
                "to": rule.notification_target,
                "subject": f"[{rule.severity.upper()}] {title}",
                "html": f"""
                <h2>{title}</h2>
                <p>{message}</p>
                <hr>
                <p><small>Alert Rule: {rule.name}</small></p>
                <p><small>Severity: {rule.get_severity_display()}</small></p>
                """
            })

        except ImportError:
            logger.warning("resend package not installed")
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            raise

    @staticmethod
    def _send_webhook_notification(rule, title, message, context=None):
        """Send webhook notification."""
        import requests

        payload = {
            'title': title,
            'message': message,
            'severity': rule.severity,
            'rule_name': rule.name,
            'alert_type': rule.alert_type,
            'timestamp': timezone.now().isoformat(),
            'context': context or {}
        }

        response = requests.post(
            rule.notification_target,
            json=payload,
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()

    @staticmethod
    def _send_slack_notification(rule, title, message, context=None):
        """Send Slack notification via webhook."""
        import requests

        severity_colors = {
            'low': '#36a64f',
            'medium': '#ffc107',
            'high': '#ff9800',
            'critical': '#dc3545'
        }

        payload = {
            'attachments': [{
                'color': severity_colors.get(rule.severity, '#808080'),
                'title': title,
                'text': message,
                'fields': [
                    {'title': 'Severity', 'value': rule.get_severity_display(), 'short': True},
                    {'title': 'Rule', 'value': rule.name, 'short': True}
                ],
                'ts': int(timezone.now().timestamp())
            }]
        }

        response = requests.post(
            rule.notification_target,
            json=payload,
            timeout=10
        )
        response.raise_for_status()

    @classmethod
    def process_alert_rules(cls):
        """
        Process all enabled alert rules and send notifications for triggered rules.

        This method should be called periodically (e.g., via Celery beat).

        Returns:
            dict with processing results
        """
        from apps.admin_api.models import AlertRule, SystemAlert

        rules = AlertRule.objects.filter(is_enabled=True)
        processed = 0
        triggered = 0
        errors = 0

        for rule in rules:
            try:
                processed += 1

                if not rule.can_send_alert():
                    continue

                result = cls.evaluate_rule(rule)

                if result.get('triggered'):
                    triggered += 1

                    title = f"{rule.get_alert_type_display()} Alert"
                    message = cls._build_alert_message(rule, result.get('details', {}))

                    cls.send_notification(rule, title, message, result.get('details'))

                    SystemAlert.create_alert(
                        title=title,
                        message=message,
                        level='critical' if rule.severity == 'critical' else 'warning',
                        auto_resolve=True,
                        expires_hours=24
                    )

            except Exception as e:
                errors += 1
                logger.error(f"Error processing alert rule {rule.id}: {e}")

        return {
            'processed': processed,
            'triggered': triggered,
            'errors': errors
        }

    @staticmethod
    def _build_alert_message(rule, details):
        """Build a human-readable alert message."""
        if rule.alert_type == 'failed_logins':
            return f"Detected {details.get('failed_count', 0)} failed login attempts in the last {details.get('time_window_minutes', 0)} minutes."

        elif rule.alert_type == 'job_failures':
            return f"Detected {details.get('failed_count', 0)} failed indexing jobs in the last {details.get('time_window_hours', 0)} hour(s)."

        elif rule.alert_type == 'system_health':
            issues = details.get('issues', [])
            issue_msgs = [i.get('message', '') for i in issues]
            return f"System health issues detected: {'; '.join(issue_msgs)}"

        elif rule.alert_type == 'quota_exceeded':
            count = details.get('exceeded_count', 0)
            return f"{count} organization(s) have exceeded their quota limits."

        return f"Alert triggered for rule: {rule.name}"

    @classmethod
    def create_manual_alert(cls, title, message, level='warning',
                           related_type='', related_id='', expires_hours=24):
        """
        Create a manual system alert (for admin-created alerts).

        Args:
            title: Alert title
            message: Alert message
            level: Alert level (info, warning, error, critical)
            related_type: Type of related object
            related_id: ID of related object
            expires_hours: Hours until alert expires

        Returns:
            SystemAlert instance
        """
        from apps.admin_api.models import SystemAlert

        return SystemAlert.create_alert(
            title=title,
            message=message,
            level=level,
            related_type=related_type,
            related_id=related_id,
            expires_hours=expires_hours
        )
