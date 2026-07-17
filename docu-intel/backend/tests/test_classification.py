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


def test_email_with_furniture_terms_stays_email_not_product_photo():
    result = classify_document(
        filename="re_pedido_proveedor.msg",
        source_path="/data/input/re_pedido_proveedor.msg",
        text=(
            "Asunto: RE: PEDIDO PROVEEDOR\nDe: compras@example.com\n"
            "Para: proveedor@example.com\nNecesitamos las sillas y armarios."
        ),
        content_route="interior_design",
    )

    assert result.document_type == "email_exportado"


def test_spreadsheet_with_furniture_terms_stays_excel_not_product_photo():
    result = classify_document(
        filename="carpinteria.xlsx",
        source_path="/data/input/carpinteria.xlsx",
        text="ARTICULO | CANTIDAD | ARMARIO | SILLA | MUEBLE | COSTE",
        content_route="interior_design",
    )

    assert result.document_type == "excel"


def test_scanned_ppto_is_quote_not_product_photo():
    result = classify_document(
        filename="ppto aceptado con descuento.jpeg",
        source_path="/data/input/IMAGENES/ppto aceptado con descuento.jpeg",
        text="",
        content_route="interior_design",
    )

    assert result.document_type == "presupuesto"


def test_budget_parent_folder_does_not_turn_uploaded_photo_into_quote():
    result = classify_document(
        filename="BLUEBAY/Presupuesto 252240/IMAGENES/DORMITORIO.jpeg",
        source_path="upload/7/BLUEBAY/Presupuesto 252240/IMAGENES/DORMITORIO.jpeg",
        text="",
        content_route="interior_design",
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


# ---------------------------------------------------------------------------
# Fix 1 (regression 2026-07-16): PDFs whose leaf filename declares
# ``presupuesto`` must report as ``presupuesto`` even when the body
# mentions dimensional vocabulary. Previously the short-circuit was
# image-only and PDFs lost to the ``medicion`` rule whenever the OCR
# yielded numbers and headers like ``ACEPTACION PRESUPUESTO``.
# ---------------------------------------------------------------------------


def test_pdf_presupuesto_filename_wins_over_body_dimension_vocabulary():
    result = classify_document(
        filename="Presupuesto 1-250258 MELIA HOTELS INTERNATIONAL S.A..pdf",
        source_path="/app/data/input/MELIA/Presupuesto 250258/PDF/Presupuesto 1-250258 MELIA HOTELS INTERNATIONAL S.A..pdf",
        text=(
            "1.348,21 N.I.F. TIPO IVA% IMPORTE I.V.A. 40% ACEPTACION PRESUPUESTO 30% "
            "RECEPCION MATERIALES 30% FINALIZACION TRABAJO NIF TEL. FAX "
            "Ancho 240 cm, largo 180 cm, alto 75 cm."
        ),
    )
    assert result.document_type == "presupuesto"


def test_pdf_presupuesto_abbrev_ppto_wins_too():
    result = classify_document(
        filename="ppto_250544_melia.pdf",
        source_path="/app/data/input/ppto_250544_melia.pdf",
        text="Ancho 200 cm alto 180 cm. IVA 21%.",
    )
    assert result.document_type == "presupuesto"


# ---------------------------------------------------------------------------
# Fix 2 (regression 2026-07-16): an .xlsx file is always a spreadsheet,
# regardless of content_route or body vocabulary. Previously a
# spreadsheet whose cells contained address/header lines plus
# dimensional columns outscored the ``excel`` extension hint because
# the Phase 0 short-circuit only fired when content_route was
# interior_design / fabric_description.
# ---------------------------------------------------------------------------


def test_xlsx_with_dimension_vocabulary_in_body_still_classifies_as_excel():
    result = classify_document(
        filename="PL_FRA PLANTILLA_solo FILIAL R.D y MX.xlsx",
        source_path="/app/data/input/PLANTILLA_solo.xlsx",
        text=(
            "### Hoja: PL - C/ Gremi Ferrers 29 - Pol. Son Castello 07009 Baleares - "
            "Telf.: 971 - 43.37.90  Fax.: 971 - 43.60.76"
        ),
        content_route=None,
    )
    assert result.document_type == "excel"


def test_xlsx_with_no_content_route_still_classifies_as_excel():
    result = classify_document(
        filename="datos_obra.xlsx",
        source_path="/app/data/input/datos_obra.xlsx",
        text="",
    )
    assert result.document_type == "excel"


# ---------------------------------------------------------------------------
# Fix 3 (regression 2026-07-16): the ``medicion`` rule used to include
# generic dimensional words (``ancho``, ``alto``, ``largo``,
# ``cantidad``, ``armario``) which made it win over more specific
# types like ``presupuesto`` whenever the OCR body mentioned
# dimensions. The generic words are gone; ``medicion`` now requires
# explicit measurement vocabulary in either filename or body.
# ---------------------------------------------------------------------------


def test_pdf_presupuesto_with_dimension_body_does_not_become_medicion():
    """A quote that lists dimensions in the body must stay a quote."""
    result = classify_document(
        filename="presupuesto_250298.pdf",
        source_path="/app/data/input/presupuesto_250298.pdf",
        text=(
            "Cliente ACME. Total presupuesto 1.245,60 EUR. Validez 30 dias. "
            "Ancho 240 cm, alto 180 cm, largo 75 cm. Cantidad 4 unidades."
        ),
    )
    assert result.document_type == "presupuesto"
    assert result.document_type != "medicion"


def test_pedido_with_armario_vocabulary_does_not_become_medicion():
    """``armario`` was previously a medicion keyword. An order whose
    body lists the items must stay an order."""
    result = classify_document(
        filename="pedido_250102.pdf",
        source_path="/app/data/input/pedido_250102.pdf",
        text=(
            "Pedido 250102. Cliente: Hotel X. Fecha pedido: 2026-05-14. "
            "2 armarios, 4 sillas, 1 mesa. Total 4.500 EUR."
        ),
    )
    assert result.document_type == "pedido"
    assert result.document_type != "medicion"


def test_explicit_measurement_filename_still_wins_as_medicion():
    """The fix removes the generic words; the explicit ones remain."""
    result = classify_document(
        filename="Medición 2 armarios hotel lobby.docx",
        source_path="/app/data/input/Medición 2 armarios hotel lobby.docx",
        text="",
    )
    assert result.document_type == "medicion"


# ---------------------------------------------------------------------------
# Fix 4 (regression 2026-07-16): the registration-time filename
# keyword pass in ``document_registration_service`` populates
# ``document_type`` for files whose leaf name strongly declares a
# type, so a PDF does not sit as ``desconocido`` until the worker
# reclassifies it.
# ---------------------------------------------------------------------------


def test_filename_hint_returns_presupuesto_for_pdf():
    from app.services.document_registration_service import _type_from_filename

    assert _type_from_filename("Presupuesto 1-250544 MELIA.pdf") == "presupuesto"
    assert _type_from_filename("PPTO 250000.pdf") == "presupuesto"


def test_filename_hint_returns_factura_and_invoice():
    from app.services.document_registration_service import _type_from_filename

    assert _type_from_filename("Factura 2-250013.pdf") == "factura"
    assert _type_from_filename("INVOICE AR INV - BCA2500222229.PDF") == "factura"


def test_filename_hint_returns_albaran():
    from app.services.document_registration_service import _type_from_filename

    assert _type_from_filename("albaran de entrega II.pdf") == "albaran"
    assert _type_from_filename("albarán de recogida muestra.pdf") == "albaran"


def test_filename_hint_returns_pedido_and_order():
    from app.services.document_registration_service import _type_from_filename

    assert _type_from_filename("pedido_250102.pdf") == "pedido"
    assert _type_from_filename("order_99001.xlsx") == "pedido"


def test_filename_hint_returns_hoja_confeccion():
    from app.services.document_registration_service import _type_from_filename

    assert (
        _type_from_filename("hoja de confeccion sombrillas erroneas beige.pdf")
        == "hoja_confeccion"
    )


def test_filename_hint_returns_medicion_and_incidencia():
    from app.services.document_registration_service import _type_from_filename

    assert _type_from_filename("MEDIDAS.pdf") == "medicion"
    assert _type_from_filename("incidencia silla lobby.pdf") == "incidencia"


def test_filename_hint_returns_none_for_ambiguous_filename():
    from app.services.document_registration_service import _type_from_filename

    assert _type_from_filename("0892_001.pdf") is None
    assert _type_from_filename("scan_2025_05_18.pdf") is None
    # Folder hints must NOT trigger the filename hint — the registration
    # pass is leaf-only by design (the worker reclassifies with the
    # full path).
    assert _type_from_filename("/app/data/presupuestos/x.pdf") is None

