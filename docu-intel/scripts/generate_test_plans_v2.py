"""
Genera segundo plano de prueba: Sección constructiva.
Plano diferente al primero para validar variedad de tipos.
"""

import json
from pathlib import Path


def generate_dxf(output_path: Path):
    """Genera DXF con sección constructiva."""
    import ezdxf
    from ezdxf import units

    doc = ezdxf.new("R2010")
    doc.units = units.M
    msp = doc.modelspace()

    # Capas
    doc.layers.add("STRUCTURA", color=7)
    doc.layers.add("COTAS", color=1)
    doc.layers.add("TEXTO", color=3)
    doc.layers.add("HATCH", color=8)
    doc.layers.add("CAJETIN", color=7)

    # Muros de sección (perfiles verticales)
    # Muro exterior izquierdo
    msp.add_lwpolyline(
        [(0, 0), (0.3, 0), (0.3, 3.0), (0, 3.0), (0, 0)],
        dxfattribs={"layer": "STRUCTURA"},
    )
    # Muro exterior derecho
    msp.add_lwpolyline(
        [(5.7, 0), (6.0, 0), (6.0, 3.0), (5.7, 3.0), (5.7, 0)],
        dxfattribs={"layer": "STRUCTURA"},
    )
    # Forjado
    msp.add_lwpolyline(
        [(0, 2.7), (6.0, 2.7), (6.0, 3.0), (0, 3.0), (0, 2.7)],
        dxfattribs={"layer": "STRUCTURA"},
    )
    # Cubierta
    msp.add_lwpolyline(
        [(0, 3.0), (3.0, 4.5), (6.0, 3.0)],
        dxfattribs={"layer": "STRUCTURA"},
    )

    # Textos descriptivos
    msp.add_text(
        "SECCIÓN A-A",
        dxfattribs={"layer": "TEXTO", "height": 0.25, "insert": (1.5, 4.8)},
    )
    msp.add_text(
        "Muro exterior 30cm",
        dxfattribs={"layer": "TEXTO", "height": 0.15, "insert": (0.5, 1.5)},
    )
    msp.add_text(
        "Forjado 30cm",
        dxfattribs={"layer": "TEXTO", "height": 0.15, "insert": (2.5, 2.85)},
    )
    msp.add_text(
        "Cubierta inclinada",
        dxfattribs={"layer": "TEXTO", "height": 0.15, "insert": (2.5, 3.8)},
    )
    msp.add_text(
        "Aislamiento térmico 5cm",
        dxfattribs={"layer": "TEXTO", "height": 0.12, "insert": (0.5, 2.0)},
    )
    msp.add_text(
        "Tabique interior 10cm",
        dxfattribs={"layer": "TEXTO", "height": 0.12, "insert": (3.0, 1.5)},
    )

    # Cotas
    msp.add_linear_dim(
        base=(0, -0.5),
        p1=(0, 0),
        p2=(6.0, 0),
        dimstyle="EZDXF",
        override={"dimtxt": 0.2},
    )
    msp.add_linear_dim(
        base=(-0.5, 0),
        p1=(0, 0),
        p2=(0, 3.0),
        dimstyle="EZDXF",
        override={"dimtxt": 0.2},
    )

    # Cajetín
    caj_x, caj_y = -1.0, -2.0
    msp.add_lwpolyline(
        [(caj_x, caj_y), (caj_x + 5, caj_y), (caj_x + 5, caj_y + 1.5), (caj_x, caj_y + 1.5), (caj_x, caj_y)],
        dxfattribs={"layer": "CAJETIN"},
    )
    msp.add_text(
        "SECCIÓN CONSTRUCTIVA - Rev A",
        dxfattribs={"layer": "CAJETIN", "height": 0.2, "insert": (caj_x + 0.2, caj_y + 1.1)},
    )
    msp.add_text(
        "Hoja: A-02  Escala: 1:20",
        dxfattribs={"layer": "CAJETIN", "height": 0.15, "insert": (caj_x + 0.2, caj_y + 0.5)},
    )

    doc.saveas(str(output_path))
    print(f"DXF generado: {output_path}")


