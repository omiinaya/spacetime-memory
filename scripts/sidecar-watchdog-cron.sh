#!/usr/bin/env bash
# Called from cron to run the sidecar health watchdog every minute.
# Example crontab entry:
#   * * * * * $HOME/spacetime-memory/scripts/sidecar-watchdog-cron.sh
#
# Logs warnings to stderr which systemd/cron captures.
# Exit code: 0 = healthy, 1 = one or more sidecars down.
#
# For no_agent cron delivery, the script's stdout is sent as the
# message when it exits non-zero.

set -euo pipefail

PROJECT_DIR="$HOME/spacetime-memory"
cd "${PROJECT_DIR}"

# Run the watchdog with standard output (only failures printed to stderr)
python3 scripts/sidecar_watchdog.py 2>&1

rc=$?

# If down, deliver a concise alert
if [ $rc -ne 0 ]; then
    echo ""
    echo "⚠️ Embedder or Tantivy sidecar is DOWN!"
    echo ""
    echo "Check status with:"
    echo "  systemctl status embedder-sidecar.service"
    echo "  systemctl status tantivy-sidecar.service"
    echo ""
    echo "Journal logs:"
    echo "  journalctl -u embedder-sidecar.service -n 20 --no-pager"
    echo "  journalctl -u tantivy-sidecar.service -n 20 --no-pager"
fi

exit $rc
