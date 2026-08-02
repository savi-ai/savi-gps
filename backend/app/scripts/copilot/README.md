# Copilot CLI scripts for Savi Teammate

Headless wrappers around [GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli).

**Shared prompts** (used by Claude, Copilot, and Kiro): [`../prompts/savi/`](../prompts/savi/)

| Script | Purpose |
|--------|---------|
| `copilot-cli.sh` | Generic: `copilot -p "…" --allow-all-tools -s` |
| `savi_plan.sh` | Plan from shared `plan.txt` |
| `savi_implement.sh` | Implement in a workdir from shared `implement.txt` |

## Prerequisites

1. Install Copilot CLI (`copilot` on `PATH`).
2. Authenticate: `copilot login`, or set `COPILOT_GITHUB_TOKEN` / `GH_TOKEN` / `GITHUB_TOKEN`.

## Security

`--allow-all-tools` skips interactive approvals. Only use inside trusted sandboxes (ADR 0008).
