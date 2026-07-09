from app.services.classification import classify_document


def test_classifies_budget_from_filename_folder_and_text():
    result = classify_document(
        filename="Presupuesto_2026_143.pdf",
        source_path="/data/input/presupuestos/Presupuesto_2026_143.pdf",
        text="Cliente ACME. Total presupuesto 1245,60 EUR. Validez 30 dias.",
    )

    assert result.document_type == "presupuesto"
    assert result.confidence >= 0.8


def test_classifies_plan_from_folder_and_keywords():
    result = classify_document(
        filename="obra-x-planta.pdf",
        source_path="/data/input/planos/obra-x-planta.pdf",
        text="Escala 1:50. Planta baja. Salon 24 m2. Cotas principales.",
    )

    assert result.document_type == "plano"
    assert result.confidence >= 0.8


def test_image_inside_planos_folder_stays_image_without_plan_signals():
    result = classify_document(
        filename="foto_jardin.jpg",
        source_path="/data/input/planos/foto_jardin.jpg",
        text="Foto del jardin con arboles y cielo despejado sin escala ni cotas tecnicas.",
    )

    assert result.document_type == "imagen"


def test_image_with_furniture_keywords_is_foto_producto():
    # Las fotos de interiorismo con mobiliario ahora son subtipo foto_producto,
    # no el tipo genérico "imagen".
    result = classify_document(
        filename="foto_sofa.jpg",
        source_path="/data/input/imagenes/foto_sofa.jpg",
        text="Foto de sofa tapizado y mesa auxiliar sin escala ni cotas tecnicas.",
    )

    assert result.document_type == "foto_producto"


def test_image_with_fabric_keywords_is_muestra_tela():
    result = classify_document(
        filename="muestra.jpg",
        source_path="/data/input/telas/muestra.jpg",
        text="Muestra de tela visillo lino algodon para cortina.",
    )

    assert result.document_type == "muestra_tela"


def test_pdf_comprobante_pago_from_keywords():
    result = classify_document(
        filename="comprobante.pdf",
        source_path="/data/input/comprobante.pdf",
        text="SEPA servicio de banca a distancia comprobante de pago transferencia.",
    )

    assert result.document_type == "comprobante_pago"


def test_pdf_dua_from_keywords():
    result = classify_document(
        filename="DUA EXPORT.PDF",
        source_path="/data/input/DUA EXPORT.PDF",
        text="EX A 26ES000855 circuito verde despacho aduanero decoraciones egea.",
    )

    assert result.document_type == "dua"


def test_pdf_albaran_transporte_from_keywords():
    result = classify_document(
        filename="recogida.pdf",
        source_path="/data/input/recogida.pdf",
        text="POP recogida MBE UPS entrega transporte etiqueta.",
    )

    assert result.document_type == "albaran_transporte"


def test_image_inside_planos_folder_with_plan_filename_can_be_plan():
    result = classify_document(
        filename="plano_planta_baja.jpg",
        source_path="/data/input/planos/plano_planta_baja.jpg",
        text="",
    )

    assert result.document_type == "plano"


def test_planos_folder_pdf_needs_real_plan_signal():
    result = classify_document(
        filename="catalogo_muebles.pdf",
        source_path="/data/input/planos/catalogo_muebles.pdf",
        text="Catalogo de muebles para salon con medidas de ancho y alto.",
    )

    assert result.document_type != "plano"


# --- Tests para los tipos nuevos sin cobertura (croquis_medida, ficha_tecnica,
# tarifa, proforma, instrucciones, render) y la Phase 0 de content_route. ---


def test_croquis_medida_from_content_route_with_measure_signals():
    # content_route=interior_design + >=2 señales de medida (croquis, medida,
    # cota) activa el subtipo croquis_medida (Phase 0).
    result = classify_document(
        filename="croquis_ventana.jpg",
        source_path="/data/input/imagenes/croquis_ventana.jpg",
        text="Croquis a medida con cota ancho 120 y caida 15.",
        content_route="interior_design",
    )

    assert result.document_type == "croquis_medida"


def test_ficha_tecnica_from_keywords():
    result = classify_document(
        filename="datasheet_motor.pdf",
        source_path="/data/input/fichas/datasheet_motor.pdf",
        text="Ficha tecnica del motor. Datos technical data. Certificate de conformidad.",
    )

    assert result.document_type == "ficha_tecnica"


def test_tarifa_from_keywords():
    result = classify_document(
        filename="lista_precios_2026.pdf",
        source_path="/data/input/precios/lista_precios_2026.pdf",
        text="Tarifa de precios vigente. Price list. Catalogo de precios actualizado.",
    )

    assert result.document_type == "tarifa"


def test_proforma_from_keywords():
    result = classify_document(
        filename="conferma_ordine_1234.pdf",
        source_path="/data/input/proformas/conferma_ordine_1234.pdf",
        text="Proforma. Conferma d'ordine 1234. Confirmacion de compra.",
    )

    assert result.document_type == "proforma"


def test_instrucciones_from_keywords():
    result = classify_document(
        filename="manual_montaje.pdf",
        source_path="/data/input/manuales/manual_montaje.pdf",
        text="Instrucciones de montaje. Manual de uso y mantenimiento del mueble.",
    )

    assert result.document_type == "instrucciones"


def test_render_from_keywords():
    result = classify_document(
        filename="concept_render_salon.jpg",
        source_path="/data/input/renders/concept_render_salon.jpg",
        text="Render 3D del salon. Visualizacion del proyecto de interiorismo.",
    )

    assert result.document_type == "render"


def test_phase0_interior_design_without_measure_signals_is_foto_producto():
    # content_route=interior_design sin señales de medida -> foto_producto.
    result = classify_document(
        filename="foto_sofa.jpg",
        source_path="/data/input/imagenes/foto_sofa.jpg",
        text="Sofa tapizado color gris. Mesa auxiliar a juego.",
        content_route="interior_design",
    )

    assert result.document_type == "foto_producto"


def test_phase0_fabric_description_is_muestra_tela():
    result = classify_document(
        filename="muestra_lino.jpg",
        source_path="/data/input/telas/muestra_lino.jpg",
        text="",
        content_route="fabric_description",
    )

    assert result.document_type == "muestra_tela"

