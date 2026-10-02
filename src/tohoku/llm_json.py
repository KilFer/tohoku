"""LLM call with structured JSON output, validation and one correction retry."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from tohoku.quota import DailyQuota
from tohoku.text import strip_fences

log = logging.getLogger(__name__)


@dataclass
class StructuredResult[T]:
    value: T | None
    error: str
    cost_usd: float


def structured_call[T](
    llm,
    budget: DailyQuota,
    model: str,
    messages: list[dict],
    schema: dict,
    name: str,
    parse: Callable[[str], T],
    check: Callable[[T], list[str]] = lambda _v: [],
) -> StructuredResult[T]:
    """Up to two attempts: if the response does not validate (or `check` reports problems) it is resent with the correction."""
    cost = 0.0
    error = ""
    for _ in range(2):
        budget.check()
        result = llm.chat_json(model, messages, schema, name)
        budget.add(result.cost_usd)
        cost += result.cost_usd
        value: T | None = None
        try:
            value = parse(strip_fences(result.content))
            problems = check(value)
        except ValidationError as exc:
            problems = [str(exc)]
        if problems:
            error = "\n".join(problems)
            messages = [
                *messages,
                {"role": "assistant", "content": result.content},
                {"role": "user", "content": f"La respuesta no cumple el esquema:\n{error}\nDevuelve únicamente el JSON corregido."},
            ]
            continue
        return StructuredResult(value=value, error="", cost_usd=cost)
    return StructuredResult(value=None, error=error, cost_usd=cost)
