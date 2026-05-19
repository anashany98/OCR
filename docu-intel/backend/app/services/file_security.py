from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


EXECUTABLE_SIGNATURES = {
    b"MZ": "windows_executable",
    b"\x7fELF": "linux_executable",
    b"\xca\xfe\xba\xbe": "mach_o_universal",
}


@dataclass(frozen=True)
class FileSecurityResult:
    allowed: bool
    quarantined: bool
    reason: str | None = None


def inspect_file_for_ingestion(path: Path) -> FileSecurityResult:
    suffix = path.suffix.lower()
    allowed_extensions = {item.lower() for item in settings.allowed_file_extensions}
    if allowed_extensions and suffix not in allowed_extensions:
        return FileSecurityResult(allowed=False, quarantined=True, reason="extension_not_allowed")

    try:
        with path.open("rb") as handle:
            header = handle.read(8)
    except OSError as exc:
        return FileSecurityResult(allowed=False, quarantined=True, reason=f"file_unreadable:{exc}")

    for signature, reason in EXECUTABLE_SIGNATURES.items():
        if header.startswith(signature):
            return FileSecurityResult(allowed=False, quarantined=True, reason=reason)

    return FileSecurityResult(allowed=True, quarantined=False)
