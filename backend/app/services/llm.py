"""Sends prompts to Groq and returns the reply text.

Groq's API is OpenAI-compatible: POST /chat/completions with a list of messages.
"""

import time

import httpx

from app import config

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRIES = 6

# Running totals, used by the benchmark to report cost.
usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


class LLMError(Exception):
    pass


def chat_llm(messages: list[dict], json_mode: bool = False) -> str:
    """Send a whole conversation (system/user/assistant messages) and return the reply."""
    if not config.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is missing. Add it to backend/.env")

    body = {"model": config.GROQ_MODEL, "temperature": 0, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                json=body,
                timeout=90,
            )
        except httpx.HTTPError as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))
                continue
            raise LLMError(f"Could not reach the Groq API: {e}") from e

        # 429 = rate limited, 5xx = temporary server problem: wait and try again.
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < MAX_RETRIES and not _is_daily_limit(response):
                time.sleep(_wait_seconds(response, attempt))
                continue
        if response.status_code != 200:
            raise LLMError(f"Groq API error {response.status_code}: {response.text[:800]}")

        data = response.json()
        used = data.get("usage") or {}
        usage["calls"] += 1
        usage["prompt_tokens"] += used.get("prompt_tokens", 0)
        usage["completion_tokens"] += used.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"] or ""
    raise LLMError("Groq API: too many retries")


def _wait_seconds(response: httpx.Response, attempt: int) -> float:
    """How long Groq asks us to wait (retry-after header), else exponential backoff."""
    try:
        return min(float(response.headers.get("retry-after", "")) + 0.5, 120)
    except ValueError:
        return min(2 ** attempt * 2, 60)


def _is_daily_limit(response: httpx.Response) -> bool:
    # Waiting won't help once the per-day quota is used up.
    text = response.text.lower()
    return "per day" in text or "(rpd)" in text or "(tpd)" in text


def ask_llm(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    return chat_llm(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        json_mode=json_mode,
    )
