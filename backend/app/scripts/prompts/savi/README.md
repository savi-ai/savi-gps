# Shared Savi Teammate CLI prompts

These templates are used by **all** coding-agent CLI wrappers:

- `scripts/claude/`
- `scripts/copilot/`
- `scripts/kiro/`
- Python `SaviCodingAgentAdapter` (same files)

| File | Placeholders | Used for |
|------|----------------|----------|
| `system.txt` | — | Shared system / persona rules |
| `plan.txt` | `{{TITLE}}` `{{DESCRIPTION}}` `{{BRIEF}}` | Implementation plan |
| `implement.txt` | `{{TITLE}}` `{{PLAN_PATH}}` `{{SHORT_ID}}` | Code in sandbox |

Render with:

```bash
python3 ../render_prompt.py savi/plan.txt \
  --var 'TITLE=Add health check' \
  --var 'DESCRIPTION=Return 200 on /healthz' \
  --var 'BRIEF='
```

Or via `../common/savi_prompts.sh` helpers (`savi_build_plan_prompt`, `savi_build_implement_prompt`).
