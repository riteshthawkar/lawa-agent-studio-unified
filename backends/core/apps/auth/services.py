"""
Authentication service layer for handling business logic.

Consolidates common authentication operations like OTP generation,
email verification, and email sending.
"""

import secrets
from datetime import timedelta
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from apps.core.logging_config import get_logger
from .models import EmailVerification

logger = get_logger(__name__)


class AuthenticationService:
    """Service class for authentication-related operations"""

    # OTP Configuration
    OTP_EXPIRY_MINUTES = 15
    OTP_LENGTH = 6

    def __init__(self):
        """Initialize authentication service"""
        self.from_email = settings.DEFAULT_FROM_EMAIL

    def generate_otp(self):
        """
        Generate a secure random OTP.

        Returns:
            str: 6-digit OTP string with leading zeros
        """
        otp = secrets.randbelow(10 ** self.OTP_LENGTH)
        otp_str = f"{otp:0{self.OTP_LENGTH}d}"
        return otp_str

    def create_email_verification(self, email, otp=None):
        """
        Create or update email verification record with OTP.

        Args:
            email (str): Email address to verify
            otp (str, optional): OTP code. If not provided, generates new one.

        Returns:
            tuple: (EmailVerification instance, otp_str)
        """
        if otp is None:
            otp = self.generate_otp()

        expires_at = timezone.now() + timedelta(minutes=self.OTP_EXPIRY_MINUTES)

        verification = EmailVerification.objects.create(
            email=email,
            otp=otp,
            expires_at=expires_at
        )

        logger.info(
            "Email verification created",
            extra={
                'email': email,
                'expires_at': expires_at.isoformat(),
                'verification_id': str(verification.id)
            }
        )

        return verification, otp

    def send_verification_email(self, email, otp, user=None, email_type='registration'):
        """
        Send OTP verification email using HTML template.

        Args:
            email (str): Recipient email address
            otp (str): OTP code to send
            user (User, optional): User instance (for logging)
            email_type (str): Type of email ('registration', 'otp_resend', 'unverified_login')

        Returns:
            bool: True if email sent successfully, False otherwise

        Raises:
            Exception: If email sending fails
        """
        subject = 'Verify your email - Lawa Webbotify'

        # Render HTML template
        html_content = render_to_string('emails/verification_email.html', {'otp': otp})
        text_content = strip_tags(html_content)

        recipient_list = [email]

        try:
            msg = EmailMultiAlternatives(subject, text_content, self.from_email, recipient_list)
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            logger.info(
                "Verification email sent successfully",
                extra={
                    'email': email,
                    'user_id': str(user.id) if user else None,
                    'email_type': email_type
                }
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to send verification email",
                extra={
                    'email': email,
                    'user_id': str(user.id) if user else None,
                    'error': str(e),
                    'email_type': email_type
                },
                exc_info=True
            )
            raise Exception(f"Failed to send verification email: {str(e)}")

    def verify_otp(self, email, otp):
        """
        Verify OTP code for email address.

        Args:
            email (str): Email address
            otp (str): OTP code to verify

        Returns:
            EmailVerification: Verification record if valid

        Raises:
            EmailVerification.DoesNotExist: If OTP is invalid or expired
        """
        verification = EmailVerification.objects.filter(
            email=email,
            otp=otp,
            expires_at__gt=timezone.now()
        ).latest('created_at')

        logger.info(
            "OTP verified successfully",
            extra={
                'email': email,
                'verification_id': str(verification.id)
            }
        )

        return verification

    def send_verification_and_create_record(self, email, user=None, email_type='registration'):
        """
        Convenience method to generate OTP, create verification record, and send email.

        Args:
            email (str): Email address
            user (User, optional): User instance
            email_type (str): Type of email

        Returns:
            str: Generated OTP

        Raises:
            Exception: If email sending fails
        """
        # Generate OTP and create verification record
        verification, otp = self.create_email_verification(email)

        # Send email
        self.send_verification_email(email, otp, user, email_type)

        return otp


def get_client_ip(request):
    """
    Extract client IP address from request.

    Handles proxy headers (X-Forwarded-For) and falls back to REMOTE_ADDR.

    Args:
        request: Django/DRF request object

    Returns:
        str: Client IP address
    """
    # Check for proxy headers first
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # X-Forwarded-For can contain multiple IPs, get the first one
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        # Fallback to REMOTE_ADDR
        ip = request.META.get('REMOTE_ADDR', 'unknown')

    return ip
