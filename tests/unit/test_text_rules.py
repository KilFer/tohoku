import pytest

from tohoku.config import Thresholds
from tohoku.models import Extraction, Outcome, PublishedNote
from tohoku.rules import decide_outcome, japan_decision
from tohoku.text import fold, normalize_name, similarity, strip_fences


def test_fold_keeps_words():
    assert fold("Japón, ÑANDÚ") == "japon, nandu"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ichiran  Shibuya!", "ichiran shibuya"),
        ("Tienda Don Quijote", "don quijote"),
        ("Kiyomizu-dera", "kiyomizu dera"),
        ("Café Ñandú", "cafe nandu"),
        ("CoCo Ichibanya (Japan)", "coco ichibanya"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_similarity_bounds():
    assert similarity("coco ichibanya", "coco ichibanya") == 1.0
    assert similarity("coco ichibanya", "coco ichiban ya") > 0.85
    assert similarity("yoshinoya", "matsuya") < 0.7


def test_strip_fences():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fences('  {"a": 1} ') == '{"a": 1}'


def _extraction(conf: float) -> Extraction:
    return Extraction(relacionado_japon=conf >= 0.5, confianza_japon=conf, idioma="es", resumen_fuente="x")


@pytest.mark.parametrize(("conf", "expected"), [(0.1, "no"), (0.39, "no"), (0.4, "uncertain"), (0.69, "uncertain"), (0.7, "yes"), (1.0, "yes")])
def test_japan_decision(conf, expected):
    assert japan_decision(_extraction(conf), Thresholds()) == expected


def test_decide_outcome():
    ok = PublishedNote(key="lugar:0", note_id="n1", action="create", review_reasons=[])
    review = PublishedNote(key="cosa:0", note_id="n2", action="create", review_reasons=["baja-confianza"])
    assert decide_outcome("no", []) == Outcome.NO_JAPON
    assert decide_outcome("yes", [ok]) == Outcome.PROCESADO
    assert decide_outcome("yes", [ok, review]) == Outcome.REVISAR
