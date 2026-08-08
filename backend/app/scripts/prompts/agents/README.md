# Agent CLI prompts (wiki / feature / architecture)

Shared `.txt` templates for GPS agent shell scripts. Same pattern as [`../savi/`](../savi/).

| Agent | Files | Script |
|-------|-------|--------|
| Wiki | `wiki/system.txt`, `wiki/task.txt` + `app/prompts/wiki_deep_analysis.txt` | `scripts/agents/wiki_agent.sh` |
| Feature | `feature/system.txt`, `feature/task.txt` | `scripts/agents/feature_agent.sh` |
| Architecture | `architecture/system.txt`, `architecture/task.txt` | `scripts/agents/architecture_agent.sh` |

Render with `../render_prompt.py` or `../../common/savi_prompts.sh` (`savi_render_prompt` after setting `SAVI_PROMPTS_DIR`).

Deep wiki rules stay at `backend/app/prompts/wiki_deep_analysis.txt` (also used by `WikiAgent` Python path).
