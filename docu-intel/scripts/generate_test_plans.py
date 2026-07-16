"""
Genera planos de prueba sintéticos (DXF + PDF) para validar el pipeline.
PM0.2 del brief: corpus con valores esperados conocidos.

Plano generado: Planta Baja vivienda unifamiliar
- Escala 1:100
- 4 habitaciones: Salón, Cocina, Dormitorio 1, Baño
- Cotas impresas
- Puertas y ventanas como bloques
- Cajetín con revisión
"""

import json
import math
from pathlib import Path

# --- Configuración del plano ---
SCALE = "1:100"
SCALE_RATIO = 100
REVISION = "B"
PHASE = "PLANTA BAJA"
SHEET = "A-01"
PROJECT = "VIVIENDA UNIFAMILIAR"
CLIENT = "CLIENTE EJEMPLO"

# Dimensiones en metros (reales)
ROOMS = {
    "Salón": {"x": 0, "y": 0, "w": 5.0, "l": 4.0},
    "Cocina": {"x": 5.0, "y": 0, "w": 3.0, "l": 4.0},
    "Dormitorio 1": {"x": 0, "y": 4.0, "w": 4.0, "l": 3.5},
    "Baño": {"x": 4.0, "y": 4.0, "w": 2.5, "l": 3.5},
}

# Puertas: (room, x_offset, y_offset, width, rotation_deg)
DOORS = [
    ("Salón", 2.0, 0, 0.90, 0),
    ("Cocina", 1.0, 0, 0.80, 0),
    ("Dormitorio 1", 1.5, 0, 0.90, 0),
    ("Baño", 0.5, 0, 0.70, 0),
]

# Ventanas: (room, x_offset, y_offset, width, rotation_deg)
WINDOWS = [
    ("Salón", 0, 1.5, 1.50, 90),
    ("Cocina", 0, 2.0, 1.20, 90),
    ("Dormitorio 1", 0, 1.5, 1.50, 90),
    ("Baño", 2.5, 1.0, 0.60, 0),
]

# Cotas impresas
DIMENSIONS = [
    {"label": "5,00", "value_m": 5.0, "x1": 0, "y1": -1.0, "x2": 5.0, "y2": -1.0, "room": "Salón"},
    {"label": "3,00", "value_m": 3.0, "x1": 5.0, "y1": -1.0, "x2": 8.0, "y2": -1.0, "room": "Cocina"},
    {"label": "4,00", "value_m": 4.0, "x1": -1.0, "y1": 0, "x2": -1.0, "y2": 4.0, "room": "Salón"},
    {"label": "3,50", "value_m": 3.5, "x1": -1.0, "y1": 4.0, "x2": -1.0, "y2": 7.5, "room": "Dormitorio 1"},
    {"label": "8,00", "value_m": 8.0, "x1": 0, "y1": -2.0, "x2": 8.0, "y2": -2.0, "room": "General"},
    {"label": "7,50", "value_m": 7.5, "x1": -2.0, "y1": 0, "x2": -2.0, "y2": 7.5, "room": "General"},
]

# Superficies esperadas
EXPECTED_AREAS = {
    "Salón": 20.0,
    "Cocina": 12.0,
    "Dormitorio 1": 14.0,
    "Baño": 8.75,
}

# Expected manifest para tests
MANIFEST = {
    "document_type": "plano_arquitectura",
    "expected": {
        "scale": SCALE,
        "phase": PHASE,
        "revision": REVISION,
        "sheet": SHEET,
        "project": PROJECT,
        "rooms": [
            {"name": name, "area_m2": area}
            for name, area in EXPECTED_AREAS.items()
        ],
        "symbols": {
            "single_door": len(DOORS),
            "window": len(WINDOWS),
        },
        "dimensions": [
            {"label": d["label"], "value_m": d["value_m"]}
            for d in DIMENSIONS
        ],
    },
}