def generate_pdf(output_path: Path):
    """Genera PDF con sección constructiva."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import black, red, blue

    w_page, h_page = A4
    c = canvas.Canvas(str(output_path), pagesize=A4)

    # Escala 1:20 → 1m = 50mm
    sf = 50
    ox, oy = 30 * mm, 100 * mm

    def to_pdf(x_m, y_m):
        return (ox + x_m * sf, oy + y_m * sf)

    # Título
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h_page - 20 * mm, "SECCIÓN CONSTRUCTIVA A-A")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h_page - 28 * mm, "Hoja A-02 - Rev A - Escala 1:20")

    # Muros
    c.setStrokeColor(black)
    c.setLineWidth(1.5)
    # Muro izquierdo
    x, y = to_pdf(0, 0)
    c.rect(x, y, 0.3 * sf, 3.0 * sf)
    # Muro derecho
    x, y = to_pdf(5.7, 0)
    c.rect(x, y, 0.3 * sf, 3.0 * sf)
    # Forjado
    x, y = to_pdf(0, 2.7)
    c.rect(x, y, 6.0 * sf, 0.3 * sf)
    # Cubierta
    c.line(*to_pdf(0, 3.0), *to_pdf(3.0, 4.5))
    c.line(*to_pdf(3.0, 4.5), *to_pdf(6.0, 3.0))

    # Textos
    c.setFillColor(blue)
    c.setFont("Helvetica", 7)
    c.drawString(*to_pdf(0.5, 1.5), "Muro exterior 30cm")
    c.drawString(*to_pdf(2.5, 2.85), "Forjado 30cm")
    c.drawString(*to_pdf(2.5, 3.8), "Cubierta inclinada")
    c.drawString(*to_pdf(0.5, 2.0), "Aislamiento térmico 5cm")
    c.drawString(*to_pdf(3.0, 1.5), "Tabique interior 10cm")

    # Cotas
    c.setFillColor(red)
    c.setFont("Helvetica", 6)
    # Horizontal
    x1, y1 = to_pdf(0, -0.3)
    x2, y2 = to_pdf(6.0, -0.3)
    c.setStrokeColor(red)
    c.setLineWidth(0.5)
    c.line(x1, y1, x2, y2)
    c.drawCentredString((x1 + x2) / 2, y1 + 3, "6,00 m")
    # Vertical
    x1, y1 = to_pdf(-0.3, 0)
    x2, y2 = to_pdf(-0.3, 3.0)
    c.line(x1, y1, x2, y2)
    c.drawCentredString(x1 - 3, (y1 + y2) / 2, "3,00 m")

    # Cajetín
    c.setStrokeColor(black)
    c.setLineWidth(1)
    cx, cy = to_pdf(-0.5, -2.5)
    c.rect(cx, cy, 100, 30)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(cx + 5, cy + 22, "SECCIÓN CONSTRUCTIVA - Rev A")
    c.setFont("Helvetica", 6)
    c.drawString(cx + 5, cy + 12, "Hoja: A-02  Escala: 1:20")

    c.save()
    print(f"PDF generado: {output_path}")


def generate_manifest(output_path: Path):
    """Genera fixture JSON con valores esperados."""
    manifest = {
        "document_type": "plano_estructura",
        "expected": {
            "scale": "1:20",
            "phase": "SECCIÓN A-A",
            "revision": "A",
            "sheet": "A-02",
            "materials": [
                {"name": "Muro exterior", "thickness_cm": 30},
                {"name": "Forjado", "thickness_cm": 30},
                {"name": "Aislamiento", "thickness_cm": 5},
                {"name": "Tabique interior", "thickness_cm": 10},
            ],
            "dimensions": [
                {"label": "6,00", "value_m": 6.0},
                {"label": "3,00", "value_m": 3.0},
            ],
        },
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Manifest generado: {output_path}")


if __name__ == "__main__":
    out_dir = Path(__file__).parent.parent / "data" / "input" / "planos"
    out_dir.mkdir(parents=True, exist_ok=True)

    generate_dxf(out_dir / "seccion_constructiva.dxf")
    generate_pdf(out_dir / "seccion_constructiva.pdf")
    generate_manifest(out_dir / "seccion_constructiva.manifest.json")

    print(f"\nArchivos generados en: {out_dir}")
