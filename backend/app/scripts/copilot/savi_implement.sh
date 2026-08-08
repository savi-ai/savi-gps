#!/usr/bin/env bash
# Savi implement via Copilot CLI — uses shared prompts/savi/implement.txt
#
# Usage:
#   savi_implement.sh "<title>" <workdir> [plan_relpath] [short_id]
#   savi_implement.sh --file prompt.txt <workdir>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../common/savi_prompts.sh
source "$SCRIPT_DIR/../common/savi_prompts.sh"

if ! command -v copilot >/dev/null 2>&1; then
  echo "Error: copilot CLI not found on PATH." >&2
  exit 127
fi

if [[ "${1:-}" == "--file" ]]; then
  FILE="${2:?prompt file required}"
  WORKDIR="${3:?workdir required}"
  [[ -f "$FILE" ]] || { echo "Error: prompt file not found: $FILE" >&2; exit 1; }
  [[ -d "$WORKDIR" ]] || { echo "Error: workdir not found: $WORKDIR" >&2; exit 1; }
  PROMPT="$(cat "$FILE")"
  cd "$WORKDIR"
  exec copilot -p "$PROMPT" --allow-all-tools -s
fi

TITLE="${1:?title required}"
WORKDIR="${2:?workdir required}"
PLAN_REL="${3:-.savi/work/PLAN.md}"
SHORT_ID="${4:-work}"

[[ -d "$WORKDIR" ]] || { echo "Error: workdir not found: $WORKDIR" >&2; exit 1; }

SYSTEM="$(savi_system_prompt || true)"
BODY="$(savi_build_implement_prompt "$TITLE" "$PLAN_REL" "$SHORT_ID")"
PROMPT="${SYSTEM}

${BODY}"

cd "$WORKDIR"
exec copilot -p "$PROMPT" --allow-all-tools -s
