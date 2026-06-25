#!/bin/sh
# H-2 entrypoint: when /app/data/files or /app/data/input are owned by
# root (the typical case on Windows Docker Desktop bind-mounts), chown
# them to the non-root ``appuser`` before the worker / watcher starts.
# Idempotent: a no-op when the dirs are already correct, and a quick
# ``stat`` instead of a full ``find`` so it stays fast on large volumes.
#
# Runs as root (the ENTRYPOINT in the image runs before the USER
# directive) and then ``exec gosu appuser:appuser "$@"`` drops
# privileges so the actual worker / uvicorn process is non-root.
set -e

APP_UID="${APP_UID:-10001}"
APP_GID="${APP_GID:-10001}"

for d in /app/data/files /app/data/input /app/data/output; do
    # Skip if the directory does not exist (some images do not declare
    # all three; the worker-fast image, for example, does not mount
    # /app/data/output).
    if [ ! -d "$d" ]; then
        continue
    fi
    # ``stat -c`` is GNU; BSD stat uses ``-f %u``. The python:3.11-slim
    # and nvidia/cuda bases both ship the GNU variant.
    current_uid="$(stat -c %u "$d" 2>/dev/null || echo 0)"
    if [ "$current_uid" != "$APP_UID" ]; then
        # ``--no-dereference`` keeps symlinks intact (the docs already
        # have hardlink/auto strategies that may create them).
        chown -R --no-dereference "${APP_UID}:${APP_GID}" "$d" 2>/dev/null || true
        echo "entrypoint: chowned $d -> ${APP_UID}:${APP_GID}" >&2
    fi
done

# Now exec the original CMD as the non-root appuser. ``gosu`` is a
# 1 MB setuid-wrapper; ``exec`` replaces the shell so the entrypoint
# is PID 1 and receives signals (SIGTERM, etc.) correctly. If the
# compose file has its own ``user:`` directive that already lands on
# the right UID, ``gosu`` is a no-op (it refuses to downgrade).
if [ "$(id -u)" = "0" ]; then
    exec gosu "${APP_UID}:${APP_GID}" "$@"
else
    exec "$@"
fi
