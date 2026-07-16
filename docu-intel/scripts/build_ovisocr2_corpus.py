"""Create a local, non-versioned OvisOCR2 benchmark manifest from images."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container-root")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    images = []
    for path in args.source.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        try:
            with Image.open(path) as image:
                pixels = image.width * image.height
            if 200704 <= pixels <= 8294400:
                images.append(path)
        except OSError:
            continue
    images.sort()
    if not images:
        raise SystemExit(f"No images found under {args.source}")
    step = max(1, len(images) // args.limit)
    selected = images[::step][: args.limit]
    pages = []
    for index, image in enumerate(selected, start=1):
        relative = image.relative_to(args.source)
        image_path = f"{args.container_root.rstrip('/')}/{relative.as_posix()}" if args.container_root else image.resolve()
        pages.append({"document_id": f"benchmark-{index}", "page_number": 1, "category": image.suffix.lower().lstrip("."), "image": str(image_path)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"pages": pages}, indent=2), encoding="utf-8")
    print(f"Wrote {len(pages)} benchmark pages to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
