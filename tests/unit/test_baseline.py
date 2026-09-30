"""Líneas base del comportamiento de Japón antes del multidestino (fase 2).

Las fixtures se generaron con el código anterior al refactor: estos tests no se regeneran, se cumplen.
"""
import json
from pathlib import Path

from builders import make_ctx, make_fetch
from fakes import FakeLLM, FakeTrilium
from tohoku.config import Thresholds
from tohoku.models import Extraction, ExtractResult, GeocodeResult, Outcome, ResolveResult, Transcript
from tohoku.notes import name_key
from tohoku.quota import DailyQuota
from tohoku.stages.publish import PublishStage
from tohoku.stages.resolve import ResolveStage
from tohoku.state import StateStore
from tohoku.trilium_layout import init_layout

FIXTURES = Path(__file__).parents[1] / "fixtures"
BASELINE = FIXTURES / "baseline"
STATE = FIXTURES / "state_results"
REPO = Path(__file__).parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Único cambio intencionado respecto a la línea base: los campos de relevancia ya no se llaman "japon".
RENAMES = {
    "relacionado_japon": "relacionado_destino",
    "confianza_japon": "confianza_destino",
    "Relacionado Japon": "Relacionado Destino",
    "Confianza Japon": "Confianza Destino",
}


def _renamed(text: str) -> str:
    for old, new in RENAMES.items():
        text = text.replace(old, new)
    return text


def test_japan_prompt_matches_baseline():
    assert _read(REPO / "config/prompts/japon.md") == _renamed(_read(BASELINE / "extract_prompt.md"))


def test_extraction_schema_matches_baseline():
    assert Extraction.model_json_schema() == json.loads(_renamed(_read(BASELINE / "extraction_schema.json")))


def test_name_keys_match_baseline():
    expected = json.loads(_read(BASELINE / "name_keys.json"))
    assert len(expected) > 100
    assert {name: name_key(name) for name in expected} == expected


def test_real_stage_results_load():
    assert len(list(STATE.glob("*.json"))) == 6
    for path in STATE.glob("*_extract.json"):
        ExtractResult.model_validate_json(_read(path))
    for path in STATE.glob("*_geocode.json"):
        GeocodeResult.model_validate_json(_read(path))
    for path in STATE.glob("*_resolve.json"):
        ResolveResult.model_validate_json(_read(path))


def test_real_extract_keeps_its_values_and_is_saved_with_new_names():
    raw = json.loads(_read(STATE / "rich_extract.json"))
    result = ExtractResult.model_validate(raw)

    assert result.extraction.confianza_destino == raw["extraction"]["confianza_japon"]
    assert result.extraction.relacionado_destino == raw["extraction"]["relacionado_japon"]
    dumped = json.loads(result.model_dump_json())["extraction"]
    assert "confianza_destino" in dumped and "confianza_japon" not in dumped
    assert ExtractResult.model_validate_json(result.model_dump_json()) == result


def _real_ctx(tmp_path, label):
    return make_ctx(
        tmp_path, fetch=make_fetch(), transcribe=Transcript(text="x", origin="whisper"),
        extract=ExtractResult.model_validate_json(_read(STATE / f"{label}_extract.json")),
        geocode=GeocodeResult.model_validate_json(_read(STATE / f"{label}_geocode.json")),
    )


def _japan_trilium():
    trilium = FakeTrilium()
    trilium.add_note("root", "Ideas de Japón", labels={"jrRoot": ""})
    return trilium, init_layout(trilium)


def test_real_results_resolve_like_baseline_and_publish(tmp_path, settings):
    trilium, layout = _japan_trilium()
    ctx = _real_ctx(tmp_path, "rich")

    plan = ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx)

    assert [[i.key, i.kind.value, i.action, i.alias_of] for i in plan.items] == json.loads(_read(BASELINE / "rich_plan.json"))
    ctx.results["resolve"] = plan
    state = StateStore(tmp_path / "state.db")
    merged = json.dumps({"resumen": "r", "que_hacer": "", "consejos": []})
    result = PublishStage(trilium, lambda: layout, FakeLLM([merged] * 10), settings, DailyQuota(state, "openrouter_usd", 10), state).run(ctx)
    assert len(result.notes) == sum(i.action != "alias" for i in plan.items)


def test_real_not_japan_result_publishes_nothing(tmp_path, settings):
    trilium, layout = _japan_trilium()
    ctx = _real_ctx(tmp_path, "no_japon")
    ctx.results["resolve"] = ResolveStage(trilium, lambda: layout, Thresholds()).run(ctx)
    state = StateStore(tmp_path / "state.db")
    result = PublishStage(trilium, lambda: layout, FakeLLM([]), settings, DailyQuota(state, "openrouter_usd", 10), state).run(ctx)
    assert result.notes == [] and result.outcome == Outcome.NO_JAPON
