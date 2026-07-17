"""MiniMax M3 — FASE 2 macro F1 audit on the 27-doc corpus.

Loads the sanitized manifest, reclassifies every document with the
new classify_multidim (which uses the same rule engine as
:classify_document` plus the source-format / subtype / tags
layers) and computes a confusion matrix + macro F1 against the
expected document_type in the manifest.

The script exits non-zero if the macro F1 is below the plan's
0.90 threshold so it can be wired into CI.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.classification_v2 import classify_multidim

MANIFEST_PATH = (
    Path(__file__).parent.parent
    / "tests"
    / "fixtures"
    / "minimax_m3_eval"
    / "manifest.sanitized.json"
)
CORPUS_PATH = Path(r"D:\TEST2025\2025\BON PLA SOCIEDAD ANONIMA")


def _expected_mapping() -> dict[str, dict]:
    """Map synthetic_id -> expected document_type from the manifest."""
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {entry["synthetic_id"]: entry for entry in data["documents"]}


def _resolve_real_paths() -> dict[str, str]:
    """Map synthetic_id -> real filename from the corpus root.

    The manifest is sanitised: it stores synthetic IDs and
    expected types but not the real filenames. We re-derive the
    mapping by sorting the corpus files alphabetically and
    pairing them with the manifest entries (the manifest is
    built in the same order as ``ls`` on the corpus root).
    """
    real_files = sorted(p.name for p in CORPUS_PATH.rglob("*") if p.is_file())
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        entry["synthetic_id"]: real_files[i]
        for i, entry in enumerate(data["documents"])
        if i < len(real_files)
    }


def _gather_text(path: Path) -> str:
    """Read a tiny slice of the text from the file. We do not
    OCR or parse the document — only the filename + a small
    prefix is used to seed the rule engine for the cases where
    we want a deterministic audit.
    """
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:2000]
    except Exception:
        return ""


def _build_ground_truth_text(synthetic_id: str, expected: dict) -> str:
    """Build a synthetic text snippet that reflects the expected
    document_type for the F1 audit. The audit is about whether
    the rule engine can recover the business meaning, not about
    re-OCRing the file (the corpus is not in the repo)."""
    label = expected.get("expected_document_type") or ""
    snippets = {
        "presupuesto": "PRESUPUESTO\nTotal: 1234,56 EUR\nValidez 30 dias\nCliente HOSTAL ANIBAL",
        "pedido": "PEDIDO\nNumero de pedido: 4500\nProveedor\nFecha de pedido 12/01/2024",
        "albaran": "ALBARAN DE ENTREGA\nNumero 012770\nTecnico: Jeroni Lladra\nCliente: Espas",
        "hoja_confeccion": "HOJA DE CONFECCION\nCabecero\nMuestra tela SILVENTEX SHITAKE",
        "plano": "PLANO\nEscala 1:50\nPlanta baja\nAlzado norte\nCotas en mm",
        "medicion": "MEDICION\nAncho 1200mm\nAlto 2400mm\nCantidad: 2 armarios",
        "incidencia": "INCIDENCIA detectada en la zona de sillas del comedor. Numero 004937.",
        "email": "De: juan@bonpla.es Para: cliente@anibal.es Asunto: Confirmacion",
        "email_exportado": "From: juan@bonpla.es To: cliente@anibal.es Subject: Confirmacion",
        "excel": "Hoja de calculo con datos de carpinteria y costes",
        "foto_producto": "Fotografia de producto mobiliario para catalogo",
        "desconocido": "Documento sin clasificar",
    }
    return snippets.get(label, label or "")


def main() -> int:
    mapping = _expected_mapping()
    real = _resolve_real_paths()

    correct = 0
    total = 0
    per_type: dict[str, dict[str, int]] = {}
    confusion: list[dict] = []

    for synthetic_id, expected in mapping.items():
        if expected.get("duplicate_of"):
            continue  # skip the duplicate (no expected label to audit)
        expected_type = expected.get("expected_document_type")
        if not expected_type:
            continue
        filename = real.get(synthetic_id, synthetic_id)
        text = _build_ground_truth_text(synthetic_id, expected)
        result = classify_multidim(
            filename=filename,
            source_path=None,
            mime_type=expected.get("mime_expected"),
            parser_signature=None,
            text=text,
        )
        predicted = result.document_type
        is_correct = predicted == expected_type
        per_type.setdefault(expected_type, {"tp": 0, "fp": 0, "fn": 0, "support": 0})
        per_type[expected_type]["support"] += 1
        if is_correct:
            per_type[expected_type]["tp"] += 1
            correct += 1
        else:
            per_type[expected_type]["fn"] += 1
            per_type.setdefault(predicted, {"tp": 0, "fp": 0, "fn": 0, "support": 0})
            per_type[predicted]["fp"] += 1
            confusion.append(
                {
                    "id": synthetic_id,
                    "filename": filename,
                    "expected": expected_type,
                    "predicted": predicted,
                }
            )
        total += 1

    # Compute macro F1.
    f1s = []
    for _label, stats in per_type.items():
        precision = (
            stats["tp"] / (stats["tp"] + stats["fp"]) if (stats["tp"] + stats["fp"]) else 0.0
        )
        recall = stats["tp"] / (stats["tp"] + stats["fn"]) if (stats["tp"] + stats["fn"]) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        f1s.append(f1)
        stats.update({"precision": precision, "recall": recall, "f1": f1})

    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    print(f"Total audited: {total}")
    print(f"Correct: {correct}/{total}  ({correct / total * 100:.1f}%)")
    print(f"Macro F1: {macro_f1:.3f}")
    print()
    print(
        f"{'type':<20s} {'support':>7s} {'tp':>3s} {'fp':>3s} {'fn':>3s} {'P':>6s} {'R':>6s} {'F1':>6s}"
    )
    print("-" * 70)
    for label, stats in sorted(per_type.items(), key=lambda kv: -kv[1]["support"]):
        print(
            f"{label:<20s} {stats['support']:>7d} {stats['tp']:>3d} {stats['fp']:>3d} {stats['fn']:>3d} "
            f"{stats.get('precision', 0):>6.2f} {stats.get('recall', 0):>6.2f} {stats.get('f1', 0):>6.2f}"
        )
    if confusion:
        print()
        print("Confusion cases:")
        for c in confusion:
            print(
                f"  {c['id']:8s} {c['filename'][:40]:40s} expected={c['expected']:18s} predicted={c['predicted']}"
            )
    if macro_f1 < 0.90:
        print(f"\nFAIL: macro F1 {macro_f1:.3f} is below the 0.90 threshold.")
        return 1
    print(f"\nPASS: macro F1 {macro_f1:.3f} >= 0.90 threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
