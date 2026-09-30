import json

import pytest

from builders import make_ctx, make_fetch, make_lugar
from fakes import FakeLLM
from helpers import make_image
from tohoku.errors import QuotaExceeded
from tohoku.models import Transcript
from tohoku.quota import DailyQuota
from tohoku.stages.extract import ExtractStage, build_user_text
from tohoku.state import StateStore

VALID = json.dumps({
    "relacionado_japon": True,
    "confianza_japon": 0.9,
    "idioma": "es",
    "resumen_fuente": "Ramen en Shibuya",
    "lugares": [make_lugar().model_dump()],
    "cosas": [],
    "otros": [],
})


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _ctx(tmp_path, images=0, frames=0):
    ctx = make_ctx(tmp_path)
    image_paths = [f"images/{i:02}.jpg" for i in range(images)]
    frame_paths = [f"frames/00_{i:02}.jpg" for i in range(frames)]
    for rel in image_paths + frame_paths:
        make_image(ctx.workdir / rel, size=(10, 10))
    ctx.results["fetch"] = make_fetch(images=image_paths, keyframes=frame_paths)
    ctx.results["transcribe"] = Transcript(text="Hoy comemos en Ichiran", origin="whisper")
    return ctx


def _stage(settings, llm, state, limit=1.0):
    return ExtractStage(settings, llm, DailyQuota(state, "openrouter_usd", limit))


def test_valid_extraction_with_images_uses_vision_model(tmp_path, settings, state):
    llm = FakeLLM([VALID], cost=0.01)

    result = _stage(settings, llm, state).run(_ctx(tmp_path, images=1, frames=2))

    assert result.extraction.lugares[0].nombre == "Ichiran Shibuya"
    assert result.cost_usd == 0.01
    assert llm.calls[0]["model"] == "vision/model"
    user_content = llm.calls[0]["messages"][1]["content"]
    assert sum(1 for part in user_content if part["type"] == "image_url") == 3
    assert state.get_counter("openrouter_usd") == 0.01


def test_without_images_uses_text_model(tmp_path, settings, state):
    llm = FakeLLM([VALID])
    _stage(settings, llm, state).run(_ctx(tmp_path))
    assert llm.calls[0]["model"] == "text/model"


def test_fenced_json_is_accepted(tmp_path, settings, state):
    result = _stage(settings, FakeLLM([f"```json\n{VALID}\n```"]), state).run(_ctx(tmp_path))
    assert result.extraction is not None


def test_invalid_then_valid_retries_once_with_error(tmp_path, settings, state):
    llm = FakeLLM(['{"relacionado_japon": true}', VALID])

    result = _stage(settings, llm, state).run(_ctx(tmp_path))

    assert result.extraction is not None
    assert len(llm.calls) == 2
    retry_messages = llm.calls[1]["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "no cumple el esquema" in retry_messages[-1]["content"]


def test_invalid_twice_returns_error(tmp_path, settings, state):
    result = _stage(settings, FakeLLM(["no json", "tampoco"]), state).run(_ctx(tmp_path))
    assert result.extraction is None
    assert result.error


def test_budget_exceeded_blocks_call(tmp_path, settings, state):
    state.add_counter("openrouter_usd", 5)
    llm = FakeLLM([VALID])
    with pytest.raises(QuotaExceeded):
        _stage(settings, llm, state, limit=1.0).run(_ctx(tmp_path))
    assert llm.calls == []


def test_build_user_text_mentions_everything():
    fetch = make_fetch(images=["images/00.jpg"], keyframes=["frames/00_00.jpg", "frames/00_01.jpg"])
    fetch.meta.hashtags = ["tokyo"]
    fetch.meta.description = "Mi caption"
    text = build_user_text(fetch, Transcript(text="audio", origin="whisper"))
    assert "Mi caption" in text and "audio" in text and "#tokyo" in text
    assert "1 imágenes del post" in text and "2 fotogramas" in text
