#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required to build Bitwarden Autofiller." >&2
    exit 1
fi

uv build
