from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.core.config import settings
from app.services.cache import cache_service

logger = logging.getLogger(__name__)


# R3: the previous implementation did ``INCR`` then ``EXPIRE`` as two
# separate Redis calls. There were two problems:
#
# 1. If the process died between the two calls (or Redis had a network
#    blip) the key would have no TTL and the counter would accumulate
#    forever, locking the integration client out indefinitely.
# 2. The check ``if count == 1: expire(...)`` was racy: when two
#    requests race on a fresh key, both can read ``count == 1`` and
#    ``count == 2`` respectively; the second never sets a TTL.
#
# The Lua script below executes ``INCR`` and ``EXPIRE`` (only on the
# first call) atomically. If the script fails the call falls through
# and we silently allow the request — better to over-permit than to
# lock out a paying integration client.
_LUA_INCR_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


def enforce_integration_rate_limit(*, client_id: int, technician_id: str) -> None:
    limit = int(settings.integration_rate_limit_per_minute or 0)
    if limit <= 0:
        return
    key = f"rate_limit:integration:{client_id}:{technician_id}"
    try:
        # ``register_script`` returns a Script object that uses
        # ``EVALSHA`` on subsequent calls (no payload shipping
        # after the first invocation) which is the recommended
        # pattern in the redis-py docs.
        incr = cache_service.client.register_script(_LUA_INCR_WITH_TTL)
        count = int(incr(keys=[key], args=[60]))
    except Exception:
        # Fail open: we do not want a Redis blip to lock out a paying
        # integration client. Operators see the log line in Sentry.
        logger.warning("rate_limit_check_failed key=%s", key, exc_info=True)
        return
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Integration rate limit exceeded"
        )
