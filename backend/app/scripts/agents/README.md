# GPS agent shell scripts (wiki / feature / architecture)

These scripts render prompts from [`../prompts/agents/`](../prompts/agents/) and invoke a vendor CLI wrapper via [`../common/agent_cli.sh`](../common/agent_cli.sh).

| Script | Output |
|--------|--------|
| `wiki_agent.sh` | `wiki_site.html`, `wiki_site.md`, `wiki_result.json` |
| `feature_agent.sh` | `features_result.json` under `temp_store/<id>/` |
| `architecture_agent.sh` | `architecture_result.json` under `temp_store/<id>/` |

## CLI vendor

```bash
# default
./wiki_agent.sh org repo /tmp/out /path/to/clone

# optional
AGENT_CLI=copilot ./wiki_agent.sh ...
AGENT_CLI=kiro ./feature_agent.sh my-run "conversation text"
```

Legacy entrypoints at `scripts/wiki_agent.sh`, `feature_agent.sh`, and `architecture_agent.sh` are shims that forward here (so `WikiAgent` Python still works).

**Note:** Golden-path Feature/Architecture **Python** agents (`FeatureAgent`, `ArchitectureAgent`) use in-process LLM calls. These shell scripts are the CLI/ops path (wiki production path + legacy feature/architecture CLI).
