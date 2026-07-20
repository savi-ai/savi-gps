#!/bin/bash
# Requires ANTHROPIC_API_KEY in the environment (never hardcode keys).
: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY in your environment}"
export ANTHROPIC_API_KEY

DIR="scripts/temp_store/$1"
mkdir -p $DIR

ARCHITECTURE_JSON="$DIR/architecture_result.json"
FEATURES_JSON="$DIR/features_result.json"

# Create ARCHITECTURE_STARTED file
# touch "$DIR/ARCHITECTURE_STARTED"

# Write features JSON to file for reference
# echo "$2" > "$FEATURES_JSON"

PROMPT="The recommended requirements/features in JSON format are at: $FEATURES_JSON 
 

Goal: Based on recommended requirements/features, define the architecture\n
You should come up with architecture based on services and other details and the analysis json\n
You should only generate the json to draw architecture on react flow and not generate the code.\n

The architecture should follow C4 model and this JSON should be the first level, context diagram. It should have high level services and not too many components.
\n
Use the below schema to come up with architecture.

SCHEMA (summary_json): {\"project_name\": \"$1\",\"version\": \"1.0\",\"last_updated\": \"\",\"nodes\": [{\"id\": \"string\",\"type\": \"default\",\"position\": {\"x\": number, \"y\": number},\"data\": {\"label\": \"string\",\"description\": \"string\",\"technology\": \"string\"}}],\"edges\": [{\"id\": \"string\",\"source\": \"string\",\"target\": \"string\",\"type\": \"default\",\"label\": \"string\"}]}\n


The nodes are services from the functional requirements in the analysis json\n
The position of node is x, y coordinates in react flow diagram/canvas\n
label and description of nodes are human friendly name and short description.\n
the technology stack should also come from requirements results, if not suggest something\n
the id of node should be some identifier which will be used in edges source and targets\n
The edges are connections from one service to other\n
come up with connections that makes sense in the architecture diagram based on services\n
label of edge is one word details of what the connection is, for eg: routes, calls, notifies, etc

Constraints: Do NOT modify files or run networked commands. Prefer high precision over speculation.\n
Write your final answer as a JSON object with exactly two top‑level keys:\n
- summary_json: <object conforming to SCHEMA>\n
- report_md: <a concise but executive‑friendly Markdown report>

The file name should architecture_result.json

OUTPUT: Write the architecture result files in $DIR folder as architecture_result.json \n\n
When the analysis is started, create a file called ARCHITECTURE_STARTED in $DIR folder.\n
When the analysis is completed, create a file called ARCHITECTURE_COMPLETED in $DIR folder.\n
When the analysis is failed, create a file called ARCHITECTURE_FAILED in $DIR folder.\n\n"

CLAUDE_SYSTEM="You are a Lead Architect. Your job is to look at the requirements and come up with architecture diagram. \n
Do not create any new code\n
Use only safe read/search actions. \nIf unsure, state assumptions. \n
Return STRICT JSON and a Markdown report."

claude -p "$PROMPT" \
  --append-system-prompt "$CLAUDE_SYSTEM"\
  --allowedTools "Bash,Read,Grep,WebSearch" \
  --add-dir analysis \
  --permission-mode acceptEdits \
  --max-turns 20

# Check if architecture_result.json was created
# if [ $? -eq 0 ] && [ -f "$ARCHITECTURE_JSON" ]; then
#     touch "$DIR/ARCHITECTURE_COMPLETED"
#     rm -f "$DIR/ARCHITECTURE_STARTED"
# else
#     touch "$DIR/ARCHITECTURE_FAILED"
#     rm -f "$DIR/ARCHITECTURE_STARTED"
# fi