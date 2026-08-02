#!/usr/bin/env bash
# Claude CLI wrapper for Savi / agent workflows.
#
# Usage:
#   claude-cli.sh "<prompt>"
#   claude-cli.sh --file prompt.txt [system_prompt_file]
#   claude-cli.sh --stdin
#   claude-cli.sh prompt.txt [system_prompt_file]   # legacy positional file form
#
# Env overrides (used by wiki / feature / architecture agents):
#   SAVI_CLI_WORKDIR       — cd here and --add-dir
#   SAVI_CLI_ADD_DIR       — extra --add-dir (can differ from workdir)
#   SAVI_CLI_ALLOWED_TOOLS — default Bash,Read,Grep,WebSearch,Edit,Write
#   SAVI_CLI_MAX_TURNS     — optional --max-turns N
#   SAVI_CLI_PERMISSION_MODE — default acceptEdits
#   SAVI_CLI_NO_DEFAULT_SYSTEM=1 — skip savi/system.txt when no system file given
#
# Requires ANTHROPIC_API_KEY (or prior `claude` auth). See backend/.env.example.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../common/savi_prompts.sh
source "$SCRIPT_DIR/../common/savi_prompts.sh"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  BACKEND_ENV="$(cd "$SCRIPT_DIR/../../.." && pwd)/.env"
  if [ -f "$BACKEND_ENV" ]; then
    ANTHROPIC_API_KEY="$(grep -E '^ANTHROPIC_API_KEY=' "$BACKEND_ENV" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//')"
    export ANTHROPIC_API_KEY
  fi
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Error: ANTHROPIC_API_KEY is not set. Export it or load backend/.env before running." >&2
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "Error: claude CLI not found on PATH." >&2
  exit 127
fi

PROMPT=""
SYSTEM_FILE=""
WORKDIR="${SAVI_CLI_WORKDIR:-}"
ADD_DIR="${SAVI_CLI_ADD_DIR:-}"
ALLOWED_TOOLS="${SAVI_CLI_ALLOWED_TOOLS:-Bash,Read,Grep,WebSearch,Edit,Write}"
PERMISSION_MODE="${SAVI_CLI_PERMISSION_MODE:-acceptEdits}"
MAX_TURNS="${SAVI_CLI_MAX_TURNS:-}"

if [[ "${1:-}" == "--file" ]]; then
  FILE="${2:?prompt file required}"
  SYSTEM_FILE="${3:-}"
  [[ -f "$FILE" ]] || { echo "Error: Prompt file not found: $FILE" >&2; exit 1; }
  PROMPT="$(cat "$FILE")"
elif [[ "${1:-}" == "--stdin" ]]; then
  PROMPT="$(cat)"
  SYSTEM_FILE="${2:-}"
elif [[ $# -ge 1 && -f "${1}" && "${1}" != -* ]]; then
  PROMPT="$(cat "$1")"
  SYSTEM_FILE="${2:-}"
elif [[ $# -ge 1 ]]; then
  PROMPT="$1"
  SYSTEM_FILE="${2:-}"
else
  echo "Usage: $0 \"<prompt>\" | $0 --file prompt.txt [system.txt] | $0 --stdin" >&2
  exit 1
fi

if [[ -z "${PROMPT// }" ]]; then
  echo "Error: empty prompt" >&2
  exit 1
fi

SYSTEM_PROMPT=""
if [[ -n "$SYSTEM_FILE" && -f "$SYSTEM_FILE" ]]; then
  SYSTEM_PROMPT="$(cat "$SYSTEM_FILE")"
elif [[ "${SAVI_CLI_NO_DEFAULT_SYSTEM:-}" != "1" ]]; then
  SYSTEM_PROMPT="$(savi_system_prompt || true)"
fi

ADD_DIR_ARGS=()
if [[ -n "$ADD_DIR" && -d "$ADD_DIR" ]]; then
  ADD_DIR_ARGS+=(--add-dir "$ADD_DIR")
fi
if [[ -n "$WORKDIR" && -d "$WORKDIR" ]]; then
  # Avoid duplicate --add-dir when workdir == add_dir
  if [[ "$WORKDIR" != "$ADD_DIR" ]]; then
    ADD_DIR_ARGS+=(--add-dir "$WORKDIR")
  fi
elif [[ -z "$ADD_DIR" && -d temp_store ]]; then
  ADD_DIR_ARGS+=(--add-dir temp_store)
fi

ARGS=(
  -p "$PROMPT"
  --allowedTools "$ALLOWED_TOOLS"
  --permission-mode "$PERMISSION_MODE"
)
if [[ -n "$SYSTEM_PROMPT" ]]; then
  ARGS+=(--append-system-prompt "$SYSTEM_PROMPT")
fi
if [[ -n "$MAX_TURNS" ]]; then
  ARGS+=(--max-turns "$MAX_TURNS")
fi
ARGS+=("${ADD_DIR_ARGS[@]}")

if [[ -n "$WORKDIR" && -d "$WORKDIR" ]]; then
  cd "$WORKDIR"
fi

exec claude "${ARGS[@]}"
