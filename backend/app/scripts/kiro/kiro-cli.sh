#!/usr/bin/env bash
# Programmatic Kiro CLI wrapper for Savi / automation.
#
# Usage:
#   kiro-cli.sh "<prompt>"
#   kiro-cli.sh --file /path/to/prompt.txt
#
# Prefers `kiro-cli chat --no-interactive --trust-all-tools`.
# Falls back to `kiro --print` when kiro-cli is absent.
# Shared Savi prompts: ../prompts/savi/

set -euo pipefail

PROMPT=""
if [[ "${1:-}" == "--file" ]]; then
  FILE="${2:?prompt file required}"
  [[ -f "$FILE" ]] || { echo "Error: prompt file not found: $FILE" >&2; exit 1; }
  PROMPT="$(cat "$FILE")"
elif [[ $# -ge 1 ]]; then
  PROMPT="$1"
else
  echo "Usage: $0 \"<prompt>\" | $0 --file prompt.txt" >&2
  exit 1
fi

if [[ -z "${PROMPT// }" ]]; then
  echo "Error: empty prompt" >&2
  exit 1
fi

WORKDIR="${SAVI_CLI_WORKDIR:-}"
if [[ -n "$WORKDIR" && -d "$WORKDIR" ]]; then
  cd "$WORKDIR"
fi

if command -v kiro-cli >/dev/null 2>&1; then
  exec kiro-cli chat --no-interactive --trust-all-tools "$PROMPT"
fi

if command -v kiro >/dev/null 2>&1; then
  exec kiro --print "$PROMPT"
fi

echo "Error: neither kiro-cli nor kiro found on PATH." >&2
exit 127
