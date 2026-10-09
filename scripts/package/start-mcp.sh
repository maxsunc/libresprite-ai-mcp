#!/bin/sh
# GPL-2.0-only. All diagnostics go to stderr; stdout is MCP JSON-RPC only.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NODE=${LIBRESPRITE_NODE:-node}
if ! command -v "$NODE" >/dev/null 2>&1; then
  echo "Node.js 20+ is required. Set LIBRESPRITE_NODE to its absolute executable path." >&2
  exit 1
fi
if ! "$NODE" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; then
  echo "Node.js 20+ is required." >&2
  exit 1
fi
exec "$NODE" "$HERE/dist/index.js" "$@"
