#!/usr/bin/env bash
# Savi implement via Claude CLI — uses shared prompts/savi/implement.txt
#
# Usage:
#   savi_implement.sh "<title>" <workdir> [plan_relpath] [short_id]
#   savi_implement.sh --file prompt.txt <workdir>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../common/savi_prompts.sh
source "$SCRIPT_DIR/../common/savi_prompts.sh"
CLI="$SCRIPT_DIR/claude-cli.sh"

if [[ "${1:-}" == "--file" ]]; then
  FILE="${2:?prompt file required}"
  WORKDIR="${3:?workdir required}"
  export SAVI_CLI_WORKDIR="$WORKDIR"
  exec "$CLI" --file "$FILE" "$SAVI_PROMPTS_DIR/system.txt"
fi

TITLE="${1:?title required}"
WORKDIR="${2:?workdir required}"
PLAN_REL="${3:-.savi/work/PLAN.md}"
SHORT_ID="${4:-work}"

[[ -d "$WORKDIR" ]] || { echo "Error: workdir not found: $WORKDIR" >&2; exit 1; }

PROMPT="$(savi_build_implement_prompt "$TITLE" "$PLAN_REL" "$SHORT_ID")"
export SAVI_CLI_WORKDIR="$WORKDIR"
exec "$CLI" "$PROMPT" "$SAVI_PROMPTS_DIR/system.txt"
