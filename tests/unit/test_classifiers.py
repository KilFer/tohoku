import json

import pytest

from fakes import FakeLLM
from tohoku.classify import CLASSIFIERS
from tohoku.classify.base import Candidate, ClassifierError
from tohoku.classify.llm import JsonSchemaClassifier, LabelClassifier

CANDIDATES = [
    Candidate(nombre="japon", descripcion="Lugares y cosas para el viaje a Japón"),
    Candidate(nombre="recetas", descripcion="Recetas de cocina para preparar en casa"),
]


def _json(**over) -> str:
    data = {"destino": "japon", "confianza": 0.9, "alternativa": "recetas", "confianza_alternativa": 0.3}
    data.update(over)
    return json.dumps(data)


def test_json_schema_valid_verdict():
    llm = FakeLLM([_json()], cost=0.002)

    verdict = JsonSchemaClassifier(llm, "m").classify("un reel de ramen", [], CANDIDATES)

    assert verdict.destino == "japon"
    assert verdict.confianza == 0.9
    assert verdict.alternativa == "recetas"
    assert verdict.confianza_alternativa == 0.3
    assert verdict.cost_usd == 0.002
    call = llm.calls[0]
    assert call["schema"]["properties"]["destino"]["enum"] == ["japon", "recetas", "ninguno"]
    sent = json.dumps(call["messages"], ensure_ascii=False)
    for candidate in CANDIDATES:
        assert candidate.descripcion in sent
    assert "un reel de ramen" in sent


def test_json_schema_ninguno_is_none():
    llm = FakeLLM([_json(destino="ninguno", alternativa=None, confianza_alternativa=0.0)])

    verdict = JsonSchemaClassifier(llm, "m").classify("x", [], CANDIDATES)

    assert verdict.destino is None
    assert verdict.alternativa is None


def test_json_schema_broken_json_raises_with_raw_and_cost():
    llm = FakeLLM(["{roto"], cost=0.005)

    with pytest.raises(ClassifierError) as info:
        JsonSchemaClassifier(llm, "m").classify("x", [], CANDIDATES)

    assert info.value.raw == "{roto"
    assert info.value.cost_usd == 0.005


@pytest.mark.parametrize("raw", ["recetas", " Recetas.\n", '"recetas"'])
def test_label_normalizes_response(raw):
    llm = FakeLLM([raw], cost=0.001)

    verdict = LabelClassifier(llm, "m").classify("x", [], CANDIDATES)

    assert verdict.destino == "recetas"
    assert verdict.confianza == 1.0
    assert verdict.cost_usd == 0.001
    assert llm.calls[0]["schema"] is None


def test_label_ninguno_is_none():
    verdict = LabelClassifier(FakeLLM(["ninguno"]), "m").classify("x", [], CANDIDATES)

    assert verdict.destino is None


def test_label_unknown_raises():
    with pytest.raises(ClassifierError) as info:
        LabelClassifier(FakeLLM(["cocina"], cost=0.003), "m").classify("x", [], CANDIDATES)

    assert info.value.raw == "cocina"
    assert info.value.cost_usd == 0.003


@pytest.mark.parametrize("cls,response", [(JsonSchemaClassifier, _json()), (LabelClassifier, "japon")])
def test_feedback_is_last_message(cls, response):
    llm = FakeLLM([response])

    cls(llm, "m").classify("x", [], CANDIDATES, feedback="destino inexistente 'cocina'")

    last = llm.calls[0]["messages"][-1]
    assert last["role"] == "user"
    assert "destino inexistente 'cocina'" in json.dumps(last, ensure_ascii=False)


def test_classifiers_registry():
    assert set(CLASSIFIERS) == {"json_schema", "etiqueta"}
    assert CLASSIFIERS["json_schema"] is JsonSchemaClassifier
    assert CLASSIFIERS["etiqueta"] is LabelClassifier
