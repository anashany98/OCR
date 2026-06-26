"""Local smoke test for Hyper-Extract.

Run from the backend root (or via Docker) to verify the service is
configured correctly without touching the database.

Usage:
    python scripts/test_hyperextract.py --file ./samples/factura_ocr.txt --type factura
    python scripts/test_hyperextract.py --text "FACTURA 1234..." --type factura
    python scripts/test_hyperextract.py --status-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _bootstrap_path() -> None:
    """Make ``app`` importable regardless of the working directory.

    The script lives in ``backend/scripts``; the package root is one
    directory up. We push it on ``sys.path`` so ``import app`` works
    when the operator runs the script from any cwd.
    """
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _read_text(path: str | None, text: str | None) -> str:
    if text:
        return text
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"input file not found: {path}")
    return p.read_text(encoding="utf-8", errors="replace")


def _print_envelope(envelope: dict) -> None:
    print("=" * 72)
    print("Hyper-Extract result")
    print("=" * 72)
    summary = {
        "enabled": envelope.get("enabled"),
        "status": envelope.get("status"),
        "document_id": envelope.get("document_id"),
        "document_type": envelope.get("document_type"),
        "provider": envelope.get("provider"),
        "model": envelope.get("model"),
        "latency_ms": envelope.get("latency_ms"),
        "warnings": envelope.get("warnings") or [],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    fields = envelope.get("fields") or {}
    print("\nExtracted fields:")
    if fields:
        print(json.dumps(fields, ensure_ascii=False, indent=2))
    else:
        print("  (none)")
    entities = envelope.get("entities") or []
    print(f"\nEntities ({len(entities)}):")
    if entities:
        print(json.dumps(entities, ensure_ascii=False, indent=2))
    else:
        print("  (none)")
    relations = envelope.get("relations") or []
    print(f"\nRelations ({len(relations)}):")
    if relations:
        print(json.dumps(relations, ensure_ascii=False, indent=2))
    else:
        print("  (none)")
    if envelope.get("error_message"):
        print(f"\nError: {envelope['error_message']}")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test for Hyper-Extract")
    parser.add_argument("--file", help="Path to a UTF-8 text file with OCR output")
    parser.add_argument("--text", help="Raw OCR text (overrides --file)")
    parser.add_argument(
        "--type",
        default=None,
        help="Document type (factura, albaran, contrato, presupuesto). "
        "Defaults to HYPEREXTRACT_DEFAULT_TYPE from settings.",
    )
    parser.add_argument(
        "--document-id",
        default="smoke-test",
        help="Identifier stored in the result envelope (default: smoke-test).",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Only print the service status (no provider call).",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override HYPEREXTRACT_PROVIDER for this run.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override HYPEREXTRACT_BASE_URL for this run.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override HYPEREXTRACT_MODEL for this run.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override HYPEREXTRACT_API_KEY for this run.",
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help="Force HYPEREXTRACT_ENABLED=true for this run.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Override HYPEREXTRACT_TIMEOUT_SECONDS for this run.",
    )
    args = parser.parse_args()

    if args.enable:
        os.environ["HYPEREXTRACT_ENABLED"] = "true"
    if args.provider is not None:
        os.environ["HYPEREXTRACT_PROVIDER"] = args.provider
    if args.base_url is not None:
        os.environ["HYPEREXTRACT_BASE_URL"] = args.base_url
    if args.model is not None:
        os.environ["HYPEREXTRACT_MODEL"] = args.model
    if args.api_key is not None:
        os.environ["HYPEREXTRACT_API_KEY"] = args.api_key
    if args.timeout is not None:
        os.environ["HYPEREXTRACT_TIMEOUT_SECONDS"] = str(args.timeout)

    _bootstrap_path()
    # Import after env overrides so ``Settings`` picks them up.
    from app.services.hyperextract.service import (  # noqa: E402  (intentional)
        HyperExtractService,
    )
    from app.services.hyperextract.templates import list_templates  # noqa: E402

    service = HyperExtractService()

    print("Templates loaded:")
    for template in list_templates():
        print(f"  - {template.document_type} (v{template.version}): {template.description}")
    print()
    print(
        f"Service status: enabled={service.is_enabled()} "
        f"base_url={service._base_url!r} model={service._model!r}"
    )

    if args.status_only:
        return 0

    text = _read_text(args.file, args.text)
    if not text.strip():
        print("\nNo input text provided. Pass --file <path> or --text <value>.")
        return 1

    envelope = service.extract_from_text(
        document_id=args.document_id,
        text=text,
        document_type=args.type,
    )
    _print_envelope(envelope)

    # Exit code mirrors the envelope status so the script can be used
    # in CI smoke pipelines.
    status = envelope.get("status")
    if status == "success":
        return 0
    if status == "disabled":
        print("\nHyper-Extract is disabled. Set HYPEREXTRACT_ENABLED=true "
              "and configure BASE_URL/MODEL/API_KEY to make a real call.")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
