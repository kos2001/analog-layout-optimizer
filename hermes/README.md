# Hermes Agent skill — analog-layout-optimizer

A Hermes Agent skill wrapping this repo's engine + virtuoso-bridge so a
self-hosted agent can drive analog sizing/routing/process-migration by natural
language. Link into a Hermes profile's `skills/` directory.

- `SKILL.md` — skill definition (triggers, usage).
- `scripts/alo.py` — JSON CLI: opamp / opamp-study / joint / maze / tcoil /
  adapt / preflight / spectre-eval.
- `scripts/ask_agent.py` — headless client to the Hermes api_server
  (`/v1/chat/completions`) for scripted/CI agent calls.

Set `ALO_REPO` to this repo's path; run with a Python env that has the engine
deps installed.
