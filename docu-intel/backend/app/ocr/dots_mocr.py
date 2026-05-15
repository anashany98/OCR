from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DotsMOCRConfig:
    enabled: bool = False
    endpoint: str | None = None


class DotsMOCREngine:
    def __init__(self, config: DotsMOCRConfig) -> None:
        self.config = config

    def extract(self, *_args, **_kwargs):
        if not self.config.enabled:
            raise RuntimeError("dots.mocr integration is disabled")
        raise NotImplementedError("dots.mocr adapter is prepared but not enabled in Fase 1")
