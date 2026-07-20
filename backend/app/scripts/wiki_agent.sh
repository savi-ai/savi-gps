#!/bin/bash
# Wiki Agent — deep codebase analysis → HTML + Markdown + JSON wiki.
#
# Usage: wiki_agent.sh <org_name> <repo_name> <output_dir> <clone_path> [analysis_config_json_path]
#
# Output: app/scripts/temp_store/analysis/<ORG>/<REPO>/
#   wiki_site.html, wiki_site.md, wiki_result.json
#   WIKI_STARTED | WIKI_COMPLETED | WIKI_FAILED (with timestamps)

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
SAMPLE_HTML="$SCRIPT_DIR/sample.html"
PROMPT_SNIPPET="$SCRIPT_DIR/../prompts/wiki_deep_analysis.txt"
TEMPLATE_PATH="$SCRIPT_DIR/../templates/wiki/wiki_site_template.html"

fail() {
  echo "$(timestamp)" > "$OUTPUT_DIR/WIKI_FAILED"
  echo "$1" >> "$OUTPUT_DIR/WIKI_FAILED"
  echo "WIKI_FAILED: $1" >&2
  exit 1
}

# Load API key from backend/.env when subprocess env did not inherit it
BACKEND_ENV="$(cd "$SCRIPT_DIR/../.." && pwd)/.env"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$BACKEND_ENV" ]; then
  ANTHROPIC_API_KEY="$(grep -E '^ANTHROPIC_API_KEY=' "$BACKEND_ENV" | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\''"]//;s/["'\''"]$//')"
  export ANTHROPIC_API_KEY
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  fail "ANTHROPIC_API_KEY is required for wiki_agent.sh"
fi

if ! command -v claude >/dev/null 2>&1; then
  fail "claude CLI not found on PATH"
fi

DEEP_RULES=""
if [ -f "$PROMPT_SNIPPET" ]; then
  DEEP_RULES=$(cat "$PROMPT_SNIPPET")
fi

CONFIG_BLOCK=""
if [ -n "$CONFIG_JSON" ] && [ -f "$CONFIG_JSON" ]; then
  CONFIG_BLOCK="
Tenant analysis attributes — extract into wiki_result.json.analysis_attributes:
$(cat "$CONFIG_JSON")
"
fi

PROMPT="
Analyze this repository at: $CLONE_PATH

Organization: $ORG_NAME
Repository: $REPO_NAME
Output directory (write ALL artifacts here): $OUTPUT_DIR
HTML style reference: $SAMPLE_HTML
Alternate template reference: $TEMPLATE_PATH

$DEEP_RULES

$CONFIG_BLOCK

Additional JSON schema for $WIKI_JSON:
{
  \"repo_name\": \"string\",
  \"overview\": { \"description\": \"string\", \"loc\": number, \"file_count\": number },
  \"functionality\": { \"summary\": \"string\", \"bullets\": [\"string\"] },
  \"tech_stack\": [{ \"layer\": \"string\", \"technologies\": [\"string\"], \"evidence_file\": \"string\" }],
  \"business_logic_layer\": {
    \"summary\": \"string\",
    \"components\": [{
      \"name\": \"string\",
      \"purpose\": \"string\",
      \"source_files\": [\"string\"],
      \"workflows\": [{ \"operation\": \"string\", \"steps\": [\"string\"] }],
      \"business_rules\": [{ \"rule\": \"string\", \"evidence_file\": \"string\" }]
    }]
  },
  \"analysis_attributes\": [{ \"key\": \"string\", \"label\": \"string\", \"value\": \"string\", \"source_file\": \"string\", \"confidence\": \"high|medium|low\" }],
  \"diagrams\": {
    \"high_level_mermaid\": \"flowchart or graph TD ...\",
    \"low_level_mermaid\": \"graph TD ...\",
    \"data_model_mermaid\": \"erDiagram ...\",
    \"request_flow_mermaid\": \"flowchart LR ...\",
    \"e2e_flow_mermaid\": \"sequenceDiagram ...\",
    \"deployment_flow_mermaid\": \"flowchart TD ...\"
  },
  \"api_surface\": [{ \"method\": \"string\", \"path\": \"string\", \"file\": \"string\", \"description\": \"string\" }],
  \"data_flow\": { \"summary\": \"string\", \"diagram_mermaid\": \"string\" },
  \"database\": { \"summary\": \"string\", \"entities\": [\"string\"] },
  \"build_deploy\": { \"summary\": \"string\", \"artifacts\": [\"string\"] },
  \"run_locally\": { \"intro\": \"string\", \"prerequisites\": [\"string\"], \"commands\": \"string\" },
  \"observability\": { \"summary\": \"string\" },
  \"sections_md\": {
    \"overview\": \"markdown\",
    \"architecture\": \"markdown\",
    \"business_logic\": \"markdown\",
    \"api_surface\": \"markdown\",
    \"data_flow\": \"markdown\",
    \"e2e_flow\": \"markdown\",
    \"database\": \"markdown\",
    \"build_deploy\": \"markdown\"
  }
}

REQUIRED output files:
1. $WIKI_HTML — complete HTML wiki similar to $SAMPLE_HTML (left TOC, Mermaid, Business Logic Layer section)
2. $WIKI_MD — same wiki content as Markdown
3. $WIKI_JSON — structured data per schema above

Process:
1. Read implementation files under $CLONE_PATH using Read, Grep, Bash — do NOT modify source.
2. Write all three files to $OUTPUT_DIR only.
3. On success, write $(timestamp) to $OUTPUT_DIR/WIKI_COMPLETED (you may overwrite WIKI_STARTED).

Constraints:
- Do not hallucinate — omit or mark \"Not detected\" when evidence is missing.
- Prefer *Impl*, *Service*, *Manager*, *Handler* files for business logic depth.
"

CLAUDE_SYSTEM="You are the Savi GPS Wiki Agent — a principal engineer producing Deep Wiki quality documentation.
You read real source code, extract business logic from implementations (not just interfaces), and write citation-backed HTML, Markdown, and JSON.
Match the richness of a professional internal wiki. Write output files exactly to the specified output directory."

echo "Wiki Agent starting for $ORG_NAME/$REPO_NAME at $(timestamp)" >&2

set +e
claude -p "$PROMPT" \
  --append-system-prompt "$CLAUDE_SYSTEM" \
  --allowedTools "Bash,Read,Grep" \
  --add-dir "$CLONE_PATH" \
  --permission-mode acceptEdits \
  --max-turns 40
CLAUDE_EXIT=$?
set -e

if [ "$CLAUDE_EXIT" -ne 0 ]; then
  fail "claude CLI exited with code $CLAUDE_EXIT"
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
