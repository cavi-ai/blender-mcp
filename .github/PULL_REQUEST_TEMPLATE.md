## What changed

-

## Why

-

## Verification

- [ ] `uv run --locked python -m unittest discover -s tests`
- [ ] `uv run --locked ruff check .`
- [ ] `npm run eval:protocol`
- [ ] Native Blender check, if Blender-side behavior changed (Blender version: )
- [ ] `uv run --locked python -m scripts.docs.build` and `uv run --locked python -m scripts.docs.verify`, if docs changed

## Contract impact

- [ ] No tool, action, or resource contract change
- [ ] Tool contract changed and `reference/tools.md`, README tool count, and
      `evals/cases.json` updated
