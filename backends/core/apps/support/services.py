"""
Notification services for support module.

Handles email notifications for feedback and support-related events.
"""

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
from apps.core.logging_config import get_logger

logger = get_logger(__name__)


class FeedbackNotificationService:
    """Service for sending feedback-related email notifications"""

    # Feedback type display names
    FEEDBACK_TYPE_DISPLAY = {
        'bug': 'Bug Report',
        'feature': 'Feature Request',
        'general': 'General Feedback',
        'complaint': 'Complaint',
        'praise': 'Praise',
    }

    def __init__(self):
        """Initialize notification service"""
        self.from_email = settings.DEFAULT_FROM_EMAIL
        # Get admin emails from settings, fallback to empty list
        self.admin_emails = getattr(settings, 'FEEDBACK_ADMIN_EMAILS', [])
        # If no specific feedback admin emails, try general admin emails
        if not self.admin_emails:
            self.admin_emails = [email for name, email in getattr(settings, 'ADMINS', [])]

    def get_feedback_type_display(self, feedback_type):
        """Get human-readable feedback type"""
        return self.FEEDBACK_TYPE_DISPLAY.get(feedback_type, feedback_type.title())

    def send_admin_notification(self, feedback):
        """
        Send email notification to admins when new feedback is submitted.

        Args:
            feedback: Feedback model instance

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        if not self.admin_emails:
            logger.warning(
                "No admin emails configured for feedback notifications",
                extra={'feedback_id': str(feedback.id)}
            )
            return False

        feedback_type_display = self.get_feedback_type_display(feedback.feedback_type)

        # Build admin URL
        admin_url = f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')}/admin/feedback"

        # Prepare template context
        context = {
            'feedback_type': feedback.feedback_type,
            'feedback_type_display': feedback_type_display,
            'priority': feedback.priority,
            'user_email': feedback.user.email if feedback.user else feedback.email,
            'user_name': feedback.user.name if feedback.user and hasattr(feedback.user, 'name') else None,
            'subject': feedback.subject,
            'message': feedback.message,
            'steps_to_reproduce': feedback.steps_to_reproduce,
            'expected_behavior': feedback.expected_behavior,
            'actual_behavior': feedback.actual_behavior,
            'submitted_at': feedback.created_at.strftime('%B %d, %Y at %I:%M %p UTC'),
            'admin_url': admin_url,
        }

        # Determine email subject based on priority
        if feedback.priority == 'critical':
            subject_prefix = '[CRITICAL] '
        elif feedback.priority == 'high':
            subject_prefix = '[HIGH] '
        else:
            subject_prefix = ''

        subject = f"{subject_prefix}New {feedback_type_display} Received - Lawa Agent Studio"

        try:
            # Render HTML template
            html_content = render_to_string('emails/feedback_admin_notification.html', context)
            text_content = strip_tags(html_content)

            # Send email to all admins
            msg = EmailMultiAlternatives(
                subject,
                text_content,
                self.from_email,
                self.admin_emails
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            logger.info(
                "Admin notification sent for feedback",
                extra={
                    'feedback_id': str(feedback.id),
                    'feedback_type': feedback.feedback_type,
                    'priority': feedback.priority,
                    'admin_emails': self.admin_emails
                }
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to send admin notification for feedback",
                extra={
                    'feedback_id': str(feedback.id),
                    'error': str(e)
                },
                exc_info=True
            )
            return False

    def send_status_update_notification(self, feedback, old_status, new_status, admin_notes=None):
        """
        Send email notification to user when feedback status is updated.

        Args:
            feedback: Feedback model instance
            old_status: Previous status value
            new_status: New status value
            admin_notes: Optional notes from admin

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        # Get user email
        user_email = feedback.user.email if feedback.user else feedback.email
        if not user_email:
            logger.warning(
                "No user email available for status update notification",
                extra={'feedback_id': str(feedback.id)}
            )
            return False

        feedback_type_display = self.get_feedback_type_display(feedback.feedback_type)

        # Status display names
        status_display = {
            'pending': 'Pending',
            'in_review': 'In Review',
            'in_progress': 'In Progress',
            'resolved': 'Resolved',
            'closed': 'Closed',
            'wont_fix': "Won't Fix",
        }

        # Build help center URL
        help_center_url = f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')}/help-center"

        # Prepare template context
        context = {
            'feedback_type': feedback.feedback_type,
            'feedback_type_display': feedback_type_display,
            'subject': feedback.subject,
            'old_status': status_display.get(old_status, old_status),
            'new_status': status_display.get(new_status, new_status),
            'new_status_value': new_status,
            'admin_notes': admin_notes,
            'submitted_at': feedback.created_at.strftime('%B %d, %Y'),
            'updated_at': timezone.now().strftime('%B %d, %Y at %I:%M %p UTC'),
            'help_center_url': help_center_url,
            'user_name': feedback.user.name if feedback.user and hasattr(feedback.user, 'name') else None,
        }

        subject = f"Your {feedback_type_display} Status Updated - Lawa Agent Studio"

        try:
            # Render HTML template
            html_content = render_to_string('emails/feedback_status_update.html', context)
            text_content = strip_tags(html_content)

            msg = EmailMultiAlternatives(
                subject,
                text_content,
                self.from_email,
                [user_email]
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            logger.info(
                "Status update notification sent to user",
                extra={
                    'feedback_id': str(feedback.id),
                    'user_email': user_email,
                    'old_status': old_status,
                    'new_status': new_status
                }
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to send status update notification",
                extra={
                    'feedback_id': str(feedback.id),
                    'user_email': user_email,
                    'error': str(e)
                },
                exc_info=True
            )
            return False


# Singleton instance for convenience
feedback_notification_service = FeedbackNotificationService()
