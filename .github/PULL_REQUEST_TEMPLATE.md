## What changed

-

## Why

-

## Verification

- [ ] `uv run --locked python -m unittest discover -s tests`
- [ ] `uv run --locked ruff check .`
- [ ] `npm run eval:protocol`
- [ ] Native Blender check, if Blender-side behavior changed (Blender version: )
- [ ] `python3 scripts/docs/build.py` and `python3 scripts/docs/verify.py`, if docs changed

## Contract impact

- [ ] No tool, action, or resource contract change
- [ ] Tool contract changed and `reference/tools.md`, README tool count, and
      `evals/cases.json` updated
