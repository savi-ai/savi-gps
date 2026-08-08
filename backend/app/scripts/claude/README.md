# Claude CLI scripts for Savi Teammate

Wrappers around the Anthropic `claude` CLI. Savi prompts are **shared** with Copilot and Kiro under [`../prompts/savi/`](../prompts/savi/).

| Script | Purpose |
|--------|---------|
| `claude-cli.sh` | Generic headless runner (`claude -p …`) |
| `savi_plan.sh` | Plan from `prompts/savi/plan.txt` |
| `savi_implement.sh` | Implement in a workdir from `prompts/savi/implement.txt` |

## Prerequisites

- `claude` on `PATH`
- `ANTHROPIC_API_KEY` set (or loaded from `backend/.env`)

## Examples

```bash
./claude-cli.sh "Summarize this repository layout"
./savi_plan.sh "Add health check" "Return 200 on /healthz"
./savi_implement.sh "Add health check" /tmp/savi_sandbox .savi/work/abc/PLAN.md abc
```

Legacy callers that used `app/scripts/claude-cli.sh` are forwarded via a shim at that path.
