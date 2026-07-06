"""On-demand vision model manager.

LM Studio can only hold a small number of models in VRAM at once, and
each loaded model eats several GB. To keep things lean we treat the
vision model (qwen3-vl-8b-thinking in our setup) as an on-demand
resource:

  - Before any vision call, we ensure the model is loaded in LM Studio
    via the host-side ``lms_server.py`` shim (the container cannot
    execute the Windows ``lms.exe`` directly). If the model is already
    resident, this is a no-op (returns immediately).
  - After the call, we schedule a delayed unload so the GPU memory is
    released when no more image work is pending. New calls reset the
    timer (debounced), so a burst of image jobs keeps the model
    resident until things quiet down.

The container reaches the host shim at
``http://host.docker.internal:1235`` (or whatever ``LMS_SHIM_URL``
points to). On Linux hosts where ``lms`` is a native binary, the
manager also falls back to invoking it directly via subprocess.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger("app.services.vision_manager")


class VisionManager:
    """Singleton-ish helper that wraps the lms shim for vision lifecycle.

    Thread-safe: multiple vision calls from the same worker will
    serialise through ``_ops_lock`` so we never end up with a load
    racing an unload.
    """

    _unload_timer: threading.Timer | None = None
    _ops_lock = threading.Lock()
    _last_action_ts: float = 0.0
    # Cache the "is loaded" answer for a few seconds to avoid hitting
    # the shim on every single call.
    _loaded_cache: bool | None = None
    _loaded_cache_ts: float = 0.0
    _LOADED_CACHE_TTL = 5.0

    @classmethod
    def is_configured(cls) -> bool:
        """True if the on-demand manager is enabled and reachable."""
        from app.core.config import settings

        if not settings.vision_on_demand:
            return False
        if not settings.vision_model:
            return False
        return cls._shim_url() is not None or cls._find_lms() is not None

    # ------------------------------------------------------------------
    # Transport: HTTP shim (preferred) or direct lms subprocess (fallback)
    # ------------------------------------------------------------------
    @classmethod
    def _shim_url(cls) -> str | None:
        return os.environ.get("LMS_SHIM_URL") or "http://host.docker.internal:1235"

    @classmethod
    def _find_lms(cls) -> str | None:
        from app.core.config import settings

        override = os.environ.get("LMS_CLI_PATH") or settings.lms_cli_path
        if override and os.path.isfile(override):
            return override
        shim = "/usr/local/bin/lms"
        if os.path.isfile(shim):
            return shim
        return shutil.which("lms")

    @classmethod
    def _lm_studio_url(cls) -> str:
        from app.core.config import settings
        return (settings.vision_base_url or settings.ai_base_url or "http://host.docker.internal:1234").rstrip("/").rstrip("/v1")

    @classmethod
    def _http_call(
        cls, method: str, path: str, body: dict | None = None, timeout: float = 30.0
    ) -> tuple[bool, dict[str, Any]]:
        url = (cls._shim_url() or "").rstrip("/") + path
        try:
            import json as _json
            import urllib.request

            data = _json.dumps(body or {}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data if method != "GET" else None,
                method=method,
                headers={"Content-Type": "application/json"} if method != "GET" else {},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = _json.loads(resp.read().decode("utf-8") or "{}")
                return (resp.status == 200, payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("HTTP shim %s %s failed: %s", method, path, exc)
            return (False, {"ok": False, "error": str(exc)})

    @classmethod
    def _lm_studio_call(
        cls, verb: str, model: str, timeout: float = 180.0
    ) -> tuple[bool, dict[str, Any]]:
        """Call LM Studio API directly to load/unload models."""
        try:
            import json as _json
            import urllib.request

            base = cls._lm_studio_url()
            if verb == "load":
                url = f"{base}/v1/models/{model}/load"
            elif verb == "unload":
                url = f"{base}/v1/models/{model}/unload"
            elif verb == "status":
                url = f"{base}/v1/models"
            else:
                return False, {"ok": False, "error": f"unknown verb: {verb}"}

            req = urllib.request.Request(url, method="POST" if verb != "status" else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = _json.loads(resp.read().decode("utf-8") or "{}")
                return (resp.status == 200, payload)
        except Exception as exc:
            logger.debug("LM Studio API %s %s failed: %s", verb, model, exc)
            return False, {"ok": False, "error": str(exc)}

    @classmethod
    def _lms_call(
        cls, verb: str, model: str, timeout: float = 180.0
    ) -> tuple[bool, dict[str, Any]]:
        """Try LM Studio API directly, then HTTP shim, then lms subprocess."""
        # 1. Direct LM Studio API (most reliable)
        ok, payload = cls._lm_studio_call(verb, model, timeout=timeout)
        if ok:
            return True, payload
        # 2. HTTP shim (lms_server.py on host)
        ok, payload = cls._http_call("POST", f"/{verb}", {"model": model}, timeout=timeout)
        if ok:
            return True, payload
        # 3. Direct lms subprocess (fallback)
        lms = cls._find_lms()
        if not lms:
            return False, {"ok": False, "error": "no lms shim and no lms binary"}
        try:
            proc = subprocess.run(
                [lms, verb, model],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return (
                proc.returncode == 0,
                {
                    "ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                },
            )
        except subprocess.TimeoutExpired:
            return False, {"ok": False, "error": "timeout"}
        except Exception as exc:
            return False, {"ok": False, "error": str(exc)}

    @classmethod
    def is_loaded(cls, model: str | None = None) -> bool:
        """Return True if the vision model is currently loaded in LM Studio."""
        from app.core.config import settings

        model = model or settings.vision_model
        if not model:
            return False
        now = time.time()
        if cls._loaded_cache is not None and (now - cls._loaded_cache_ts) < cls._LOADED_CACHE_TTL:
            return cls._loaded_cache

        # Check LM Studio API directly
        try:
            import json as _json
            import urllib.request
            url = f"{cls._lm_studio_url()}/v1/models"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = _json.loads(resp.read().decode("utf-8"))
                loaded = any(
                    m.get("id") == model for m in payload.get("data", [])
                )
                cls._loaded_cache = loaded
                cls._loaded_cache_ts = now
                return loaded
        except Exception:
            pass

        # Fallback: HTTP shim
        ok, payload = cls._http_call("GET", "/status", timeout=10)
        if ok:
            loaded = any(
                m.get("id") == model and m.get("loaded") for m in payload.get("models", [])
            )
            cls._loaded_cache = loaded
            cls._loaded_cache_ts = now
            return loaded

        return False

    @classmethod
    def ensure_loaded(cls, model: str | None = None) -> bool:
        """Idempotently load the vision model. Returns True on success."""
        from app.core.config import settings

        if not cls.is_configured():
            return False
        model = model or settings.vision_model
        with cls._ops_lock:
            if cls.is_loaded(model):
                return True
            logger.info("VisionManager: loading %s", model)
            ok, payload = cls._lms_call("load", model, timeout=180)
            cls._loaded_cache = None
            if not ok:
                logger.warning(
                    "VisionManager: load failed: %s",
                    (payload or {}).get("error") or (payload or {}).get("stderr", "")[:300],
                )
                return False
            logger.info("VisionManager: loaded %s", model)
            # Give LM Studio a moment to publish the loaded model.
            time.sleep(2)
            cls._loaded_cache = True
            cls._loaded_cache_ts = time.time()
            cls._last_action_ts = cls._loaded_cache_ts
            return True

    @classmethod
    def schedule_unload(cls, delay: int | None = None) -> None:
        """Schedule a delayed unload. Multiple calls reset the timer.

        ``delay`` seconds after the last call, the vision model is
        unloaded. Set ``VISION_UNLOAD_DELAY_SECONDS=0`` to unload
        immediately after each call.
        """
        from app.core.config import settings

        if not cls.is_configured():
            return
        delay = delay if delay is not None else settings.vision_unload_delay_seconds

        def _fire() -> None:
            from app.core.config import settings

            model = settings.vision_model
            if not model:
                return
            with cls._ops_lock:
                if not cls.is_loaded(model):
                    return
                logger.info("VisionManager: unloading %s (idle)", model)
                ok, payload = cls._lms_call("unload", model, timeout=30)
                cls._loaded_cache = None
                if not ok:
                    logger.warning(
                        "VisionManager: unload failed: %s",
                        (payload or {}).get("error") or (payload or {}).get("stderr", "")[:200],
                    )

        with cls._ops_lock:
            if cls._unload_timer is not None:
                cls._unload_timer.cancel()
            if delay <= 0:
                threading.Thread(target=_fire, daemon=True).start()
                return
            cls._unload_timer = threading.Timer(delay, _fire)
            cls._unload_timer.daemon = True
            cls._unload_timer.start()
            cls._last_action_ts = time.time()
            logger.debug("VisionManager: unload scheduled in %ss (debounced)", delay)

    @classmethod
    def cancel_pending_unload(cls) -> None:
        """Cancel any pending unload. Used by ``ensure_loaded`` to keep
        the model resident while work is in flight."""
        with cls._ops_lock:
            if cls._unload_timer is not None:
                cls._unload_timer.cancel()
                cls._unload_timer = None
