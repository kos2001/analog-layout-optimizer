#!/usr/bin/env python3
"""Headless client for the virtuoso-bridge Hermes agent via the api_server.

Same transport Hermes Desktop uses: POST OpenAI-format chat to the gateway's
`/v1/chat/completions` with `Authorization: Bearer <API_SERVER_KEY>`. Lets
scripts/CI drive the analog_opt agent (which calls alo.py + virtuoso-bridge).

Setup (once):
  - profile config: platforms.api_server.enabled=true, extra.port=8650
  - profile .env:   API_SERVER_KEY=<token>
  - run:            virtuoso-bridge gateway start
  - codex/login token must be valid (the desktop auto-refreshes it; headless
    needs `virtuoso-bridge login` / re-auth when it expires).

Usage:
  python ask_agent.py "size an OTA for min power and report gain/GBW/PM/power"
  PORT=8650 python ask_agent.py "..."
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

PROFILE_ENV = os.path.expanduser("~/.hermes/profiles/virtuoso-bridge/.env")


def _api_key() -> str:
    if os.environ.get("API_SERVER_KEY"):
        return os.environ["API_SERVER_KEY"]
    try:
        for line in open(PROFILE_ENV):
            if line.startswith("API_SERVER_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    raise SystemExit("API_SERVER_KEY not found (env or profile .env)")


def ask(prompt: str, *, port: int, model: str = "gpt-5.5", timeout: int = 180) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {_api_key()}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: ask_agent.py <prompt>")
    prompt = " ".join(sys.argv[1:])
    port = int(os.environ.get("PORT", "8650"))
    try:
        resp = ask(prompt, port=port)
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:500]}", file=sys.stderr)
        return 1
    if "error" in resp:
        print("AGENT ERROR:", json.dumps(resp["error"], indent=2))
        return 1
    msg = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(msg or json.dumps(resp, indent=2)[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
