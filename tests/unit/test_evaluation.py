from builders import make_extraction, make_fetch, make_lugar, make_cosa
from tohoku.config import Thresholds
from tohoku.evaluation import EvalCase, EvalRunner, count_matches, format_table, load_cases, score_case
from tohoku.models import ExtractResult, Transcript

CASE = EvalCase.model_validate({
    "id": "ramen", "url": "https://www.youtube.com/shorts/abc",
    "expect": {"destino": True, "lugares": ["Ichiran Shibuya", "Fushimi Inari"], "cosas": ["CoCo Ichibanya"]},
})


def test_count_matches_is_tolerant():
    assert count_matches(["Ichiran Shibuya", "Fushimi Inari"], ["ICHIRAN Shibuya", "Fushimi Inari Taisha"]) == 2
    assert count_matches(["Kinkaku-ji"], ["Tokyo Tower", "Nara Park"]) == 0


def test_score_case():
    extraction = make_extraction(lugares=[make_lugar(), make_lugar("Tokyo Tower")], cosas=[make_cosa()])
    score = score_case(CASE, ExtractResult(extraction=extraction, cost_usd=0.02), Thresholds())
    assert score.destino_ok is True
    assert (score.lugares_found, score.lugares_expected) == (1, 2)
    assert (score.cosas_found, score.cosas_expected) == (1, 1)
    assert score.extra == 1
    assert score.cost_usd == 0.02


def test_score_failed_extraction():
    score = score_case(CASE, ExtractResult(extraction=None, error="JSON"), Thresholds())
    assert score.destino_ok is False and score.error == "JSON"


def test_format_table_totals():
    extraction = make_extraction(lugares=[make_lugar()])
    table = format_table([score_case(CASE, ExtractResult(extraction=extraction, cost_usd=0.01), Thresholds())], "vision/model", True)
    assert "vision/model" in table and "fotogramas: sí" in table
    assert "ramen | ok | 1/2 | 0/1" in table
    assert "Lugares 1/2" in table


def test_load_cases(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text("- id: a\n  url: https://youtu.be/x\n  expect: {destino: false}\n", encoding="utf-8")
    assert load_cases(path)[0].expect.destino is False
    path.write_text("# vacío\n", encoding="utf-8")
    assert load_cases(path) == []


class StubStage:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        return self.result


class RecordingExtract:
    def __init__(self):
        self.keyframes_seen = []

    def run(self, ctx):
        self.keyframes_seen.append(list(ctx.results["fetch"].keyframes))
        return ExtractResult(extraction=make_extraction(lugares=[make_lugar()]))


def test_runner_caches_media_and_can_drop_keyframes(tmp_path):
    fetch = StubStage(make_fetch(keyframes=["frames/00_00.jpg"]))
    transcribe = StubStage(Transcript(text="hola", origin="whisper"))
    runner = EvalRunner(fetch, transcribe, tmp_path / "cache")
    extract = RecordingExtract()

    runner.run([CASE], extract, Thresholds(), keyframes=True)
    runner.run([CASE], extract, Thresholds(), keyframes=False)

    assert fetch.calls == 1 and transcribe.calls == 1
    assert extract.keyframes_seen == [["frames/00_00.jpg"], []]
