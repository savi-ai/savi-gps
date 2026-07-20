#!/bin/bash
# Requires ANTHROPIC_API_KEY in the environment (never hardcode keys).
: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY in your environment}"
export ANTHROPIC_API_KEY

DIR="scripts/temp_store/$1"
mkdir $DIR

FEATURES_JSON="$DIR/features_result.json"

PROMPT="
Analyze the idea and conversation history: 
 ### Idea and Conversation History ###

$2

###

Goal: Based on the above conversation, define the features\n
You should come up with features/requirements based on the idea and conversation history\n
You should only recommend and not generate the code.\n
\n
Use the below schema to come up with features.

SCHEMA (summary_json): 
each feature should have title, description, business_value, actors, high_level_flow, acceptance_criteria (with highlevel positive and negative scenarios)


Constraints: Do NOT modify files or run networked commands. Prefer high precision over speculation.\n
Write your final answer as a JSON object with exactly two top‑level keys:\n
- summary_json: <object conforming to SCHEMA>\n
- report_md: <a concise but executive‑friendly Markdown report>

The file name should features_result.json

OUTPUT: Write the analysis result files in $DIR folder as features_result.json \n\n
When the analysis is started, create a file called FEATURES_STARTED in $DIR folder.\n
When the analysis is completed, create a file called FEATURES_COMPLETED in $DIR folder.\n
When the analysis is failed, create a file called FEATURES_FAILED in $DIR folder.\n\n"

CLAUDE_SYSTEM="You are a Lead Product Manager. Your job is to look at the idea and conversion history about the idea and come up with requirements. \n
Do not create any new code\n
Use only safe read/search actions. \nIf unsure, state assumptions. \n
Return STRICT JSON and a Markdown report."

claude -p "$PROMPT" \
  --append-system-prompt "$CLAUDE_SYSTEM$"\
  --allowedTools "Bash,Read,Grep,WebSearch" \
  --add-dir analysis \
  --permission-mode acceptEdits \
  --max-turns 20