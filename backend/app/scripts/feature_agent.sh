#!/usr/bin/env bash
# Shim: moved to scripts/agents/feature_agent.sh
exec "$(cd "$(dirname "$0")" && pwd)/agents/feature_agent.sh" "$@"
