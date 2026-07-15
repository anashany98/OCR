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

# CR9: Write permission healthcheck — verify that the appuser can
# actually write to the data directories before starting the worker.
# This catches permission issues early instead of failing mid-OCR.
_healthcheck_write() {
    local dir="$1"
    if [ -d "$dir" ]; then
        local testfile="${dir}/.healthcheck_$$"
        if touch "$testfile" 2>/dev/null; then
            rm -f "$testfile"
        else
            echo "entrypoint: WARNING — cannot write to $dir (fixing permissions)" >&2
            chown -R "${APP_UID}:${APP_GID}" "$dir" 2>/dev/null || true
        fi
    fi
}

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
    # The mount root can already belong to appuser while cache directories
    # created by an older root-run worker remain below it.  Those stale
    # ``*_pages`` directories make PDF rendering fail with EACCES.  Inspect a
    # shallow directory tree as a cheap startup check; only recurse when a
    # repair is actually needed.
    nested_wrong_owner="$(find "$d" -xdev -maxdepth 3 -type d ! -uid "$APP_UID" -print -quit 2>/dev/null)"
    if [ "$current_uid" != "$APP_UID" ] || [ -n "$nested_wrong_owner" ]; then
        # ``--no-dereference`` keeps symlinks intact (the docs already
        # have hardlink/auto strategies that may create them).
        chown -R --no-dereference "${APP_UID}:${APP_GID}" "$d" 2>/dev/null || true
        echo "entrypoint: chowned $d -> ${APP_UID}:${APP_GID}" >&2
    fi
done

# CR9: Verify write permissions after chown.
for d in /app/data/files /app/data/input /app/data/output; do
    _healthcheck_write "$d"
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
