#!/usr/bin/env bash
# Feature Agent — idea/conversation → features_result.json
#
# Usage: feature_agent.sh <project_or_run_id> "<conversation text>"
#
# Prompts: scripts/prompts/agents/feature/{system,task}.txt
# CLI: AGENT_CLI=claude|copilot|kiro (default claude)

set -euo pipefail

PROJECT_ID="${1:?project/run id required}"
CONVERSATION="${2:?conversation text required}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROMPTS_DIR="$SCRIPTS_ROOT/prompts/agents/feature"

# Prefer scripts/temp_store (legacy relative path was scripts/temp_store from CWD)
DIR="${FEATURE_OUTPUT_DIR:-$SCRIPTS_ROOT/temp_store/$PROJECT_ID}"
mkdir -p "$DIR"

# shellcheck source=../common/savi_prompts.sh
source "$SCRIPTS_ROOT/common/savi_prompts.sh"
# shellcheck source=../common/agent_cli.sh
source "$SCRIPTS_ROOT/common/agent_cli.sh"
SAVI_PROMPTS_DIR="$PROMPTS_DIR"

BACKEND_ENV="$(cd "$SCRIPTS_ROOT/../.." && pwd)/.env"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$BACKEND_ENV" ]; then
  ANTHROPIC_API_KEY="$(grep -E '^ANTHROPIC_API_KEY=' "$BACKEND_ENV" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//')"
  export ANTHROPIC_API_KEY
fi

if [[ "$(agent_cli_vendor)" == "claude" ]]; then
  : "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY in your environment}"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
printf '%s' "$CONVERSATION" > "$TMP_DIR/conversation.txt"

PROMPT="$(
  savi_render_prompt task.txt \
    --var "DIR=$DIR" \
    --file-var "CONVERSATION=$TMP_DIR/conversation.txt" \
    --max-file-bytes 200000
)"

export SAVI_CLI_ADD_DIR="$DIR"
export SAVI_CLI_ALLOWED_TOOLS="${SAVI_CLI_ALLOWED_TOOLS:-Bash,Read,Grep,WebSearch}"
export SAVI_CLI_MAX_TURNS="${SAVI_CLI_MAX_TURNS:-20}"
export SAVI_CLI_NO_DEFAULT_SYSTEM=1

agent_cli_run "$PROMPT" "$PROMPTS_DIR/system.txt"
