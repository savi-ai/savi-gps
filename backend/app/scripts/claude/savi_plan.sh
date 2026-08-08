#!/usr/bin/env bash
# Savi plan via Claude CLI — uses shared prompts/savi/plan.txt
#
# Usage:
#   savi_plan.sh "<title>" "<description>" [context_brief_file]
#   savi_plan.sh --file rendered_prompt.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../common/savi_prompts.sh
source "$SCRIPT_DIR/../common/savi_prompts.sh"
CLI="$SCRIPT_DIR/claude-cli.sh"

if [[ "${1:-}" == "--file" ]]; then
  exec "$CLI" --file "${2:?prompt file required}" "$SAVI_PROMPTS_DIR/system.txt"
fi

TITLE="${1:?title required}"
DESC="${2:-}"
BRIEF_FILE="${3:-}"

PROMPT="$(savi_build_plan_prompt "$TITLE" "$DESC" "$BRIEF_FILE")"
exec "$CLI" "$PROMPT" "$SAVI_PROMPTS_DIR/system.txt"
