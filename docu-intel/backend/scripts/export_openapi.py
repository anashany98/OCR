"""Export the FastAPI OpenAPI schema to ``openapi.json``.

Usage::

    cd docu-intel/backend
    python -m scripts.export_openapi
    # -> ../../docs/openapi.json
    python -m scripts.export_openapi --output /tmp/api.json

The generated file is intended for:

* consumers that generate typed API clients (openapi-typescript, orval, ...)
* contract tests that detect breaking changes between releases
* documentation portals (Redoc, Stoplight, ...)

CI runs this script and diffs the output against the committed snapshot
(see ``tests/test_openapi_contract.py``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _resolve_app():
    # Lazy import to avoid loading the full app on --help.
    from app.main import app

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the FastAPI OpenAPI schema.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs" / "openapi.json",
        help="Where to write the schema. Defaults to <repo>/docs/openapi.json.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Use 0 to produce a single-line file.",
    )
    args = parser.parse_args()

    app = _resolve_app()
    schema = app.openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(schema, indent=args.indent, sort_keys=False),
        encoding="utf-8",
    )
    print(f"OpenAPI schema written to {args.output}")
    print(f"  paths: {len(schema.get('paths', {}))}")
    print(f"  components.schemas: {len(schema.get('components', {}).get('schemas', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
