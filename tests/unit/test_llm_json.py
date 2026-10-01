import json

import pytest
from pydantic import BaseModel

from fakes import FakeLLM
from tohoku.errors import QuotaExceeded
from tohoku.llm_json import structured_call
from tohoku.quota import DailyQuota
from tohoku.state import StateStore


class Out(BaseModel):
    n: int


OK = json.dumps({"n": 1})
BAD = json.dumps({"n": "x"})


@pytest.fixture
def budget(tmp_path):
    state = StateStore(tmp_path / "state.db")
    return DailyQuota(state, "openrouter_usd", 10)


def _call(llm, budget, check=lambda _v: []):
    messages = [{"role": "user", "content": "hola"}]
    return structured_call(llm, budget, "m", messages, Out.model_json_schema(), "out", Out.model_validate_json, check)


def test_valid_first_time(budget):
    llm = FakeLLM([OK])
    result = _call(llm, budget)
    assert result.value == Out(n=1) and result.error == "" and len(llm.calls) == 1
    assert result.cost_usd == pytest.approx(0.001)


def test_invalid_then_valid_sends_correction(budget):
    llm = FakeLLM([BAD, OK])
    result = _call(llm, budget)
    assert result.value == Out(n=1)
    second = llm.calls[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": BAD}
    assert "La respuesta no cumple el esquema" in second[-1]["content"]


def test_check_problems_trigger_retry(budget):
    llm = FakeLLM([OK, OK])
    calls = []

    def check(v):
        calls.append(v)
        return ["malo"] if len(calls) == 1 else []

    result = _call(llm, budget, check)
    assert result.value == Out(n=1) and len(llm.calls) == 2
    assert "malo" in llm.calls[1]["messages"][-1]["content"]


def test_two_invalid_answers_give_error(budget):
    llm = FakeLLM([BAD, BAD])
    result = _call(llm, budget)
    assert result.value is None and result.error
    assert result.cost_usd == pytest.approx(0.002)


def test_cost_is_added_to_budget(budget):
    _call(FakeLLM([BAD, OK]), budget)
    assert budget._state.get_counter("openrouter_usd") == pytest.approx(0.002)


def test_quota_exceeded_before_calling(tmp_path):
    state = StateStore(tmp_path / "state.db")
    budget = DailyQuota(state, "openrouter_usd", 0.0)
    llm = FakeLLM([OK])
    with pytest.raises(QuotaExceeded):
        _call(llm, budget)
    assert llm.calls == []
