"""Runtime Settings Service

Allows runtime configuration of settings that can be modified
without restarting the application. Uses Redis for persistence.

The pattern here is:
1. Default value comes from environment/config (settings object)
2. Runtime overrides are stored in Redis
3. Code reads from runtime_settings() which checks Redis first,
   falling back to default if no override exists
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.cache import cache_service

# TTL for runtime settings (24 hours)
RUNTIME_SETTINGS_TTL = 86400
RUNTIME_SETTINGS_PREFIX = "settings:runtime:"


class RuntimeSettingsService:
    """Service for managing runtime settings overrides.
    
    Runtime settings take precedence over default config values
    and are stored in Redis for persistence across restarts.
    """

    def get(self, key: str, default: Any = None) -> Any:
        """Get a runtime setting value.
        
        Args:
            key: Setting key (e.g., 'max_upload_size_mb')
            default: Default value if not set
        
        Returns:
            The runtime override value or default
        """
        redis_key = f"{RUNTIME_SETTINGS_PREFIX}{key}"
        value = cache_service.get(redis_key)
        if value is not None:
            return value
        return default

    def set(self, key: str, value: Any, ttl_seconds: int = RUNTIME_SETTINGS_TTL) -> bool:
        """Set a runtime setting override.
        
        Args:
            key: Setting key
            value: Value to set
            ttl_seconds: How long to cache (default 24h)
        
        Returns:
            True if successful, False otherwise
        """
        redis_key = f"{RUNTIME_SETTINGS_PREFIX}{key}"
        return cache_service.set(redis_key, value, ttl_seconds)

    def delete(self, key: str) -> bool:
        """Remove a runtime setting override, reverting to default.
        
        Args:
            key: Setting key to remove
        
        Returns:
            True if deleted, False otherwise
        """
        redis_key = f"{RUNTIME_SETTINGS_PREFIX}{key}"
        return cache_service.delete(redis_key)

    def get_all_runtime(self) -> dict[str, Any]:
        """Get all runtime settings overrides.
        
        Returns:
            Dict of all runtime overrides
        """
        result = {}
        pattern = f"{RUNTIME_SETTINGS_PREFIX}*"
        try:
            client = cache_service.client
            for key in client.scan_iter(match=pattern, count=500):
                setting_key = key.replace(RUNTIME_SETTINGS_PREFIX, "")
                value = cache_service.get(key)
                if value is not None:
                    result[setting_key] = value
        except Exception:
            pass
        return result


runtime_settings = RuntimeSettingsService()


def get_max_upload_size_mb() -> int:
    """Get the current max upload size in MB.
    
    Checks runtime override first, falls back to config default.
    
    Returns:
        Max upload size in MB (default: 200)
    """
    return runtime_settings.get("max_upload_size_mb", settings.max_upload_size_mb)


def set_max_upload_size_mb(value: int) -> bool:
    """Set the max upload size in MB.
    
    Args:
        value: New max size in MB
    
    Returns:
        True if successful
    """
    if value <= 0:
        value = 1
    if value > 10000:
        value = 10000  # Hard ceiling of 10GB
    return runtime_settings.set("max_upload_size_mb", value)