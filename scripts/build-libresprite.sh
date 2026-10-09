#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${LIBRESPRITE_BUILD_DIR:-$ROOT/build/libresprite}"
# CMake compiler flags are shell-parsed; escape checkouts with spaces/special chars.
printf -v prefix_map '%q' "-ffile-prefix-map=$ROOT=."

for tool in cmake ninja; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. See docs/building.md for build prerequisites." >&2
    exit 1
  fi
done

options=(
  -S "$ROOT/vendor/libresprite"
  -B "$BUILD_DIR"
  -G Ninja
  "-DCMAKE_BUILD_TYPE=${LIBRESPRITE_BUILD_TYPE:-RelWithDebInfo}"
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
  -DCMAKE_DISABLE_FIND_PACKAGE_V8=ON
  "-DCMAKE_C_FLAGS=$prefix_map"
  "-DCMAKE_CXX_FLAGS=$prefix_map"
)

if [[ "$(uname -s)" == Darwin ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required by the upstream macOS build. See docs/building.md." >&2
    exit 1
  fi
  prefix="$(brew --prefix)"
  options+=(
    "-DCMAKE_OSX_ARCHITECTURES=$(uname -m)"
    "-DCMAKE_OSX_SYSROOT=$(xcrun --sdk macosx --show-sdk-path)"
    "-DCMAKE_PREFIX_PATH=$prefix;$prefix/opt/libarchive;$prefix/opt/jpeg-turbo"
  )
  export PKG_CONFIG_PATH="$prefix/lib/pkgconfig:$prefix/share/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi

cmake "${options[@]}" "$@"
cmake --build "$BUILD_DIR" --target libresprite --parallel "${LIBRESPRITE_BUILD_JOBS:-4}"
