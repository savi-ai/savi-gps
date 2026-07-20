#!/bin/bash

# Claude CLI script for agent workflows.
# Usage: claude-cli.sh <prompt_file> [system_prompt_file]
#
# Requires ANTHROPIC_API_KEY in the environment (see backend/.env.example).

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "Error: ANTHROPIC_API_KEY is not set. Export it or load backend/.env before running."
    exit 1
fi

if [ $# -lt 1 ]; then
    echo "Usage: $0 <prompt_file> [system_prompt_file]"
    exit 1
fi

PROMPT_FILE="$1"
SYSTEM_FILE="${2:-}"

if [ ! -f "$PROMPT_FILE" ]; then
    echo "Error: Prompt file not found: $PROMPT_FILE"
    exit 1
fi

PROMPT=$(cat "$PROMPT_FILE")

if [ -n "$SYSTEM_FILE" ] && [ -f "$SYSTEM_FILE" ]; then
    SYSTEM_PROMPT=$(cat "$SYSTEM_FILE")
    claude -p "$PROMPT" \
      --append-system-prompt "$SYSTEM_PROMPT" \
      --allowedTools "Bash,Read,Grep,WebSearch" \
      --add-dir temp_store \
      --permission-mode acceptEdits
else
    claude -p "$PROMPT" \
      --allowedTools "Bash,Read,Grep,WebSearch" \
      --add-dir temp_store \
      --permission-mode acceptEdits
fi
