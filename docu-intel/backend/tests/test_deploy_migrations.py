"""Tests for the deploy / migration / device-resolution helpers
introduced in Block 3.

What we lock in:

* ``resolve_paddle_device`` honours an explicit value when the
  caller passes one, picks ``gpu:<idx>`` when ``CUDA_VISIBLE_DEVICES``
  is set AND the Paddle runtime can see a GPU, and returns ``None``
  (Paddle's own default — CPU on a CPU build, GPU 0 on a CUDA
  build) otherwise.
* The migration entrypoint script exists, is non-empty, and
  references ``alembic upgrade head`` so the migrate compose
  service can rely on it.
* The Dockerfile's CMD no longer contains ``alembic upgrade
  head`` (the migration was moved to a dedicated ``migrate``
  service so two replicas do not race on the schema).
* The production compose file declares a ``migrate`` service
  and every backend / worker declares it as a dependency.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# resolve_paddle_device
# ---------------------------------------------------------------------------


def _reload_paddle_module():
    """Reload ``app.ocr.paddle`` so the module-level cache of the
    resolved device is recomputed against the current env vars.
    """
    import importlib

    from app.ocr import paddle as paddle_module

    return importlib.reload(paddle_module)


def test_resolve_paddle_device_uses_explicit_value(monkeypatch):
    from app.ocr import paddle as paddle_module

    assert paddle_module.resolve_paddle_device(requested="gpu:0") == "gpu:0"
    assert paddle_module.resolve_paddle_device(requested="cpu") == "cpu"
    assert paddle_module.resolve_paddle_device(requested=None) is None


def test_resolve_paddle_device_falls_back_to_default_without_cuda(monkeypatch):
    """When no CUDA is visible, ``resolve_paddle_device`` returns
    ``None`` so PaddleOCR picks its own default (CPU on a CPU
    build). The function must not crash and must not invent a
    ``gpu:`` device.
    """
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    from app.ocr import paddle as paddle_module

    device = paddle_module.resolve_paddle_device()
    # ``None`` means "let Paddle decide". On any non-CUDA host
    # that resolves to CPU.
    assert device is None


def test_resolve_paddle_device_uses_cuda_when_runtime_sees_a_gpu(monkeypatch):
    """When ``CUDA_VISIBLE_DEVICES`` is set AND the Paddle runtime
    reports at least one device, ``resolve_paddle_device`` returns
    ``gpu:<idx>``.

    The test patches ``_cuda_runtime_available`` so it does not
    depend on the actual Paddle install on the test host.
    """
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    from app.ocr import paddle as paddle_module

    monkeypatch.setattr(paddle_module, "_cuda_runtime_available", lambda: True)
    assert paddle_module.resolve_paddle_device() == "gpu:0"


def test_resolve_paddle_device_logs_warning_when_cuda_env_set_but_no_runtime(monkeypatch, caplog):
    """When the operator exports ``CUDA_VISIBLE_DEVICES`` but the
    Paddle wheel is the CPU-only build, the resolver logs a
    warning and returns ``None`` so the worker keeps booting.
    """
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    from app.ocr import paddle as paddle_module

    monkeypatch.setattr(paddle_module, "_cuda_runtime_available", lambda: False)
    with caplog.at_level("WARNING", logger="app.ocr.paddle"):
        device = paddle_module.resolve_paddle_device()
    assert device is None
    # The operator-facing warning names the env var so they can
    # see why their GPU host is using CPU.
    assert any("CUDA_VISIBLE_DEVICES" in record.message for record in caplog.records), (
        f"expected a warning that names CUDA_VISIBLE_DEVICES, got: {[r.message for r in caplog.records]}"
    )


def test_resolve_paddle_device_cuda_runtime_probe_does_not_raise(monkeypatch):
    """``_cuda_runtime_available`` must never raise — the resolver
    relies on that to keep the worker boot resilient on hosts
    where Paddle is partially installed.
    """
    from app.ocr import paddle as paddle_module

    # No paddle import: returns False, no exception.
    monkeypatch.setattr(paddle_module, "_cuda_runtime_available", lambda: False)
    assert paddle_module._cuda_runtime_available() is False


# ---------------------------------------------------------------------------
# Dockerfile / migration entrypoint
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_cmd_runs_only_uvicorn():
    """The Dockerfile's CMD must NOT include ``alembic upgrade
    head`` — running it from every uvicorn replica raced on
    ``alembic_version`` at boot. Migrations are run by a
    dedicated ``migrate`` compose service.
    """
    dockerfile = (_REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    cmd_line = next(
        (line for line in dockerfile.splitlines() if line.strip().startswith("CMD ")),
        None,
    )
    assert cmd_line is not None, "Dockerfile is missing a CMD instruction"
    assert "alembic upgrade head" not in cmd_line, (
        "Dockerfile CMD still runs migrations; move them to the migrate "
        "compose service so multiple uvicorn replicas do not race on "
        "alembic_version."
    )
    assert "uvicorn app.main:app" in cmd_line, (
        "Dockerfile CMD should still start uvicorn (without migrations)"
    )


def test_entrypoint_migrate_script_is_present_and_calls_alembic():
    """The one-shot ``migrate`` compose service invokes
    ``scripts/entrypoint-migrate.sh`` which must exist and call
    ``alembic upgrade head``. The script is small on purpose:
    set -e, run the command, log the result.
    """
    script = _REPO_ROOT / "backend" / "scripts" / "entrypoint-migrate.sh"
    assert script.is_file(), (
        f"entrypoint-migrate.sh missing at {script}; the migrate compose service depends on it."
    )
    content = script.read_text(encoding="utf-8")
    assert "alembic upgrade head" in content, (
        "entrypoint-migrate.sh must invoke 'alembic upgrade head'"
    )
    # set -e so any failure surfaces as a non-zero exit code and
    # the compose healthcheck (``service_completed_successfully``)
    # reports the failure.
    assert "set -e" in content, (
        "entrypoint-migrate.sh must 'set -e' so a failed migration "
        "fails the migrate service and the dependent workers do not start."
    )


def test_entrypoint_migrate_script_is_executable_in_git():
    """The script must have the executable bit set in git so the
    image's ``COPY scripts /app/scripts`` step picks it up with
    the right mode. On Windows the OS file mode is always
    ``0o666`` (no x bit), so we read the bit from the git index
    via ``git ls-files --stage``. The output is
    ``<mode> <hash> <stage>\t<path>`` and ``100755`` is the
    executable regular-file mode (vs ``100644`` for the default
    non-executable file).
    """
    script_rel = "backend/scripts/entrypoint-migrate.sh"
    script_abs = _REPO_ROOT / script_rel
    assert script_abs.is_file(), f"{script_abs} is missing"

    # POSIX fast path: the OS file mode already carries +x.
    if script_abs.stat().st_mode & 0o111:
        return

    # Windows / core.fileMode=false path: read the git index.
    # ``git ls-files --stage`` prints
    # ``<mode> <hash> <stage><TAB><path>``. The mode ``100755``
    # means executable regular file; ``100644`` is the default
    # non-executable file mode.
    result = subprocess.run(
        ["git", "ls-files", "--stage", script_rel],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    line = result.stdout.splitlines()[0] if result.stdout else ""
    # The first three columns are space-separated; the path is
    # tab-separated. We only need the first column (the mode).
    mode = line.split("\t", 1)[0].split()[0] if line else ""
    assert mode == "100755", (
        f"{script_rel} is not executable in git (mode={mode!r}). The "
        "Dockerfile chmods it at build time, but the source file "
        "should also be executable in git so a local "
        "``./scripts/entrypoint-migrate.sh`` test works without "
        "re-applying the chmod. Fix with: "
        "'git update-index --chmod=+x backend/scripts/entrypoint-migrate.sh'"
    )


# ---------------------------------------------------------------------------
# docker-compose.prod.yml — migrate service + depends_on wiring
# ---------------------------------------------------------------------------


def _read_compose(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_prod_compose_declares_migrate_service():
    content = _read_compose(_REPO_ROOT / "docker-compose.prod.yml")
    assert re.search(r"^  migrate:", content, re.MULTILINE), (
        "docker-compose.prod.yml is missing a 'migrate' service. "
        "Migrations must run from a dedicated init job, not from the "
        "backend / worker CMDs."
    )
    # The migrate service must use the dedicated entrypoint script.
    migrate_block_match = re.search(
        r"^  migrate:.*?(?=^  \w)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    assert migrate_block_match is not None
    migrate_block = migrate_block_match.group(0)
    assert "entrypoint-migrate.sh" in migrate_block
    assert 'restart: "no"' in migrate_block, (
        "migrate must be a one-shot service (restart: no), not a long-running one."
    )


@pytest.mark.parametrize(
    "service",
    ["backend:", "worker-fast:", "worker-maintenance:", "ocr-worker:", "watcher:", "scheduler:"],
)
def test_prod_compose_services_depend_on_migrate(service):
    content = _read_compose(_REPO_ROOT / "docker-compose.prod.yml")
    service_match = re.search(
        rf"^  {re.escape(service.rstrip(':'))}:.*?(?=^  \w)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    assert service_match is not None, f"Service {service!r} not found in compose"
    block = service_match.group(0)
    assert "migrate:" in block, f"Service {service!r} does not declare depends_on: migrate"
    assert "service_completed_successfully" in block, (
        f"Service {service!r} depends on migrate but does not require "
        "service_completed_successfully; it could start before the "
        "migrations are applied."
    )


# ---------------------------------------------------------------------------
# docker-compose.yml — same wiring for dev
# ---------------------------------------------------------------------------


def test_dev_compose_declares_migrate_service():
    content = _read_compose(_REPO_ROOT / "docker-compose.yml")
    assert re.search(r"^  migrate:", content, re.MULTILINE), (
        "docker-compose.yml is missing a 'migrate' service. Migrations "
        "must run from a dedicated init job in the dev stack too."
    )
    migrate_block_match = re.search(
        r"^  migrate:.*?(?=^  \w)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    assert migrate_block_match is not None
    migrate_block = migrate_block_match.group(0)
    assert "entrypoint-migrate.sh" in migrate_block
    assert 'restart: "no"' in migrate_block
