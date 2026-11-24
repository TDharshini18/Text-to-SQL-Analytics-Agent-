"""Rewrite Agent: turns a follow-up question into a standalone one.

"now only 2023" means nothing to the SQL agent on its own. Given the last few questions
and the SQL that answered them, this agent rewrites it as a complete question. A question
that already stands alone comes back unchanged.
"""

import json
import re

from app.services.llm import LLMError, ask_llm

MAX_TURNS = 3  # how many earlier questions the agent looks at
MAX_SQL_CHARS = 1500  # keep the prompt (and the token cost) small

PROMPT = """You rewrite a follow-up question into a standalone question for a database assistant.
You get the earlier questions with the SQL that answered them, then the new question.
- If the new question depends on the earlier ones ("now only 2023", "same but by month",
  "and for Kochi?", "which of those is highest"), rewrite it as ONE complete question that
  carries the needed context.
- If it already makes sense on its own, return it unchanged.
- Do not answer it, do not write SQL, and do not add anything the user did not ask for.

Reply with JSON only:
{"question": "<the standalone question>"}"""


def rewrite_question(question: str, conversation: list[dict]) -> str:
    """Return a standalone version of the question; the original if there is no history."""
    turns = conversation[-MAX_TURNS:]
    if not turns:
        return question
    earlier = "\n\n".join(
        f"Q{i}: {t['question']}\nSQL: {t['sql'][:MAX_SQL_CHARS]}" for i, t in enumerate(turns, 1)
    )
    try:
        reply = ask_llm(PROMPT, f"Earlier:\n{earlier}\n\nNew question: {question}", json_mode=True)
        match = re.search(r"\{.*\}", reply, re.DOTALL)
        data = json.loads(match.group(0) if match else reply)
        rewritten = str(data.get("question") or "").strip()
    except (LLMError, ValueError, AttributeError):
        return question  # a failed rewrite never blocks an answer
    return rewritten or question
