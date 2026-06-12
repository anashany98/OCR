from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings

THUMBNAIL_SIZE = (200, 280)
THUMBNAIL_DIR = settings.files_dir / "thumbnails"


def ensure_thumbnail_dir() -> Path:
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    return THUMBNAIL_DIR


def _font(size: int) -> ImageFont.ImageFont:
    """Best-effort system font loader. Falls back to PIL's default bitmap font
    when no TrueType font is available (small Alpine image, no DejaVu, etc.)."""
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> list[str]:
    """Greedy word-wrap that respects ``max_width`` pixels at the given font."""
    if not text:
        return [""]
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def _save(img: Image.Image, thumb_path: Path) -> Path:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
    img.save(thumb_path, "JPEG", quality=85)
    return thumb_path


def generate_pdf_thumbnail(pdf_path: Path, document_hash: str) -> Path | None:
    try:
        import pymupdf

        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"

        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)

        doc = pymupdf.open(str(pdf_path))
        if doc.page_count == 0:
            return None

        page = doc[0]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
        img_data = pix.tobytes("jpg")

        img = Image.open(io.BytesIO(img_data))
        _save(img, thumb_path)
        doc.close()
        return thumb_path.relative_to(settings.files_dir)
    except Exception:
        return None


def generate_image_thumbnail(image_path: Path, document_hash: str) -> Path | None:
    try:
        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"

        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)

        img = Image.open(str(image_path))
        _save(img, thumb_path)
        return thumb_path.relative_to(settings.files_dir)
    except Exception:
        return None


def generate_excel_thumbnail(xlsx_path: Path, document_hash: str) -> Path | None:
    """Render the first sheet of an Excel workbook as a small grid preview.

    Shows up to ``MAX_ROWS`` rows × ``MAX_COLS`` columns of the active sheet,
    truncated to fit ``THUMBNAIL_SIZE``. The cell text is shortened to
    ``MAX_CELL_CHARS`` and the sheet name is printed as a header banner.
    """
    try:
        import openpyxl

        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"
        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)

        wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
        try:
            sheet = wb.active
            if sheet is None:
                return None
            sheet_name = sheet.title
            rows_iter = sheet.iter_rows(min_row=1, max_row=20, max_col=8, values_only=True)
            rows: list[tuple[str, ...]] = []
            for r in rows_iter:
                rendered = tuple(("" if v is None else str(v))[:24] for v in r)
                rows.append(rendered)
        finally:
            wb.close()

        if not rows:
            return None

        W, H = THUMBNAIL_SIZE
        # Render at 2x and downscale for crisper text in the saved JPEG.
        scale = 2
        canvas = Image.new("RGB", (W * scale, H * scale), "white")
        draw = ImageDraw.Draw(canvas)

        header_font = _font(int(11 * scale))
        cell_font = _font(int(9 * scale))

        # Sheet name banner
        draw.rectangle((0, 0, W * scale, int(18 * scale)), fill="#1f3a5f")
        draw.text(
            (int(6 * scale), int(2 * scale)),
            f"Excel: {sheet_name[:26]}",
            fill="white",
            font=header_font,
        )

        # Column headers (A, B, C, ...)
        col_header_y = int(22 * scale)
        col_w = (W - 30) * scale // max(len(rows[0]), 1)
        row_num_w = int(28 * scale)
        for i in range(len(rows[0])):
            x = row_num_w + i * col_w
            draw.rectangle(
                (x, col_header_y, x + col_w, col_header_y + int(12 * scale)),
                fill="#e2e8f0",
                outline="#cbd5e1",
            )
            letter = chr(ord("A") + i) if i < 26 else f"C{i + 1}"
            draw.text(
                (x + int(2 * scale), col_header_y + int(1 * scale)),
                letter,
                fill="#475569",
                font=cell_font,
            )

        # Cells
        row_h = int(11 * scale)
        for r_idx, row in enumerate(rows):
            y = col_header_y + int(12 * scale) + r_idx * row_h
            if y + row_h > H * scale:
                break
            # Row number
            draw.rectangle((0, y, row_num_w, y + row_h), fill="#f1f5f9", outline="#cbd5e1")
            draw.text(
                (int(2 * scale), y + int(1 * scale)), str(r_idx + 1), fill="#64748b", font=cell_font
            )
            for c_idx, value in enumerate(row):
                if c_idx >= len(rows[0]):
                    break
                x = row_num_w + c_idx * col_w
                draw.rectangle((x, y, x + col_w, y + row_h), outline="#e2e8f0", fill="white")
                # Truncate horizontally to col_w - 4px
                text = value if len(value) <= 18 else value[:17] + "…"
                draw.text(
                    (x + int(2 * scale), y + int(1 * scale)), text, fill="#1e293b", font=cell_font
                )

        _save(canvas, thumb_path)
        return thumb_path.relative_to(settings.files_dir)
    except Exception:
        return None


