"""Parser for Outlook ``.msg`` email files.

Uses the ``extract-msg`` package (the de-facto Python reader for the
Outlook .msg format). Returns an :class:`ExtractedDocument` whose single
page carries a header line (``Subject / From / To / Date``) followed by
the plain-text body. Attachments are listed by name so the user can see
what was attached without opening the email in Outlook.

Some .msg files (especially forwarded threads with quoted history) carry
the raw MAPI property stream in ``msg.body`` instead of a clean text body.
We sanitize aggressively and fall back to a short note when the result
still looks like raw MAPI/Outlook content.

HTML email bodies are converted to markdown so any tables the sender
included (presupuestos, cotizaciones, listados) are preserved as proper
tables instead of being flattened into a single column of text.

No image_path is produced (Outlook .msg has no per-page rendering); the
detail-page viewer falls back to the on-demand thumbnail generator
(``app.services.thumbnail.generate_msg_thumbnail``) which paints a
compact email-style preview.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from pathlib import Path

from app.ocr.base import BaseOCREngine
from app.parsers.embedded_images import EmbeddedImage, extract_embedded_image_pages
from app.parsers.types import ExtractedBlock, ExtractedDocument, ExtractedPage

logger = logging.getLogger(__name__)

# Hard cap on the body we surface into the OCR panel. Forwarded threads can
# easily be a few MB; the panel is not the place to dump the whole thing.
_MAX_BODY_CHARS = 20_000

# Signals that ``msg.body`` returned raw MAPI property bytes rather than
# the rendered text body. When any of these appear we treat the body as
# unparseable and surface a short note instead.
_MAPI_TOKENS = (
    "__substg1.0_",
    "__nameid_version",
    "IPM.Note",
    "Root Entry",
    "ExchangeLabs",
    "EXCHANGELABS",
)


def _clean_body(raw: str | None) -> str:
    if not raw:
        return ""
    # Strip NUL and most control bytes, but keep tabs / newlines.
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
    # Collapse runs of whitespace that aren't real newlines.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _looks_like_mapi_blob(text: str) -> bool:
    if not text:
        return False
    head = text[:2000]
    return any(tok in head for tok in _MAPI_TOKENS)


# ---------------------------------------------------------------------------
# HTML -> markdown for email bodies. The goal is NOT a general-purpose HTML
# renderer; it only needs to preserve <table>, <tr>, <td>/<th>, <p>, <br>,
# <b>/<strong>, <i>/<em>, and inline text. Anything more exotic falls back
# to plain text.
# ---------------------------------------------------------------------------


class _HTMLToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell_text: list[str] = []
        self.row_cells: list[str] = []
        self.table_rows: list[list[str]] = []
        self.header_row: list[str] | None = None
        self.list_stack: list[str] = []
        self.skip_depth = 0  # skip <script>, <style>, etc.

    # --- helpers ----------------------------------------------------------
    def _flush_cell(self) -> None:
        text = "".join(self.cell_text).strip()
        text = re.sub(r"\s+", " ", text)
        self.cell_text = []
        self.row_cells.append(text)

    def _flush_row(self) -> None:
        if self.row_cells:
            self.table_rows.append(self.row_cells)
        self.row_cells = []

    def _flush_table(self) -> None:
        if not self.table_rows:
            return
        # The first row with at least 2 non-empty cells becomes the header.
        header: list[str] | None = None
        body: list[list[str]] = []
        for r in self.table_rows:
            if header is None and sum(1 for c in r if c) >= 2:
                header = r
            else:
                body.append(r)
        if header is None and self.table_rows:
            header = self.table_rows[0]
            body = self.table_rows[1:]
        # Normalise column count.
        ncols = max(len(header or []), *(len(r) for r in body)) if (header or body) else 0
        if ncols == 0:
            self.table_rows = []
            return
        if header is None:
            header = [f"col{i + 1}" for i in range(ncols)]
        else:
            header = list(header) + [""] * (ncols - len(header))
        # Pad body rows.
        body = [list(r) + [""] * (ncols - len(r)) for r in body]

        def esc(cell: str) -> str:
            return (cell or "").replace("|", "\\|").replace("\n", " ").strip() or " "

        md_lines = [
            "| " + " | ".join(esc(c) for c in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for r in body:
            md_lines.append("| " + " | ".join(esc(c) for c in r) + " |")
        self.parts.append("\n".join(md_lines))
        self.parts.append("\n\n")
        self.table_rows = []
        self.header_row = None

    # --- tag handlers -----------------------------------------------------
    def handle_starttag(self, tag: str, attrs):  # type: ignore[override]
        t = tag.lower()
        if t in ("script", "style"):
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if t == "table":
            self.in_table = True
            self.parts.append("\n\n")
        elif t == "tr":
            self.in_row = True
        elif t in ("td", "th"):
            self.in_cell = True
            self.cell_text = []
        elif t in ("p", "div"):
            self.parts.append("\n\n")
        elif t == "br":
            self.parts.append("\n")
        elif t in ("b", "strong"):
            self.parts.append("**")
        elif t in ("i", "em"):
            self.parts.append("*")
        elif t == "li":
            self.parts.append("\n- ")

    def handle_endtag(self, tag: str):  # type: ignore[override]
        t = tag.lower()
        if t in ("script", "style"):
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if t == "table":
            if self.in_table:
                self._flush_row()
                self._flush_table()
            self.in_table = False
        elif t == "tr":
            if self.in_row:
                self._flush_cell()
                self._flush_row()
            self.in_row = False
        elif t in ("td", "th"):
            if self.in_cell:
                self._flush_cell()
            self.in_cell = False
        elif t in ("b", "strong"):
            self.parts.append("**")
        elif t in ("i", "em"):
            self.parts.append("*")
        elif t in ("p", "div", "ul", "ol"):
            self.parts.append("\n\n")

    def handle_data(self, data: str):
        if self.skip_depth:
            return
        if self.in_cell:
            self.cell_text.append(data)
        else:
            self.parts.append(data)

    def close(self) -> str:  # type: ignore[override]
        if self.in_table:
            self._flush_row()
            self._flush_table()
        text = "".join(self.parts)
        # Collapse blank lines.
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_markdown(html: str) -> str:
    parser = _HTMLToMarkdown()
    try:
        parser.feed(html)
    except Exception:
        logger.debug("html_to_markdown_parse_failed, falling back to regex", exc_info=True)
        return re.sub(r"<[^>]+>", " ", html)
    return parser.close()


def _extract_html_tables_markdown(html: str) -> str:
    """Pull <table>...</table> blocks from the HTML body and serialise
    them as markdown tables. Other HTML is dropped (the plain text body
    is already extracted by extract-msg)."""
    if not html:
        return ""
    parser = _HTMLToMarkdown()
    try:
        parser.feed(html)
    except Exception:
        logger.debug("html_tables_extract_failed", exc_info=True)
        return ""
    return parser.close()


def _image_attachment(att) -> EmbeddedImage | None:
    name = (
        getattr(att, "longFilename", None)
        or getattr(att, "shortFilename", None)
        or "(adjunto sin nombre)"
    )
    content = getattr(att, "data", None)
    return EmbeddedImage(name, content) if isinstance(content, bytes) else None


def parse_msg(
    path: Path,
    output_dir: Path | None = None,
    ocr_engine: BaseOCREngine | None = None,
) -> ExtractedDocument:
    import extract_msg

    msg = extract_msg.Message(str(path))
    try:
        subject = (msg.subject or "").strip() or "(sin asunto)"
        sender = (msg.sender or "").strip() or "(remitente desconocido)"
        to = (msg.to or "").strip() or "(sin destinatario)"
        cc = (msg.cc or "").strip()
        date = msg.date
        date_str = date.strftime("%Y-%m-%d %H:%M") if date is not None else "(sin fecha)"

        body_clean = _clean_body(msg.body)
        html_body = getattr(msg, "htmlBody", None) or getattr(msg, "html_body", None)

        if _looks_like_mapi_blob(body_clean):
            # ``msg.body`` came back as raw MAPI/Outlook property bytes
            # (common with forwarded threads and certain Exchange exports).
            # Try the HTML body as a fallback; otherwise surface a note.
            if html_body:
                try:
                    from bs4 import BeautifulSoup

                    body_clean = _clean_body(BeautifulSoup(html_body, "html.parser").get_text("\n"))
                except Exception:
                    logger.debug(
                        "beautifulsoup_parse_failed, falling back to html_to_markdown",
                        exc_info=True,
                    )
                    body_clean = _html_to_markdown(html_body) or body_clean
            if _looks_like_mapi_blob(body_clean):
                body_clean = (
                    "(No se ha podido extraer el cuerpo del email. "
                    "El archivo .msg contiene el flujo MAPI interno en lugar "
                    "de un cuerpo de texto. Usa el botón Descargar para abrirlo en Outlook.)"
                )

        # Pull HTML tables (if any) so the LLM can see them as proper tables
        # instead of flattened text.
        html_tables_md = _extract_html_tables_markdown(html_body) if html_body else ""
        if (
            html_tables_md
            and html_tables_md.strip()
            and html_tables_md.strip() != body_clean.strip()
        ):
            body_clean = f"{body_clean}\n\n--- Tablas del email ---\n\n{html_tables_md}"

        # Truncate to keep the OCR panel usable.
        if len(body_clean) > _MAX_BODY_CHARS:
            body_clean = (
                body_clean[:_MAX_BODY_CHARS]
                + "\n\n[… cuerpo truncado, ver .msg original para el texto completo]"
            )

        attachment_names: list[str] = []
        image_attachments: list[EmbeddedImage] = []
        try:
            for att in msg.attachments or []:
                name = (
                    getattr(att, "longFilename", None)
                    or getattr(att, "shortFilename", None)
                    or "(adjunto sin nombre)"
                )
                attachment_names.append(name)
                image = _image_attachment(att)
                if image is not None:
                    image_attachments.append(image)
        except Exception:
            logger.debug("attachment_list_failed", exc_info=True)
    finally:
        close = getattr(msg, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.debug("msg_close_failed", exc_info=True)

    header_lines = [
        f"Asunto: {subject}",
        f"De: {sender}",
        f"Para: {to}",
    ]
    if cc:
        header_lines.append(f"CC: {cc}")
    header_lines.append(f"Fecha: {date_str}")
    if attachment_names:
        header_lines.append(f"Adjuntos ({len(attachment_names)}): " + ", ".join(attachment_names))

    text = "\n".join(header_lines) + "\n\n" + body_clean

    pages = [
        ExtractedPage(
            page_number=1,
            text=text,
            ocr_content_kind="native_text",
            blocks=[
                ExtractedBlock(
                    block_type="text",
                    text=text,
                    page_number=1,
                    confidence=1.0,
                    source_engine="extract-msg",
                )
            ],
        )
    ]
    pages.extend(
        extract_embedded_image_pages(
            image_attachments,
            output_dir=output_dir,
            ocr_engine=ocr_engine,
            first_page_number=len(pages) + 1,
        )
    )
    return ExtractedDocument(pages=pages)
