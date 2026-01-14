"""
Geo-location utility for IP-based location lookup.
Uses MaxMind GeoLite2 database for server-side IP geolocation.

For production use:
1. Download GeoLite2-City.mmdb from MaxMind (free registration required)
2. Place it in the data/ directory or set GEOIP_DATABASE_PATH env var
3. Update periodically (MaxMind updates weekly)

Alternative: Use IP-API or similar service for lightweight deployments.
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import geoip2 - it's optional
try:
    import geoip2.database
    import geoip2.errors
    GEOIP_AVAILABLE = True
except ImportError:
    GEOIP_AVAILABLE = False
    logger.warning("geoip2 library not installed. Geo-location features will be disabled.")


@dataclass
class GeoLocation:
    """Geo-location data container."""
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'country_code': self.country_code,
            'country_name': self.country_name,
            'region': self.region,
            'city': self.city
        }


class GeoLocationService:
    """
    Service for IP-based geo-location lookup.
    Uses MaxMind GeoLite2 database for server-side lookups.
    """

    def __init__(self):
        self._reader = None
        self._initialized = False
        self._initialize()

    def _initialize(self):
        """Initialize the GeoIP database reader."""
        if not GEOIP_AVAILABLE:
            logger.info("GeoIP not available - geo-location disabled")
            return

        # Look for database in common locations
        db_paths = [
            os.getenv('GEOIP_DATABASE_PATH', ''),
            './GeoLite2-City.mmdb',
            './data/GeoLite2-City.mmdb',
            '/usr/share/GeoIP/GeoLite2-City.mmdb',
            os.path.expanduser('~/.local/share/GeoIP/GeoLite2-City.mmdb'),
        ]

        for db_path in db_paths:
            if db_path and os.path.exists(db_path):
                try:
                    self._reader = geoip2.database.Reader(db_path)
                    self._initialized = True
                    logger.info(f"GeoIP database loaded from: {db_path}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to load GeoIP database from {db_path}: {e}")

        logger.warning("GeoIP database not found. Geo-location will be disabled.")

    def lookup(self, ip_address: str) -> GeoLocation:
        """
        Look up geo-location for an IP address.

        Args:
            ip_address: The IP address to look up

        Returns:
            GeoLocation object with available location data
        """
        result = GeoLocation()

        if not self._initialized or not ip_address:
            return result

        # Skip private/local IPs
        if self._is_private_ip(ip_address):
            logger.debug(f"Skipping geo-lookup for private IP: {ip_address}")
            return result

        try:
            response = self._reader.city(ip_address)

            result.country_code = response.country.iso_code
            result.country_name = response.country.name
            result.region = response.subdivisions.most_specific.name if response.subdivisions else None
            result.city = response.city.name

            if response.location:
                result.latitude = response.location.latitude
                result.longitude = response.location.longitude

            logger.debug(f"Geo-lookup for {ip_address}: {result.country_code}, {result.city}")

        except geoip2.errors.AddressNotFoundError:
            logger.debug(f"IP address not found in GeoIP database: {ip_address}")
        except Exception as e:
            logger.warning(f"Error during geo-lookup for {ip_address}: {e}")

        return result

    def _is_private_ip(self, ip_address: str) -> bool:
        """Check if an IP address is private/local."""
        if not ip_address:
            return True

        # Common private/local IP patterns
        private_patterns = [
            '127.',
            '10.',
            '192.168.',
            '172.16.', '172.17.', '172.18.', '172.19.',
            '172.20.', '172.21.', '172.22.', '172.23.',
            '172.24.', '172.25.', '172.26.', '172.27.',
            '172.28.', '172.29.', '172.30.', '172.31.',
            'localhost',
            '::1',
            'fe80:',
        ]

        for pattern in private_patterns:
            if ip_address.startswith(pattern):
                return True

        return False

    def close(self):
        """Close the database reader."""
        if self._reader:
            self._reader.close()
            self._reader = None
            self._initialized = False


# Global service instance
_geo_service: Optional[GeoLocationService] = None


def get_geo_service() -> GeoLocationService:
    """Get or create the global geo-location service instance."""
    global _geo_service
    if _geo_service is None:
        _geo_service = GeoLocationService()
    return _geo_service


def lookup_ip(ip_address: str) -> GeoLocation:
    """
    Convenience function to look up geo-location for an IP address.

    Args:
        ip_address: The IP address to look up

    Returns:
        GeoLocation object with available location data
    """
    return get_geo_service().lookup(ip_address)


def get_client_ip_from_websocket(websocket) -> Optional[str]:
    """
    Extract client IP from WebSocket connection.
    Handles proxy headers (X-Forwarded-For, X-Real-IP).

    Args:
        websocket: FastAPI WebSocket object

    Returns:
        Client IP address or None
    """
    # Check for proxy headers first (for load balancers, nginx, etc.)
    forwarded_for = websocket.headers.get('x-forwarded-for')
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs: client, proxy1, proxy2
        # The first IP is the original client
        return forwarded_for.split(',')[0].strip()

    real_ip = websocket.headers.get('x-real-ip')
    if real_ip:
        return real_ip.strip()

    # Fall back to direct connection IP
    if hasattr(websocket, 'client') and websocket.client:
        return websocket.client.host

    return None