def generate_dxf(output_path: Path):
    """Genera DXF con plano arquitectónico."""
    import ezdxf
    from ezdxf import units

    doc = ezdxf.new("R2010")
    doc.units = units.M
    msp = doc.modelspace()

    # Capas
    doc.layers.add("MUROS", color=7)       # blanco
    doc.layers.add("COTAS", color=1)        # rojo
    doc.layers.add("TEXTO", color=3)        # verde
    doc.layers.add("PUERTAS", color=5)      # azul
    doc.layers.add("VENTANAS", color=6)     # magenta
    doc.layers.add("CAJETIN", color=7)

    # Dibujar muros (polilíneas cerradas por habitación)
    for name, room in ROOMS.items():
        x, y = room["x"], room["y"]
        w, l = room["w"], room["l"]
        points = [(x, y), (x + w, y), (x + w, y + l), (x, y + l), (x, y)]
        msp.add_lwpolyline(points, dxfattribs={"layer": "MUROS"})

    # Etiquetas de habitaciones
    for name, room in ROOMS.items():
        cx = room["x"] + room["w"] / 2
        cy = room["y"] + room["l"] / 2
        msp.add_text(
            name,
            dxfattribs={"layer": "TEXTO", "height": 0.25, "insert": (cx, cy)},
        )

    # Superficies
    for name, room in ROOMS.items():
        cx = room["x"] + room["w"] / 2
        cy = room["y"] + room["l"] / 2 - 0.4
        area = room["w"] * room["l"]
        msp.add_text(
            f"{area:.1f} m2",
            dxfattribs={"layer": "TEXTO", "height": 0.15, "insert": (cx, cy)},
        )

    # Puertas (arco + línea)
    for room_name, xo, yo, width, rot in DOORS:
        room = ROOMS[room_name]
        px = room["x"] + xo
        py = room["y"] + yo
        # Línea de puerta
        msp.add_line(
            (px, py), (px + width, py),
            dxfattribs={"layer": "PUERTAS"},
        )
        # Arco de apertura
        center = (px, py)
        msp.add_arc(
            center, radius=width, start_angle=0, end_angle=90,
            dxfattribs={"layer": "PUERTAS"},
        )

    # Ventanas (línea doble)
    for room_name, xo, yo, width, rot in WINDOWS:
        room = ROOMS[room_name]
        wx = room["x"] + xo
        wy = room["y"] + yo
        msp.add_line(
            (wx, wy), (wx + width, wy),
            dxfattribs={"layer": "VENTANAS"},
        )
        msp.add_line(
            (wx, wy + 0.1), (wx + width, wy + 0.1),
            dxfattribs={"layer": "VENTANAS"},
        )

    # Cotas (DXF DIMENSION entities)
    for dim in DIMENSIONS:
        msp.add_linear_dim(
            base=(dim["x1"], dim["y1"] - 0.3),
            p1=(dim["x1"], dim["y1"]),
            p2=(dim["x2"], dim["y2"]),
            dimstyle="EZDXF",
            override={"dimtxt": 0.2},
        )

    # Cajetín
    caj_x, caj_y = -3.0, -3.0
    msp.add_lwpolyline(
        [(caj_x, caj_y), (caj_x + 6, caj_y), (caj_x + 6, caj_y + 2), (caj_x, caj_y + 2), (caj_x, caj_y)],
        dxfattribs={"layer": "CAJETIN"},
    )
    msp.add_text(
        f"{PROJECT} - {PHASE}",
        dxfattribs={"layer": "CAJETIN", "height": 0.3, "insert": (caj_x + 0.2, caj_y + 1.5)},
    )
    msp.add_text(
        f"Hoja: {SHEET}  Rev: {REVISION}  Escala: {SCALE}",
        dxfattribs={"layer": "CAJETIN", "height": 0.2, "insert": (caj_x + 0.2, caj_y + 0.5)},
    )
    msp.add_text(
        f"Cliente: {CLIENT}",
        dxfattribs={"layer": "CAJETIN", "height": 0.15, "insert": (caj_x + 0.2, caj_y + 0.2)},
    )

    doc.saveas(str(output_path))
    print(f"DXF generado: {output_path}")


