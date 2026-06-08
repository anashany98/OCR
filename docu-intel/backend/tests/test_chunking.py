from __future__ import annotations


def test_build_chunks_respects_sentence_boundaries_when_possible():
    from app.services.chunking import build_chunks

    chunks = build_chunks(
        "Primera frase completa. Segunda frase con importe total. Tercera frase final.",
        max_words=5,
        overlap_words=0,
    )

    assert [text for text, _ in chunks] == [
        "Primera frase completa.",
        "Segunda frase con importe total.",
        "Tercera frase final.",
    ]


def test_build_chunks_keeps_paragraph_sentences_together_under_limit():
    from app.services.chunking import build_chunks

    chunks = build_chunks(
        "Cabecera del documento. Referencia ABC123.\n\n"
        "Detalle de factura. Total factura 120 euros.",
        max_words=7,
        overlap_words=0,
    )

    assert [text for text, _ in chunks] == [
        "Cabecera del documento. Referencia ABC123.",
        "Detalle de factura. Total factura 120 euros.",
    ]
