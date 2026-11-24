"""Check whether the Groq key in backend/.env can make requests right now.

  python -m benchmarks.check_quota

Sends one tiny request (about 10 tokens). Note: Groq does not report the daily tokens left,
so "OK" means small requests work; a full question (~6,000 tokens) can still be refused
if the daily quota is nearly used up.
"""

import re

import httpx

from app import config

r = httpx.post(
    "https://api.groq.com/openai/v1/chat/completions",
    headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
    json={"model": config.GROQ_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
    timeout=30,
)
if r.status_code == 200:
    h = r.headers
    print(f"OK - the key works ({config.GROQ_MODEL}).")
    print(f"  requests left today:      {h.get('x-ratelimit-remaining-requests')} of {h.get('x-ratelimit-limit-requests')}")
    print(f"  tokens left this minute:  {h.get('x-ratelimit-remaining-tokens')} of {h.get('x-ratelimit-limit-tokens')}")
else:
    message = r.json().get("error", {}).get("message", r.text)
    print(f"LIMITED - HTTP {r.status_code}")
    print("  " + re.sub(r"org_\w+", "org_***", message)[:300])
