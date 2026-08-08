#!/usr/bin/env bash
# Wiki Agent — deep codebase analysis → HTML + Markdown + JSON wiki.
#
# Usage: wiki_agent.sh <org_name> <repo_name> <output_dir> <clone_path> [analysis_config_json_path]
#
# Prompts: scripts/prompts/agents/wiki/{system,task}.txt
#          + app/prompts/wiki_deep_analysis.txt
# CLI: AGENT_CLI=claude|copilot|kiro (default claude)

set -euo pipefail

ORG_NAME="${1:?org name required}"
REPO_NAME="${2:?repo name required}"
OUTPUT_DIR="${3:?output dir required}"
CLONE_PATH="${4:?clone path required}"
CONFIG_JSON="${5:-}"

mkdir -p "$OUTPUT_DIR"

timestamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

echo "$(timestamp)" > "$OUTPUT_DIR/WIKI_STARTED"
rm -f "$OUTPUT_DIR/WIKI_COMPLETED" "$OUTPUT_DIR/WIKI_FAILED"

WIKI_JSON="$OUTPUT_DIR/wiki_result.json"
WIKI_HTML="$OUTPUT_DIR/wiki_site.html"
WIKI_MD="$OUTPUT_DIR/wiki_site.md"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# sample.html stays at scripts/ root (shim-compatible path)
SAMPLE_HTML="$SCRIPTS_ROOT/sample.html"
if [[ ! -f "$SAMPLE_HTML" ]]; then
  SAMPLE_HTML="$SCRIPT_DIR/../sample.html"
fi
DEEP_RULES_PATH="$SCRIPTS_ROOT/../prompts/wiki_deep_analysis.txt"
TEMPLATE_PATH="$SCRIPTS_ROOT/../templates/wiki/wiki_site_template.html"
PROMPTS_DIR="$SCRIPTS_ROOT/prompts/agents/wiki"

# shellcheck source=../common/savi_prompts.sh
source "$SCRIPTS_ROOT/common/savi_prompts.sh"
# shellcheck source=../common/agent_cli.sh
source "$SCRIPTS_ROOT/common/agent_cli.sh"
SAVI_PROMPTS_DIR="$PROMPTS_DIR"

fail() {
  echo "$(timestamp)" > "$OUTPUT_DIR/WIKI_FAILED"
  echo "$1" >> "$OUTPUT_DIR/WIKI_FAILED"
  echo "WIKI_FAILED: $1" >&2
  exit 1
}

BACKEND_ENV="$(cd "$SCRIPTS_ROOT/../.." && pwd)/.env"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$BACKEND_ENV" ]; then
  ANTHROPIC_API_KEY="$(grep -E '^ANTHROPIC_API_KEY=' "$BACKEND_ENV" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//')"
  export ANTHROPIC_API_KEY
fi

# Claude path still needs the key; Copilot/Kiro use their own auth
if [[ "$(agent_cli_vendor)" == "claude" ]]; then
  if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    fail "ANTHROPIC_API_KEY is required for wiki_agent.sh (AGENT_CLI=claude)"
  fi
  if ! command -v claude >/dev/null 2>&1; then
    fail "claude CLI not found on PATH"
  fi
fi

DEEP_RULES=""
if [ -f "$DEEP_RULES_PATH" ]; then
  DEEP_RULES="$(cat "$DEEP_RULES_PATH")"
fi

CONFIG_BLOCK=""
if [ -n "$CONFIG_JSON" ] && [ -f "$CONFIG_JSON" ]; then
  CONFIG_BLOCK="Tenant analysis attributes — extract into wiki_result.json.analysis_attributes:
$(cat "$CONFIG_JSON")"
fi

# Write large fields via temp files for safe substitution
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
printf '%s' "$DEEP_RULES" > "$TMP_DIR/deep_rules.txt"
printf '%s' "$CONFIG_BLOCK" > "$TMP_DIR/config_block.txt"

PROMPT="$(
  savi_render_prompt task.txt \
    --var "CLONE_PATH=$CLONE_PATH" \
    --var "ORG_NAME=$ORG_NAME" \
    --var "REPO_NAME=$REPO_NAME" \
    --var "OUTPUT_DIR=$OUTPUT_DIR" \
    --var "SAMPLE_HTML=$SAMPLE_HTML" \
    --var "TEMPLATE_PATH=$TEMPLATE_PATH" \
    --var "WIKI_JSON=$WIKI_JSON" \
    --var "WIKI_HTML=$WIKI_HTML" \
    --var "WIKI_MD=$WIKI_MD" \
    --file-var "DEEP_RULES=$TMP_DIR/deep_rules.txt" \
    --file-var "CONFIG_BLOCK=$TMP_DIR/config_block.txt" \
    --max-file-bytes 200000
)"

echo "Wiki Agent starting for $ORG_NAME/$REPO_NAME at $(timestamp) (CLI=$(agent_cli_vendor))" >&2

export SAVI_CLI_ADD_DIR="$CLONE_PATH"
export SAVI_CLI_ALLOWED_TOOLS="${SAVI_CLI_ALLOWED_TOOLS:-Bash,Read,Grep}"
export SAVI_CLI_MAX_TURNS="${SAVI_CLI_MAX_TURNS:-40}"
export SAVI_CLI_NO_DEFAULT_SYSTEM=1

set +e
agent_cli_run "$PROMPT" "$PROMPTS_DIR/system.txt"
CLI_EXIT=$?
set -e

if [ "$CLI_EXIT" -ne 0 ]; then
  fail "agent CLI exited with code $CLI_EXIT"
fi

MISSING=""
[ -f "$WIKI_HTML" ] || MISSING="wiki_site.html "
[ -f "$WIKI_MD" ] || MISSING="${MISSING}wiki_site.md "
[ -f "$WIKI_JSON" ] || MISSING="${MISSING}wiki_result.json "

if [ -n "$MISSING" ]; then
  fail "Missing required files: $MISSING"
fi

rm -f "$OUTPUT_DIR/WIKI_STARTED"
echo "$(timestamp)" > "$OUTPUT_DIR/WIKI_COMPLETED"
echo "Wiki artifacts written to $OUTPUT_DIR" >&2
exit 0
