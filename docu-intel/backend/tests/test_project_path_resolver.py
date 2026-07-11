"""Tests for Phase 3 — project_path_resolver."""

from app.services.project_path_resolver import resolve_corpus_path, classify_category


class TestResolveCorpusPath:
    def test_direct_brand_budget(self):
        r = resolve_corpus_path("2025/ACME/Presupuesto 252536/PDF/file.pdf")
        assert r.year == 2025
        assert r.brand == "ACME"
        assert r.hotel is None
        assert r.budget_code == "252536"
        assert r.category == "PDF"

    def test_brand_hotel_budget(self):
        r = resolve_corpus_path("2025/ACME/Hotel Riviera/Presupuesto 250922/Excel/pedido.xlsx")
        assert r.year == 2025
        assert r.brand == "ACME"
        assert r.hotel == "Hotel Riviera"
        assert r.budget_code == "250922"
        assert r.category == "Excel"

    def test_brand_with_mixed_structure(self):
        r1 = resolve_corpus_path("2025/GrupoX/Presupuesto 111/PDF/a.pdf")
        r2 = resolve_corpus_path("2025/GrupoX/HotelY/Presupuesto 222/PDF/b.pdf")
        assert r1.brand == "GrupoX"
        assert r1.hotel is None
        assert r2.brand == "GrupoX"
        assert r2.hotel == "HotelY"

    def test_rejected_budget_name(self):
        r = resolve_corpus_path("2025/ACME/PDF/file.pdf")
        assert r.budget_code is None
        assert r.brand == "ACME"

    def test_no_presupuesto(self):
        r = resolve_corpus_path("2025/ACME/HotelX/imagenes/foto.jpg")
        assert r.year == 2025
        assert r.brand == "ACME"
        assert r.hotel == "HotelX"
        assert r.budget_code is None

    def test_unicode_segments(self):
        r = resolve_corpus_path("2025/Marca España/Hotel Açor/Presupuesto 12345/PDF/archivo.pdf")
        assert r.brand == "Marca España"
        assert r.hotel == "Hotel Açor"
        assert r.budget_code == "12345"

    def test_spaces_in_budget_code(self):
        r = resolve_corpus_path("2025/ACME/Presupuesto 25 25 36/PDF/f.pdf")
        assert r.budget_code == "25 25 36"

    def test_with_source_root(self):
        r = resolve_corpus_path(
            "D:/TEST2025/2025/ACME/Presupuesto 123/PDF/f.pdf",
            source_root="D:/TEST2025/2025",
        )
        assert r.year == 2025
        assert r.brand == "ACME"
        assert r.budget_code == "123"

    def test_backslash_path(self):
        r = resolve_corpus_path("2025\\ACME\\Presupuesto 999\\PDF\\f.pdf")
        assert r.year == 2025
        assert r.brand == "ACME"
        assert r.budget_code == "999"

    def test_no_year(self):
        r = resolve_corpus_path("ACME/Presupuesto 123/PDF/f.pdf")
        assert r.year is None
        assert r.brand == "ACME"
        assert r.budget_code == "123"


class TestClassifyCategory:
    def test_excel_is_pedidos(self):
        assert classify_category("pedido.xlsx") == "pedidos"

    def test_factura_in_name(self):
        assert classify_category("factura_001.pdf") == "facturas"

    def test_albaran(self):
        assert classify_category("albaran_entrega.pdf") == "albaranes"

    def test_image(self):
        assert classify_category("foto_producto.jpg") == "imagenes"

    def test_msg_is_correos(self):
        assert classify_category("mensaje.msg") == "correos"

    def test_folder_category_override(self):
        assert classify_category("any.pdf", "IMAGENES") == "imagenes"

    def test_unknown_is_otros(self):
        assert classify_category("archivo.dat") == "otros"
