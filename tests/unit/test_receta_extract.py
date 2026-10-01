import json

import pytest
from PIL import Image

from builders import make_ctx, make_fetch, make_meta
from fakes import FakeLLM
from helpers import make_image
from tohoku.errors import QuotaExceeded
from tohoku.flows.receta.cover import CoverStage
from tohoku.flows.receta.extract import RecetaExtractStage
from tohoku.flows.receta.models import CoverResult, RecetaExtraction
from tohoku.models import ContentType, Transcript
from tohoku.quota import DailyQuota
from tohoku.state import StateStore

VALID = json.dumps({
    "relacionado_destino": True,
    "confianza_destino": 0.95,
    "titulo": "Tortilla de patatas",
    "resumen": "Tortilla jugosa",
    "raciones": 4,
    "ingredientes": [{"cantidad": "6", "unidad": None, "ingrediente": "huevos"}],
    "pasos": ["Pelar patatas", "Cuajar"],
    "portada": 1,
    "confianza": 0.9,
})


@pytest.fixture
def state(tmp_path):
    return StateStore(tmp_path / "state.db")


def _ctx(tmp_path, images=0, frames=0, content_type=ContentType.VIDEO):
    ctx = make_ctx(tmp_path)
    image_paths = [f"images/{i:02}.jpg" for i in range(images)]
    frame_paths = [f"frames/00_{i:02}.jpg" for i in range(frames)]
    for rel in image_paths + frame_paths:
        make_image(ctx.workdir / rel, size=(2000, 1500))
    ctx.results["fetch"] = make_fetch(
        meta=make_meta(content_type=content_type), images=image_paths, keyframes=frame_paths,
    )
    ctx.results["transcribe"] = Transcript(text="Pelamos las patatas", origin="whisper")
    return ctx


def _stage(settings, llm, state, limit=1.0):
    return RecetaExtractStage(settings, llm, DailyQuota(state, "openrouter_usd", limit), "prompt receta")


def test_valid_extraction_and_schema(tmp_path, settings, state):
    llm = FakeLLM([VALID], cost=0.01)

    result = _stage(settings, llm, state).run(_ctx(tmp_path, frames=2))

    assert result.extraction.titulo == "Tortilla de patatas"
    assert result.cost_usd == 0.01
    assert llm.calls[0]["schema"] == RecetaExtraction.model_json_schema()
    assert llm.calls[0]["messages"][0]["content"] == "prompt receta"
    assert state.get_counter("openrouter_usd") == 0.01


def test_schema_retry_reuses_structured_call(tmp_path, settings, state):
    llm = FakeLLM(['{"titulo": "x"}', VALID])

    result = _stage(settings, llm, state).run(_ctx(tmp_path))

    assert result.extraction is not None
    assert len(llm.calls) == 2
    assert "no cumple el esquema" in llm.calls[1]["messages"][-1]["content"]


def test_two_failures_return_error(tmp_path, settings, state):
    result = _stage(settings, FakeLLM(["{}", "{}"]), state).run(_ctx(tmp_path))
    assert result.extraction is None
    assert result.error


def test_vision_model_with_images_and_text_model_without(tmp_path, settings, state):
    llm = FakeLLM([VALID, VALID])
    _stage(settings, llm, state).run(_ctx(tmp_path, images=1))
    _stage(settings, llm, state).run(_ctx(tmp_path / "otro"))
    assert llm.calls[0]["model"] == "vision/model"
    assert llm.calls[1]["model"] == "text/model"


def test_images_order_post_then_keyframes(tmp_path, settings, state):
    from tohoku.clients.openrouter import image_part

    ctx = _ctx(tmp_path, images=2, frames=1)
    # marcamos cada imagen con un tamaño distinto para identificar el orden
    sizes = {"images/00.jpg": (20, 10), "images/01.jpg": (30, 10), "frames/00_00.jpg": (40, 10)}
    for rel, size in sizes.items():
        make_image(ctx.workdir / rel, size=size)
    llm = FakeLLM([VALID])

    _stage(settings, llm, state).run(ctx)

    parts = [p for p in llm.calls[0]["messages"][1]["content"] if p["type"] == "image_url"]
    expected = [image_part(ctx.workdir / rel) for rel in sizes]
    assert parts == expected


def test_budget_exhausted_raises(tmp_path, settings, state):
    with pytest.raises(QuotaExceeded):
        _stage(settings, FakeLLM([VALID]), state, limit=0.0).run(_ctx(tmp_path))


def _cover_ctx(tmp_path, portada, images=0, frames=0, content_type=ContentType.VIDEO):
    ctx = _ctx(tmp_path, images=images, frames=frames, content_type=content_type)
    ctx.results["extract"] = _extract_result(portada)
    return ctx


def _extract_result(portada):
    from tohoku.flows.receta.extract import RecetaExtractResult

    data = json.loads(VALID) | {"portada": portada}
    return RecetaExtractResult(extraction=RecetaExtraction.model_validate(data), cost_usd=0.0)


def test_cover_valid_index(tmp_path, settings):
    ctx = _cover_ctx(tmp_path, 2, images=1, frames=2)

    result = CoverStage(settings).run(ctx)

    assert result == CoverResult(path="cover.jpg")
    with Image.open(ctx.workdir / "cover.jpg") as im:
        assert max(im.size) <= settings.image_max_side


def test_cover_out_of_range_is_none(tmp_path, settings):
    ctx = _cover_ctx(tmp_path, 9, images=1, frames=1, content_type=ContentType.IMAGE)
    assert CoverStage(settings).run(ctx).path is None
    assert not (ctx.workdir / "cover.jpg").exists()


def test_cover_post_without_portada_uses_first_image(tmp_path, settings):
    ctx = _cover_ctx(tmp_path, None, images=2, content_type=ContentType.IMAGE)
    assert CoverStage(settings).run(ctx).path == "cover.jpg"
    assert (ctx.workdir / "cover.jpg").exists()


def test_cover_video_without_portada_is_none(tmp_path, settings):
    ctx = _cover_ctx(tmp_path, None, frames=3, content_type=ContentType.VIDEO)
    assert CoverStage(settings).run(ctx).path is None


def test_cover_without_extraction_is_none(tmp_path, settings):
    ctx = _cover_ctx(tmp_path, 0, images=1)
    ctx.results["extract"] = _extract_result(0).model_copy(update={"extraction": None})
    assert CoverStage(settings).run(ctx).path is None