def generate_pdf(output_path: Path):
    """Genera PDF con plano arquitectónico (rasterizado con reportlab)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import black, red, blue, green, Color

    w_page, h_page = A4
    c = canvas.Canvas(str(output_path), pagesize=A4)

    # Factor de escala: 1m = 20mm en papel (1:100 → A4 ≈ 210mm = 10.5m)
    sf = 20  # mm per meter

    # Offset para centrar
    ox, oy = 30 * mm, 80 * mm

    def to_pdf(x_m, y_m):
        return (ox + x_m * sf, oy + y_m * sf)

    # Título
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, h_page - 20 * mm, f"{PROJECT}")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h_page - 28 * mm, f"{PHASE} - Hoja {SHEET} - Rev {REVISION} - Escala {SCALE}")

    # Muros
    c.setStrokeColor(black)
    c.setLineWidth(1.5)
    for name, room in ROOMS.items():
        x, y = to_pdf(room["x"], room["y"])
        w = room["w"] * sf
        l = room["l"] * sf
        c.rect(x, y, w, l)

    # Etiquetas
    c.setFillColor(green)
    c.setFont("Helvetica", 7)
    for name, room in ROOMS.items():
        cx, cy = to_pdf(room["x"] + room["w"] / 2, room["y"] + room["l"] / 2)
        c.drawCentredString(cx, cy, name)
        area = room["w"] * room["l"]
        c.drawCentredString(cx, cy - 10, f"{area:.1f} m²")

    # Cotas
    c.setFillColor(red)
    c.setFont("Helvetica", 6)
    for dim in DIMENSIONS:
        x1, y1 = to_pdf(dim["x1"], dim["y1"])
        x2, y2 = to_pdf(dim["x2"], dim["y2"])
        c.setStrokeColor(red)
        c.setLineWidth(0.5)
        c.line(x1, y1, x2, y2)
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        c.setFillColor(red)
        c.drawCentredString(mx, my + 3, f"{dim['label']} m")

    # Puertas (arco simplified)
    c.setStrokeColor(blue)
    c.setLineWidth(1)
    for room_name, xo, yo, width, rot in DOORS:
        room = ROOMS[room_name]
        px, py = to_pdf(room["x"] + xo, room["y"] + yo)
        pw = width * sf
        c.line(px, py, px + pw, py)
        c.arc(px, py, px + pw, py + pw, 0, 90)

    # Ventanas
    c.setStrokeColor(Color(0.6, 0, 0.6))
    c.setLineWidth(2)
    for room_name, xo, yo, width, rot in WINDOWS:
        room = ROOMS[room_name]
        wx, wy = to_pdf(room["x"] + xo, room["y"] + yo)
        ww = width * sf
        c.line(wx, wy, wx + ww, wy)

    # Cajetín
    c.setStrokeColor(black)
    c.setLineWidth(1)
    cx, cy = to_pdf(-0.5, -2.5)
    c.rect(cx, cy, 120, 40)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(cx + 5, cy + 30, f"{PROJECT} - {PHASE}")
    c.setFont("Helvetica", 6)
    c.drawString(cx + 5, cy + 20, f"Hoja: {SHEET}  Rev: {REVISION}  Escala: {SCALE}")
    c.drawString(cx + 5, cy + 10, f"Cliente: {CLIENT}")

    c.save()
    print(f"PDF generado: {output_path}")


def generate_manifest(output_path: Path):
    """Genera fixture JSON con valores esperados."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(MANIFEST, f, indent=2, ensure_ascii=False)
    print(f"Manifest generado: {output_path}")


if __name__ == "__main__":
    out_dir = Path(__file__).parent.parent / "data" / "input" / "planos"
    out_dir.mkdir(parents=True, exist_ok=True)

    generate_dxf(out_dir / "vivienda_planta_baja.dxf")
    generate_pdf(out_dir / "vivienda_planta_baja.pdf")
    generate_manifest(out_dir / "vivienda_planta_baja.manifest.json")

    print(f"\nArchivos generados en: {out_dir}")
    print(f"Esperado: {json.dumps(MANIFEST['expected'], indent=2, ensure_ascii=False)}")
