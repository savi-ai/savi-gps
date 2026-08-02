#!/usr/bin/env bash
# Architecture Agent — features JSON → architecture_result.json (React Flow / C4)
#
# Usage: architecture_agent.sh <project_or_run_id>
# Expects features at scripts/temp_store/<id>/features_result.json (or FEATURE_OUTPUT_DIR)
#
# Prompts: scripts/prompts/agents/architecture/{system,task}.txt
# CLI: AGENT_CLI=claude|copilot|kiro (default claude)

set -euo pipefail

PROJECT_ID="${1:?project/run id required}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROMPTS_DIR="$SCRIPTS_ROOT/prompts/agents/architecture"

DIR="${FEATURE_OUTPUT_DIR:-$SCRIPTS_ROOT/temp_store/$PROJECT_ID}"
mkdir -p "$DIR"

FEATURES_JSON="$DIR/features_result.json"
ARCHITECTURE_JSON="$DIR/architecture_result.json"

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

PROMPT="$(
  savi_render_prompt task.txt \
    --var "PROJECT_NAME=$PROJECT_ID" \
    --var "DIR=$DIR" \
    --var "FEATURES_JSON=$FEATURES_JSON" \
    --var "ARCHITECTURE_JSON=$ARCHITECTURE_JSON"
)"

export SAVI_CLI_ADD_DIR="$DIR"
export SAVI_CLI_ALLOWED_TOOLS="${SAVI_CLI_ALLOWED_TOOLS:-Bash,Read,Grep,WebSearch}"
export SAVI_CLI_MAX_TURNS="${SAVI_CLI_MAX_TURNS:-20}"
export SAVI_CLI_NO_DEFAULT_SYSTEM=1

agent_cli_run "$PROMPT" "$PROMPTS_DIR/system.txt"
