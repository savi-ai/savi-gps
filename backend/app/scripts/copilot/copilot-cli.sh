#!/usr/bin/env bash
# Programmatic GitHub Copilot CLI wrapper for Savi / automation.
#
# Usage:
#   copilot-cli.sh "<prompt>"
#   copilot-cli.sh --file /path/to/prompt.txt
#   echo "prompt" | copilot-cli.sh --stdin
#
# Auth: COPILOT_GITHUB_TOKEN | GH_TOKEN | GITHUB_TOKEN  or  `copilot login`
# Shared Savi prompts: ../prompts/savi/
#
# Docs:
#   https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli
#   https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference

set -euo pipefail

if ! command -v copilot >/dev/null 2>&1; then
  echo "Error: copilot CLI not found on PATH. Install GitHub Copilot CLI first." >&2
  exit 127
fi

PROMPT=""
if [[ "${1:-}" == "--file" ]]; then
  FILE="${2:?prompt file required}"
  [[ -f "$FILE" ]] || { echo "Error: prompt file not found: $FILE" >&2; exit 1; }
  PROMPT="$(cat "$FILE")"
elif [[ "${1:-}" == "--stdin" ]]; then
  PROMPT="$(cat)"
elif [[ $# -ge 1 ]]; then
  PROMPT="$1"
else
  echo "Usage: $0 \"<prompt>\" | $0 --file prompt.txt | $0 --stdin" >&2
  exit 1
fi

if [[ -z "${PROMPT// }" ]]; then
  echo "Error: empty prompt" >&2
  exit 1
fi

# -p programmatic, --allow-all-tools headless, -s silent (script-friendly)
exec copilot -p "$PROMPT" --allow-all-tools -s
