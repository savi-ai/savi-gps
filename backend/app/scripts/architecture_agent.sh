#!/usr/bin/env bash
# Shim: moved to scripts/agents/architecture_agent.sh
exec "$(cd "$(dirname "$0")" && pwd)/agents/architecture_agent.sh" "$@"
