#!/bin/sh
# Install DeepSeek Harness (dsh) for the current user, without root.
#
# DeepSeek Harness is a plugin-based agent framework distributed as the
# npm package @deepseek-ai/dsh. This script installs it into a per-user
# npm prefix (default: ~/.local) so the `dsh` command lands on PATH at
# $PREFIX/bin/dsh.
set -eu

PREFIX="${DSH_PREFIX:-$HOME/.local}"

if ! command -v npm >/dev/null 2>&1; then
    echo "error: npm is required; install Node.js (>= 18) first" >&2
    exit 1
fi

npm install -g --prefix "$PREFIX" @deepseek-ai/dsh

echo "installed: $PREFIX/bin/dsh ($("$PREFIX/bin/dsh" --version))"

case ":$PATH:" in
    *":$PREFIX/bin:"*) ;;
    *) echo "note: $PREFIX/bin is not on PATH; add it to your shell profile" ;;
esac
