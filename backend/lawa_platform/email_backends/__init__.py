"""
Resend Email Backend for Django

This backend uses the Resend API to send emails instead of SMTP.
"""
import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class ResendEmailBackend(BaseEmailBackend):
    """
    Email backend that uses Resend API.
    
    Configure in settings:
        EMAIL_BACKEND = 'lawa_platform.email_backends.resend_backend.ResendEmailBackend'
        RESEND_API_KEY = 'your-api-key'
        DEFAULT_FROM_EMAIL = 'your@email.com'
    """
    
    def __init__(self, api_key=None, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or getattr(settings, 'RESEND_API_KEY', None)
        if self.api_key:
            resend.api_key = self.api_key
    
    def send_messages(self, email_messages):
        """Send one or more EmailMessage objects and return the number of email messages sent."""
        if not self.api_key:
            if not self.fail_silently:
                raise ValueError("RESEND_API_KEY is not configured")
            return 0
        
        num_sent = 0
        for message in email_messages:
            try:
                self._send(message)
                num_sent += 1
            except Exception as e:
                if not self.fail_silently:
                    raise
        return num_sent
    
    def _send(self, message):
        """Send a single EmailMessage using Resend API."""
        # Get recipients
        to_emails = list(message.to) if message.to else []
        cc_emails = list(message.cc) if message.cc else []
        bcc_emails = list(message.bcc) if message.bcc else []
        
        # Build the email params
        params = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": to_emails,
            "subject": message.subject,
        }
        
        # Add CC and BCC if present
        if cc_emails:
            params["cc"] = cc_emails
        if bcc_emails:
            params["bcc"] = bcc_emails
        
        # Handle HTML vs plain text
        if hasattr(message, 'alternatives') and message.alternatives:
            # This is an EmailMultiAlternatives with HTML
            for content, mimetype in message.alternatives:
                if mimetype == 'text/html':
                    params["html"] = content
                    break
        
        # Always include plain text body
        if message.body:
            if "html" in params:
                # If we have HTML, body becomes text fallback
                params["text"] = message.body
            else:
                # No HTML, use body as text content
                params["text"] = message.body
        
        # If we only have text but no html, that's fine
        # If we have neither, send empty text
        if "html" not in params and "text" not in params:
            params["text"] = ""
        
        # Reply-to header
        if message.reply_to:
            params["reply_to"] = list(message.reply_to)
        
        # Send via Resend API
        response = resend.Emails.send(params)
        return response
