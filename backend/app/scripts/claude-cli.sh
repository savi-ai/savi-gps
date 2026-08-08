#!/usr/bin/env bash
# Shim: claude-cli.sh moved to scripts/claude/claude-cli.sh
exec "$(cd "$(dirname "$0")" && pwd)/claude/claude-cli.sh" "$@"
