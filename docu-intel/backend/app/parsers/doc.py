"""Parser for legacy .doc (OLE2) files.

Converts .doc → .docx using LibreOffice headless, then delegates to the
.docx parser. Requires `libreoffice` on the system PATH.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.parsers.docx import parse_docx
from app.parsers.types import ExtractedDocument

logger = logging.getLogger("app.parsers.doc")

LIBREOFFICE_TIMEOUT = 60  # seconds


def _find_libreoffice() -> str | None:
    """Locate libreoffice binary on the system."""
    path = shutil.which("libreoffice")
    if path:
        return path
    # Common alternative names / paths
    for candidate in ("soffice", "/usr/bin/libreoffice", "/usr/bin/soffice"):
        if shutil.which(candidate) or Path(candidate).exists():
            return candidate
    return None


def parse_doc(path: Path) -> ExtractedDocument:
    """Convert .doc to .docx via LibreOffice, then parse the result.

    Args:
        path: Path to the .doc file.

    Returns:
        ExtractedDocument with the parsed text.

    Raises:
        RuntimeError: If LibreOffice is not installed or conversion fails.
    """
    libreoffice = _find_libreoffice()
    if libreoffice is None:
        raise RuntimeError(
            "LibreOffice is required to process .doc files. "
            "Install it with: apt-get install -y libreoffice-core"
        )

    with tempfile.TemporaryDirectory(prefix="docuintel_doc_") as tmpdir:
        output_dir = Path(tmpdir)
        source_copy = output_dir / path.name
        shutil.copy2(path, source_copy)

        try:
            result = subprocess.run(
                [
                    libreoffice,
                    "--headless",
                    "--norestore",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    str(output_dir),
                    str(source_copy),
                ],
                capture_output=True,
                text=True,
                timeout=LIBREOFFICE_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"LibreOffice timed out converting .doc file: {path.name}") from None

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            logger.warning(
                "LibreOffice conversion returned %d for %s: %s",
                result.returncode,
                path.name,
                stderr[:500],
            )

        # Find the generated .docx
        docx_files = list(output_dir.glob("*.docx"))
        if not docx_files:
            raise RuntimeError(
                f"LibreOffice did not produce a .docx for {path.name}. "
                f"stderr: {result.stderr.strip()[:300]}"
            )

        return parse_docx(docx_files[0])
