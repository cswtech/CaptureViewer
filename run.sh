#!/usr/bin/env bash
# Run CaptureViewer directly from the source tree (no install needed).
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m captureviewer "$@"
