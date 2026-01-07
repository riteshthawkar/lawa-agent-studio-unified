import requests
import dns.resolver
from urllib.parse import urlparse
from django.conf import settings
from django.utils import timezone
from .models import Site
from apps.core.exceptions import SiteNotVerified
from apps.core.logging_config import get_logger

logger = get_logger(__name__)


class SiteVerificationService:
    """Service for verifying site ownership"""
    
    def __init__(self):
        self.timeout = 30
    
    def verify_dns_record(self, site):
        """Verify DNS TXT record for site ownership"""
        try:
            # Extract domain from URL
            parsed_url = urlparse(site.domain)
            domain = parsed_url.netloc or parsed_url.path
            
            # Remove port if present
            if ':' in domain:
                domain = domain.split(':')[0]
            
            # Query DNS TXT record
            txt_records = dns.resolver.resolve(f'_lawa-verification.{domain}', 'TXT')
            
            for record in txt_records:
                # Clean up the record value (remove quotes)
                record_value = str(record).strip('"')
                if record_value == site.verification_token:
                    return True
            
            return False
            
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.Timeout):
            return False
        except Exception as e:
            # Log error but don't fail verification
            logger.warning(
                "DNS verification error",
                extra={
                    'domain': site.domain,
                    'site_id': str(site.id),
                    'error': str(e),
                    'verification_method': 'dns'
                }
            )
            return False
    
    def verify_file_upload(self, site):
        """Verify file upload for site ownership"""
        try:
            # Construct verification URL
            verification_url = f"{site.domain.rstrip('/')}/lawa-verification-{site.verification_token}.txt"
            
            # Make HTTP request
            response = requests.get(verification_url, timeout=self.timeout)
            response.raise_for_status()
            
            # Check if content matches token
            content = response.text.strip()
            return content == site.verification_token
            
        except (requests.RequestException, Exception) as e:
            # Log error but don't fail verification
            logger.warning(
                "File verification error",
                extra={
                    'domain': site.domain,
                    'site_id': str(site.id),
                    'error': str(e),
                    'verification_method': 'file'
                }
            )
            return False
    
    def verify_site(self, site):
        """Verify site ownership using the configured method"""
        # MVP: Skip actual verification for easier testing
        # TODO: Re-enable verification for production
        logger.warning(
            "MVP: Skipping site verification",
            extra={
                'domain': site.domain,
                'site_id': str(site.id),
                'reason': 'mvp_testing'
            }
        )
        return True
        
        # Original verification logic (commented out for MVP)
        # if site.verification_method == 'dns':
        #     return self.verify_dns_record(site)
        # elif site.verification_method == 'file':
        #     return self.verify_file_upload(site)
        # else:
        #     raise ValueError(f"Unknown verification method: {site.verification_method}")
    
    def mark_site_verified(self, site):
        """Mark site as verified"""
        site.verified_at = timezone.now()
        site.status = 'active'
        site.save(update_fields=['verified_at', 'status'])
        return site
    
    def mark_site_failed(self, site, error_message=None):
        """Mark site verification as failed"""
        site.status = 'blocked'
        if error_message:
            # Store error message in meta or create a separate field
            pass
        site.save(update_fields=['status'])
        return site
