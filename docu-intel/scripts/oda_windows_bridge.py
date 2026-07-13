"""Authenticated local bridge from Docker to Windows ODA File Converter.

Run this on the Windows host where ODAFileConverter.exe is installed:

  python scripts/oda_windows_bridge.py --token <long-random-token>

It listens on the local Docker host gateway. Every request must carry the
same token. No original DWG is modified: conversion happens in a temporary
workspace and the generated DXF is returned directly to the backend.
"""

from __future__ import annotations

import argparse
import cgi
import hmac
import os
import subprocess
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_ODA = Path(r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe")


class OdaBridgeHandler(BaseHTTPRequestHandler):
    server: "OdaBridgeServer"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/convert":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        supplied = self.headers.get("X-Docu-Intel-Bridge-Token", "")
        if not hmac.compare_digest(supplied, self.server.token):
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "multipart/form-data":
            self.send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Expected multipart/form-data")
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]},
            )
            uploaded = form["file"]
            filename = Path(uploaded.filename or "plan.dwg").name
            if Path(filename).suffix.lower() != ".dwg":
                raise ValueError("Only .dwg files are accepted")
            payload = uploaded.file.read(self.server.max_bytes + 1)
            if not payload or len(payload) > self.server.max_bytes:
                raise ValueError("DWG is empty or exceeds the configured size limit")
            dxf = self.server.convert(filename, payload)
        except (KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
            self.send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/dxf")
        self.send_header("Content-Length", str(len(dxf)))
        self.end_headers()
        self.wfile.write(dxf)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Do not log filenames or tokens; the backend already records the job.
        return


class OdaBridgeServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], *, token: str, executable: Path, max_bytes: int) -> None:
        super().__init__(address, OdaBridgeHandler)
        self.token = token
        self.executable = executable
        self.max_bytes = max_bytes

    def convert(self, filename: str, payload: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="docu_intel_oda_") as root:
            workspace = Path(root)
            input_dir = workspace / "input"
            output_dir = workspace / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            source = input_dir / filename
            source.write_bytes(payload)
            completed = subprocess.run(
                [str(self.executable), str(input_dir), str(output_dir), "ACAD2018", "DXF", "0", "1", filename],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            generated = next(output_dir.rglob("*.dxf"), None)
            if completed.returncode != 0 or generated is None:
                raise ValueError("ODA File Converter could not create a DXF")
            return generated.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", default=os.environ.get("DWG_CONVERTER_BRIDGE_TOKEN", ""))
    parser.add_argument("--oda-exe", type=Path, default=DEFAULT_ODA)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--max-bytes", type=int, default=100_000_000)
    args = parser.parse_args()
    if len(args.token) < 32:
        raise SystemExit("Use a random DWG_CONVERTER_BRIDGE_TOKEN of at least 32 characters.")
    if not args.oda_exe.is_file():
        raise SystemExit(f"ODA File Converter not found: {args.oda_exe}")
    server = OdaBridgeServer((args.host, args.port), token=args.token, executable=args.oda_exe, max_bytes=args.max_bytes)
    print(f"ODA bridge ready on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
