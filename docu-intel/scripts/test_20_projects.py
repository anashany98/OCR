#!/usr/bin/env python3
"""Test path resolver with 20 real corpus paths."""
from app.services.project_path_resolver import resolve_corpus_path, classify_category

paths = [
    "/app/source/2025/0377K76F113D78P89S57I48U117H64Y62K/Presupuesto 250434/EXCEL/file.xlsx",
    "/app/source/2025/ABIEL JARED SALAS GARCIA VILLARACO/Presupuesto 252234/CORREOS/msg.msg",
    "/app/source/2025/ABIEL JARED SALAS GARCIA VILLARACO/Presupuesto 252234/IMAGENES/foto.jpeg",
    "/app/source/2025/ABIEL JARED SALAS GARCIA VILLARACO/Presupuesto 252234/PDF/doc.pdf",
    "/app/source/2025/AGGIL MATRIZ SL/Presupuesto 250001/PDF/presupuesto.pdf",
    "/app/source/2025/AGROTURISMO MONTUIRI/Presupuesto 250100/EXCEL/pedido.xlsx",
    "/app/source/2025/AGUAS DE IBIZA-BONITO IBIZA HOTEL/Hotel Bonito/Presupuesto 250200/PDF/factura.pdf",
    "/app/source/2025/ALVARO SANS ARQUITECTURA HOTELERA S.L.P/Presupuesto 250300/PDF/plano.pdf",
    "/app/source/2025/ARABELLA HOTELS SL/Hotel Bella/Presupuesto 250400/IMAGENES/tejido.jpg",
    "/app/source/2025/AZULINE HOTELS-HOTEL BERGANTIN(BERG)/Presupuesto 250500/PDF/pedido.pdf",
    "/app/source/2025/APTOS C'AS SABONERS(SABO)/Presupuesto 250600/CORREOS/correo.msg",
    "/app/source/2025/AVANTE GESTION DE PROYECTOS Y OBRAS SOCIEDAD LIMITADA/Presupuesto 250700/EXCEL/presupuesto.xlsx",
    "/app/source/2025/ART-DOLLUM SL/Presupuesto 250800/PDF/albaran.pdf",
    "/app/source/2025/AGROTURISMO POLLENSA(AGRO)/Presupuesto 250900/IMAGENES/croquis.png",
    "/app/source/2025/ANTONIO NADAL DESTIL.LERIES SL/Presupuesto 251000/PDF/factura.pdf",
    "/app/source/2025/APARTHOTEL CAN PICAFORT PALACE S.L.U/Hotel Can Picafort/Presupuesto 251100/EXCEL/detalle.xlsx",
    "/app/source/2025/APTOS.PORTODRACH(PORT)/Presupuesto 251200/PDF/planos.pdf",
    "/app/source/2025/ADRIANE ESCARFULLRY/Presupuesto 251300/IMAGENES/render.jpg",
    "/app/source/2025/AITOR PERSONAL/Presupuesto 251400/PDF/incidencia.pdf",
    "/app/source/2025/ANGELA FRESNEDA LOZANO/Presupuesto 251500/CORREOS/pedido.msg",
]

results = {"total": 0, "with_brand": 0, "with_budget": 0, "with_hotel": 0, "errors": 0}

print(f"Testing {len(paths)} paths from the corpus...")
print(f"{'#':<3} {'Brand':<30} {'Hotel':<20} {'Budget':<10} {'Category':<12}")
print("-" * 80)

for i, p in enumerate(paths, 1):
    try:
        r = resolve_corpus_path(p, "/app/source/2025")
        cat = classify_category(p.split("/")[-1], r.category)
        results["total"] += 1
        if r.brand:
            results["with_brand"] += 1
        if r.budget_code:
            results["with_budget"] += 1
        if r.hotel:
            results["with_hotel"] += 1
        hotel_display = r.hotel or "-"
        print(f"{i:<3} {(r.brand or '?'):<30} {hotel_display:<20} {(r.budget_code or '?'):<10} {cat:<12}")
    except Exception as e:
        results["errors"] += 1
        print(f"{i:<3} ERROR: {e}")

print()
print(f"Results: {results['total']} total, {results['with_brand']} with brand, "
      f"{results['with_budget']} with budget, {results['with_hotel']} with hotel, "
      f"{results['errors']} errors")