def generate_msg_thumbnail(msg_path: Path, document_hash: str) -> Path | None:
    """Render a compact email-style preview (subject, from, date, body excerpt)."""
    try:
        import extract_msg

        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"
        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)

        msg = extract_msg.Message(str(msg_path))
        try:
            subject = (msg.subject or "").strip() or "(sin asunto)"
            sender = (msg.sender or "").strip() or "(remitente desconocido)"
            date = msg.date
            date_str = date.strftime("%Y-%m-%d %H:%M") if date is not None else ""
            body = (msg.body or "").strip()
        finally:
            close = getattr(msg, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        W, H = THUMBNAIL_SIZE
        scale = 2
        canvas = Image.new("RGB", (W * scale, H * scale), "white")
        draw = ImageDraw.Draw(canvas)

        subject_font = _font(int(13 * scale))
        field_font = _font(int(10 * scale))
        body_font = _font(int(9 * scale))

        # Header strip
        draw.rectangle((0, 0, W * scale, int(22 * scale)), fill="#1f3a5f")
        draw.text((int(6 * scale), int(3 * scale)), "Email (.msg)", fill="white", font=field_font)

        y = int(28 * scale)
        # Subject (bold-ish, larger)
        for line in _wrap_text(draw, subject, subject_font, W * scale - int(12 * scale))[:2]:
            draw.text((int(6 * scale), y), line, fill="#0f172a", font=subject_font)
            y += int(16 * scale)

        y += int(2 * scale)
        # Divider
        draw.line((int(6 * scale), y, (W - 6) * scale, y), fill="#cbd5e1", width=1)
        y += int(4 * scale)

        # From
        for line in _wrap_text(draw, f"De: {sender}", field_font, W * scale - int(12 * scale))[:1]:
            draw.text((int(6 * scale), y), line, fill="#334155", font=field_font)
            y += int(12 * scale)
        # Date
        if date_str:
            draw.text((int(6 * scale), y), date_str, fill="#64748b", font=field_font)
            y += int(12 * scale)

        y += int(4 * scale)
        draw.line((int(6 * scale), y, (W - 6) * scale, y), fill="#e2e8f0", width=1)
        y += int(4 * scale)

        # Body excerpt
        body_excerpt = body[:600] if body else "(cuerpo vacío)"
        for line in _wrap_text(draw, body_excerpt, body_font, W * scale - int(12 * scale)):
            if y + int(11 * scale) > (H - 4) * scale:
                break
            draw.text((int(6 * scale), y), line, fill="#1e293b", font=body_font)
            y += int(11 * scale)

        _save(canvas, thumb_path)
        return thumb_path.relative_to(settings.files_dir)
    except Exception:
        return None


def get_thumbnail_path(document_hash: str) -> Path | None:
    thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"
    if thumb_path.exists():
        return thumb_path.relative_to(settings.files_dir)
    return None
