#!/usr/bin/env bash
# Shim: moved to scripts/agents/wiki_agent.sh
exec "$(cd "$(dirname "$0")" && pwd)/agents/wiki_agent.sh" "$@"
