from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


def calculate_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stored_relative_path(file_hash: str, extension: str | None) -> Path:
    clean_extension = (extension or "").lower()
    if clean_extension and not clean_extension.startswith("."):
        clean_extension = "." + clean_extension
    return Path(file_hash[:2]) / f"{file_hash}{clean_extension}"


def copy_to_storage(
    source: Path,
    files_dir: Path,
    file_hash: str,
    extension: str | None,
    *,
    strategy: str = "copy",
) -> Path:
    relative_path = stored_relative_path(file_hash, extension)
    target = files_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        if strategy in {"hardlink", "auto"}:
            try:
                os.link(source, target)
                return relative_path
            except OSError:
                if strategy == "hardlink":
                    raise
        shutil.copy2(source, target)
    return relative_path
