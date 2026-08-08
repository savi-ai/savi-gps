#!/usr/bin/env bash
# Resolve which vendor CLI wrapper to use for GPS agent scripts.
# Default: claude. Override with AGENT_CLI=claude|copilot|kiro
#
# shellcheck shell=bash

_AGENT_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_SCRIPTS_ROOT="$(cd "$_AGENT_COMMON_DIR/.." && pwd)"

agent_cli_vendor() {
  echo "${AGENT_CLI:-claude}" | tr '[:upper:]' '[:lower:]'
}

agent_cli_path() {
  local vendor
  vendor="$(agent_cli_vendor)"
  case "$vendor" in
    claude) echo "$_SCRIPTS_ROOT/claude/claude-cli.sh" ;;
    copilot) echo "$_SCRIPTS_ROOT/copilot/copilot-cli.sh" ;;
    kiro) echo "$_SCRIPTS_ROOT/kiro/kiro-cli.sh" ;;
    *)
      echo "Error: unknown AGENT_CLI=$vendor (use claude|copilot|kiro)" >&2
      return 1
      ;;
  esac
}

# Run vendor CLI with prompt + optional system file.
# Claude supports system file as 2nd arg; Copilot/Kiro prepend system into prompt.
agent_cli_run() {
  local prompt="$1"
  local system_file="${2:-}"
  local cli
  cli="$(agent_cli_path)"
  [[ -x "$cli" || -f "$cli" ]] || { echo "Error: CLI wrapper missing: $cli" >&2; return 127; }

  local vendor
  vendor="$(agent_cli_vendor)"
  if [[ "$vendor" == "claude" ]]; then
    if [[ -n "$system_file" && -f "$system_file" ]]; then
      "$cli" "$prompt" "$system_file"
    else
      SAVI_CLI_NO_DEFAULT_SYSTEM=1 "$cli" "$prompt"
    fi
    return $?
  fi

  # Copilot / Kiro: fold system prompt into the user prompt
  local full="$prompt"
  if [[ -n "$system_file" && -f "$system_file" ]]; then
    full="$(cat "$system_file")

$prompt"
  fi
  "$cli" "$full"
}
