from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

EXECUTABLE_SIGNATURES = {
    b"MZ": "windows_executable",
    b"\x7fELF": "linux_executable",
    b"\xca\xfe\xba\xbe": "mach_o_universal",
    b"\xcf\xfa\xed\xfe": "mach_o_executable",
    b"\xfe\xed\xfa\xcf": "mach_o_executable",
    b"#!": "script_executable",
}

# Office formats that are blocked at ingestion. We deliberately
# **do not** include ``.doc`` or ``.docx`` here because the parser
# router has dedicated handlers for both (``parse_doc`` / ``parse_docx``)
# and the original goal of this block list was macro-enabled or
# otherwise risky Office formats. Keep the list aligned with the
# router in :mod:`app.parsers.router` — anything here must NOT have
# a parser, and anything with a parser must NOT be here.
BLOCKED_OFFICE_EXTENSIONS = {
    ".docm",
    ".xlsb",
    ".pptm",
    ".accdb",
    ".mdb",
    ".odt",
    ".ods",
    ".odp",
}

MAGIC_SIGNATURES = {
    ".pdf": [(b"%PDF", "invalid_pdf_signature")],
    ".png": [(b"\x89PNG\r\n\x1a\n", "invalid_png_signature")],
    ".jpg": [(b"\xff\xd8\xff", "invalid_jpeg_signature")],
    ".jpeg": [(b"\xff\xd8\xff", "invalid_jpeg_signature")],
    ".tif": [(b"II*\x00", "invalid_tiff_signature"), (b"MM\x00*", "invalid_tiff_signature")],
    ".tiff": [(b"II*\x00", "invalid_tiff_signature"), (b"MM\x00*", "invalid_tiff_signature")],
    ".bmp": [(b"BM", "invalid_bmp_signature")],
    ".webp": [(b"RIFF", "invalid_webp_signature")],
    ".xlsx": [(b"PK\x03\x04", "invalid_xlsx_signature"), (b"PK\x05\x06", "invalid_xlsx_signature")],
    ".xlsm": [(b"PK\x03\x04", "invalid_xlsm_signature"), (b"PK\x05\x06", "invalid_xlsm_signature")],
    ".xls": [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "invalid_xls_signature")],
    ".doc": [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "invalid_doc_signature")],
    ".docx": [(b"PK\x03\x04", "invalid_docx_signature"), (b"PK\x05\x06", "invalid_docx_signature")],
    ".msg": [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "invalid_msg_signature")],
    # Every supported DWG release starts with an AC10xx version marker.
    ".dwg": [(b"AC10", "invalid_dwg_signature")],
}


@dataclass(frozen=True)
class FileSecurityResult:
    allowed: bool
    quarantined: bool
    reason: str | None = None


def inspect_file_for_ingestion(path: Path) -> FileSecurityResult:
    suffix = path.suffix.lower()
    if suffix in BLOCKED_OFFICE_EXTENSIONS:
        return FileSecurityResult(allowed=False, quarantined=True, reason="office_document_blocked")

    allowed_extensions = {item.lower() for item in settings.allowed_file_extensions}
    if allowed_extensions and suffix not in allowed_extensions:
        return FileSecurityResult(allowed=False, quarantined=True, reason="extension_not_allowed")

    try:
        with path.open("rb") as handle:
            header = handle.read(16)
    except OSError as exc:
        return FileSecurityResult(allowed=False, quarantined=True, reason=f"file_unreadable:{exc}")

    for signature, reason in EXECUTABLE_SIGNATURES.items():
        if header.startswith(signature):
            return FileSecurityResult(allowed=False, quarantined=True, reason=reason)

    expected_signatures = MAGIC_SIGNATURES.get(suffix)
    if expected_signatures and not any(
        header.startswith(signature) for signature, _ in expected_signatures
    ):
        return FileSecurityResult(allowed=False, quarantined=True, reason=expected_signatures[0][1])

    if suffix == ".webp" and len(header) >= 12 and header[8:12] != b"WEBP":
        return FileSecurityResult(allowed=False, quarantined=True, reason="invalid_webp_signature")

    # F6-02: inspect ZIP-based Office files for embedded VBA macros
    if suffix in {".docx", ".xlsx", ".pptx"}:
        macro_reason = _check_zip_for_macros(path)
        if macro_reason:
            return FileSecurityResult(allowed=False, quarantined=True, reason=macro_reason)

    return FileSecurityResult(allowed=True, quarantined=False)


# F6-02: VBA macro indicators inside ZIP-based Office files
_MACRO_INDICATORS = {
    "vbaProject.bin",
    "vbaData.xml",
    "macroDebug.xml",
}


def _check_zip_for_macros(path: Path) -> str | None:
    """Inspect a ZIP-based Office file for embedded VBA macros.

    Returns a reason string if macros are found, None if clean.
    """
    import zipfile

    try:
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                basename = name.rsplit("/", 1)[-1].lower()
                if basename in _MACRO_INDICATORS:
                    return "office_macro_detected"
                # Also check for ActiveX controls
                if basename.startswith("active") and basename.endswith(".xml"):
                    return "officeactivex_detected"
    except (zipfile.BadZipFile, OSError):
        pass  # Not a valid ZIP — let other checks handle it
    return None
