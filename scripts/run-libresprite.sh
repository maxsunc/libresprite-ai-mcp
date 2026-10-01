#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${LIBRESPRITE_BUILD_DIR:-$ROOT/build/libresprite}"
EXECUTABLE="$BUILD_DIR/bin/libresprite"

if [[ ! -x "$EXECUTABLE" ]]; then
  echo "LibreSprite is not built. Run bash scripts/build-libresprite.sh first." >&2
  exit 1
fi

exec "$EXECUTABLE" "$@"
