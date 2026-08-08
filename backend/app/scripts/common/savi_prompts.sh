#!/usr/bin/env bash
# Shared helpers for Savi CLI wrappers (claude / copilot / kiro).
# shellcheck shell=bash

_SAVI_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAVI_SCRIPTS_ROOT="$(cd "$_SAVI_COMMON_DIR/.." && pwd)"
SAVI_PROMPTS_DIR="${SAVI_PROMPTS_DIR:-$SAVI_SCRIPTS_ROOT/prompts/savi}"
SAVI_RENDER="${SAVI_RENDER:-$SAVI_SCRIPTS_ROOT/prompts/render_prompt.py}"

savi_render_prompt() {
  # Usage: savi_render_prompt <template_name> [--var/--file-var ...]
  local name="$1"
  shift
  local template="$SAVI_PROMPTS_DIR/$name"
  if [[ ! -f "$template" ]]; then
    echo "Error: prompt template not found: $template" >&2
    return 1
  fi
  python3 "$SAVI_RENDER" "$template" "$@"
}

savi_system_prompt() {
  if [[ -f "$SAVI_PROMPTS_DIR/system.txt" ]]; then
    cat "$SAVI_PROMPTS_DIR/system.txt"
  fi
}

savi_build_plan_prompt() {
  local title="${1:-}"
  local desc="${2:-}"
  local brief_file="${3:-}"
  local args=(--var "TITLE=$title" --var "DESCRIPTION=$desc")
  if [[ -n "$brief_file" && -f "$brief_file" ]]; then
    args+=(--file-var "BRIEF=$brief_file")
  else
    args+=(--var "BRIEF=")
  fi
  savi_render_prompt plan.txt "${args[@]}"
}

savi_build_implement_prompt() {
  local title="${1:-}"
  local plan_path="${2:-}"
  local short_id="${3:-}"
  savi_render_prompt implement.txt \
    --var "TITLE=$title" \
    --var "PLAN_PATH=$plan_path" \
    --var "SHORT_ID=$short_id"
}
