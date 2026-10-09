#!/bin/sh
# GPL-2.0-only. No files are changed. --connect explicitly opens/closes a session.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$HERE/start-mcp.sh" --doctor "$@"
