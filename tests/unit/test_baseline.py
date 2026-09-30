"""Líneas base del comportamiento de Japón antes del multidestino (fase 2).

Las fixtures se generaron con el código anterior al refactor: estos tests no se regeneran, se cumplen.
"""
import json
from pathlib import Path

from tohoku.models import Extraction, ExtractResult, GeocodeResult, ResolveResult
from tohoku.notes import name_key

FIXTURES = Path(__file__).parents[1] / "fixtures"
BASELINE = FIXTURES / "baseline"
STATE = FIXTURES / "state_results"
REPO = Path(__file__).parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_extract_prompt_matches_baseline():
    assert _read(REPO / "src/tohoku/prompts/extract.md") == _read(BASELINE / "extract_prompt.md")


def test_extraction_schema_matches_baseline():
    assert Extraction.model_json_schema() == json.loads(_read(BASELINE / "extraction_schema.json"))


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
