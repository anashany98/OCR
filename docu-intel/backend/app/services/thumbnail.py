from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings

THUMBNAIL_SIZE = (200, 280)
THUMBNAIL_DIR = settings.files_dir / "thumbnails"
PREVIEW_SIZE = (1400, 1000)
PREVIEW_DIR = settings.files_dir / "previews"


def ensure_thumbnail_dir() -> Path:
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    return THUMBNAIL_DIR


def ensure_preview_dir() -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    return PREVIEW_DIR


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


def _save_preview(img: Image.Image, preview_path: Path) -> Path:
    """Persist a full-size viewer image without downscaling it to a card."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(preview_path, "JPEG", quality=88)
    return preview_path


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


def generate_office_thumbnail(document_path: Path, document_hash: str) -> Path | None:
    """Render the first page of a Word/OpenDocument file without persisting a PDF.

    LibreOffice is already part of the backend image for document extraction.
    The conversion lives in a private temporary directory, uses no shell, and
    delegates final rasterisation to the same PDF thumbnail code used elsewhere.
    """
    if document_path.suffix.lower() not in {".doc", ".docx", ".odt", ".rtf"}:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="docu-intel-preview-") as output_dir:
            result = subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    output_dir,
                    str(document_path),
                ],
                check=False,
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None
            converted = Path(output_dir) / f"{document_path.stem}.pdf"
            if not converted.exists():
                return None
            return generate_pdf_thumbnail(converted, document_hash)
    except (OSError, subprocess.SubprocessError):
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
                with contextlib.suppress(Exception):
                    close()

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


def _eml_fields(eml_path: Path) -> tuple[str, str, str, str]:
    """Read a mail safely, preferring its text body over untrusted HTML."""
    with eml_path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    subject = str(message.get("subject") or "").strip() or "(sin asunto)"
    sender = str(message.get("from") or "").strip() or "(remitente desconocido)"
    date = str(message.get("date") or "").strip()
    body_part = message.get_body(preferencelist=("plain",))
    if body_part is not None:
        body = body_part.get_content()
    elif not message.is_multipart():
        body = message.get_content()
    else:
        body = ""
    return subject, sender, date, str(body).strip()


def _render_eml(eml_path: Path, output_path: Path, size: tuple[int, int]) -> bool:
    subject, sender, date, body = _eml_fields(eml_path)
    width, height = size
    canvas = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(canvas)
    subject_font = _font(32)
    field_font = _font(22)
    body_font = _font(20)

    draw.rectangle((0, 0, width, 70), fill="#1f3a5f")
    draw.text((28, 20), "Correo electronico (.eml)", fill="white", font=field_font)
    y = 105
    for line in _wrap_text(draw, subject, subject_font, width - 56)[:3]:
        draw.text((28, y), line, fill="#0f172a", font=subject_font)
        y += 42
    y += 12
    draw.line((28, y, width - 28, y), fill="#cbd5e1", width=2)
    y += 18
    for label, value in (("De", sender), ("Fecha", date)):
        if value:
            for line in _wrap_text(draw, f"{label}: {value}", field_font, width - 56)[:2]:
                draw.text((28, y), line, fill="#334155", font=field_font)
                y += 30
    y += 12
    draw.line((28, y, width - 28, y), fill="#e2e8f0", width=2)
    y += 22
    for line in _wrap_text(draw, body[:12000] or "(cuerpo vacio)", body_font, width - 56):
        if y + 28 > height - 24:
            draw.text((28, height - 42), "...", fill="#64748b", font=body_font)
            break
        draw.text((28, y), line, fill="#1e293b", font=body_font)
        y += 28
    _save_preview(canvas, output_path)
    return True


def generate_eml_thumbnail(eml_path: Path, document_hash: str) -> Path | None:
    """Create the small email card used by results and source citations."""
    try:
        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"
        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)
        return thumb_path.relative_to(settings.files_dir) if _render_eml(eml_path, thumb_path, THUMBNAIL_SIZE) else None
    except Exception:
        return None


def generate_eml_preview(eml_path: Path, document_hash: str) -> Path | None:
    """Create a readable email image for the document detail viewer."""
    try:
        ensure_preview_dir()
        preview_path = PREVIEW_DIR / f"{document_hash}.jpg"
        if preview_path.exists():
            return preview_path.relative_to(settings.files_dir)
        return preview_path.relative_to(settings.files_dir) if _render_eml(eml_path, preview_path, PREVIEW_SIZE) else None
    except Exception:
        return None


def _render_cad_dxf_to_image(dxf_path: Path, output_path: Path, size: tuple[int, int]) -> bool:
    """Render common DXF geometry with Pillow, without a GUI CAD dependency."""
    try:
        import ezdxf

        document = ezdxf.readfile(str(dxf_path))
        shapes: list[tuple[str, tuple, str]] = []
        bounds: list[tuple[float, float]] = []

        def point(value) -> tuple[float, float]:
            return float(value.x), float(value.y)

        def add_bounds(*points: tuple[float, float]) -> None:
            bounds.extend(points)

        for entity in document.modelspace():
            kind = entity.dxftype()
            layer = getattr(entity.dxf, "layer", "0")
            if kind == "LINE":
                start, end = point(entity.dxf.start), point(entity.dxf.end)
                shapes.append(("line", (start, end), layer))
                add_bounds(start, end)
            elif kind == "LWPOLYLINE":
                points = tuple((float(x), float(y)) for x, y, *_ in entity.get_points("xy"))
                if len(points) > 1:
                    shapes.append(("polyline", (points, bool(entity.closed)), layer))
                    add_bounds(*points)
            elif kind == "POLYLINE":
                points = tuple(point(vertex.dxf.location) for vertex in entity.vertices)
                if len(points) > 1:
                    shapes.append(("polyline", (points, bool(entity.is_closed)), layer))
                    add_bounds(*points)
            elif kind in {"CIRCLE", "ARC"}:
                center = point(entity.dxf.center)
                radius = float(entity.dxf.radius)
                shapes.append((kind.lower(), (center, radius, getattr(entity.dxf, "start_angle", 0.0), getattr(entity.dxf, "end_angle", 360.0)), layer))
                add_bounds((center[0] - radius, center[1] - radius), (center[0] + radius, center[1] + radius))
            elif kind in {"TEXT", "MTEXT", "INSERT"}:
                insert = getattr(entity.dxf, "insert", None)
                if insert is None:
                    continue
                location = point(insert)
                if kind == "TEXT":
                    text = str(entity.dxf.text).strip()
                elif kind == "MTEXT":
                    text = str(entity.plain_text()).strip()
                else:
                    text = f"[{getattr(entity.dxf, 'name', 'bloque')}]"
                if text:
                    shapes.append(("text", (location, text[:100]), layer))
                    add_bounds(location)

        if not bounds:
            return False
        min_x, max_x = min(x for x, _ in bounds), max(x for x, _ in bounds)
        min_y, max_y = min(y for _, y in bounds), max(y for _, y in bounds)
        span_x, span_y = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
        width, height = size
        margin = 50
        scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)

        def pixel(raw: tuple[float, float]) -> tuple[int, int]:
            return (int(margin + (raw[0] - min_x) * scale), int(height - margin - (raw[1] - min_y) * scale))

        canvas = Image.new("RGB", size, "#fafafa")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, width, 36), fill="#1f3a5f")
        draw.text((16, 9), f"Plano CAD: {dxf_path.name}", fill="white", font=_font(18))
        palette = ["#1d4ed8", "#059669", "#b45309", "#7c3aed", "#be123c", "#0f766e"]
        layers = {layer: palette[index % len(palette)] for index, layer in enumerate(sorted({layer for _, _, layer in shapes}))}
        for kind, data, layer in shapes:
            color = layers[layer]
            if kind == "line":
                draw.line((pixel(data[0]), pixel(data[1])), fill=color, width=2)
            elif kind == "polyline":
                points, closed = data
                rendered = [pixel(item) for item in points]
                if closed:
                    rendered.append(rendered[0])
                draw.line(rendered, fill=color, width=2)
            elif kind in {"circle", "arc"}:
                center, radius, start, end = data
                left_top = pixel((center[0] - radius, center[1] + radius))
                right_bottom = pixel((center[0] + radius, center[1] - radius))
                if kind == "circle":
                    draw.ellipse((left_top, right_bottom), outline=color, width=2)
                else:
                    draw.arc((left_top, right_bottom), start=-float(end), end=-float(start), fill=color, width=2)
            elif kind == "text":
                location, text = data
                draw.text(pixel(location), text, fill=color, font=_font(14))
        _save_preview(canvas, output_path)
        return True
    except Exception:
        return False


def _generate_cad_image(cad_path: Path, output_path: Path, size: tuple[int, int]) -> bool:
    suffix = cad_path.suffix.lower()
    try:
        if suffix == ".dxf":
            return _render_cad_dxf_to_image(cad_path, output_path, size)
        if suffix != ".dwg":
            return False
        from app.parsers.dwg import _convert_dwg_to_dxf

        with tempfile.TemporaryDirectory(prefix="docu-intel-dwg-preview-") as temporary_dir:
            converted = Path(temporary_dir) / f"{cad_path.stem}.dxf"
            _convert_dwg_to_dxf(cad_path, converted)
            return _render_cad_dxf_to_image(converted, output_path, size)
    except Exception:
        return False


def generate_cad_thumbnail(cad_path: Path, document_hash: str) -> Path | None:
    try:
        ensure_thumbnail_dir()
        thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"
        if thumb_path.exists():
            return thumb_path.relative_to(settings.files_dir)
        return thumb_path.relative_to(settings.files_dir) if _generate_cad_image(cad_path, thumb_path, THUMBNAIL_SIZE) else None
    except Exception:
        return None


def generate_cad_preview(cad_path: Path, document_hash: str) -> Path | None:
    try:
        ensure_preview_dir()
        preview_path = PREVIEW_DIR / f"{document_hash}.jpg"
        if preview_path.exists():
            return preview_path.relative_to(settings.files_dir)
        return preview_path.relative_to(settings.files_dir) if _generate_cad_image(cad_path, preview_path, PREVIEW_SIZE) else None
    except Exception:
        return None


def get_thumbnail_path(document_hash: str) -> Path | None:
    thumb_path = THUMBNAIL_DIR / f"{document_hash}.jpg"
    if thumb_path.exists():
        return thumb_path.relative_to(settings.files_dir)
    return None


def get_preview_path(document_hash: str) -> Path | None:
    preview_path = PREVIEW_DIR / f"{document_hash}.jpg"
    if preview_path.exists():
        return preview_path.relative_to(settings.files_dir)
    return None
