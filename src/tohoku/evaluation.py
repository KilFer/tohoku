from pathlib import Path

import yaml
from pydantic import BaseModel

from tohoku.config import Thresholds
from tohoku.context import JobContext
from tohoku.errors import TohokuError
from tohoku.models import ExtractResult, FetchResult, Transcript
from tohoku.rules import destination_decision
from tohoku.sources import classify_url
from tohoku.state import Job, JobStatus, utcnow
from tohoku.text import normalize_name, similarity

NAME_MATCH = 0.8


class Expect(BaseModel):
    japan: bool
    lugares: list[str] = []
    cosas: list[str] = []


class EvalCase(BaseModel):
    id: str
    url: str
    expect: Expect


class CaseScore(BaseModel):
    id: str
    japan_ok: bool
    lugares_found: int = 0
    lugares_expected: int = 0
    cosas_found: int = 0
    cosas_expected: int = 0
    extra: int = 0
    cost_usd: float = 0.0
    error: str | None = None


def load_cases(path: Path) -> list[EvalCase]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [EvalCase.model_validate(case) for case in data]


def count_matches(expected: list[str], got: list[str]) -> int:
    found = [normalize_name(g) for g in got if g]
    hits = 0
    for name in expected:
        wanted = normalize_name(name)
        if any(g and (wanted in g or g in wanted or similarity(wanted, g) >= NAME_MATCH) for g in found):
            hits += 1
    return hits


def score_case(case: EvalCase, result: ExtractResult, thresholds: Thresholds) -> CaseScore:
    expected_l, expected_c = len(case.expect.lugares), len(case.expect.cosas)
    extraction = result.extraction
    if extraction is None:
        return CaseScore(
            id=case.id, japan_ok=False, lugares_expected=expected_l, cosas_expected=expected_c,
            cost_usd=result.cost_usd, error=result.error or "extracción fallida",
        )
    is_japan = destination_decision(extraction, thresholds) != "no"
    lugar_names = [l.nombre for l in extraction.lugares] + [l.nombre_local for l in extraction.lugares if l.nombre_local]
    found_l = count_matches(case.expect.lugares, lugar_names)
    found_c = count_matches(case.expect.cosas, [c.nombre for c in extraction.cosas])
    return CaseScore(
        id=case.id, japan_ok=is_japan == case.expect.japan,
        lugares_found=found_l, lugares_expected=expected_l, cosas_found=found_c, cosas_expected=expected_c,
        extra=max(0, len(extraction.lugares) + len(extraction.cosas) - found_l - found_c), cost_usd=result.cost_usd,
    )


def format_table(scores: list[CaseScore], model: str, keyframes: bool) -> str:
    lines = [f"Modelo: {model} · fotogramas: {'sí' if keyframes else 'no'}", "caso | japón | lugares | cosas | extra | coste USD | error"]
    for s in scores:
        lines.append(
            f"{s.id} | {'ok' if s.japan_ok else 'FALLO'} | {s.lugares_found}/{s.lugares_expected} | "
            f"{s.cosas_found}/{s.cosas_expected} | {s.extra} | {s.cost_usd:.4f} | {s.error or ''}"
        )
    lines.append(
        f"TOTAL · Japón {sum(s.japan_ok for s in scores)}/{len(scores)} · "
        f"Lugares {sum(s.lugares_found for s in scores)}/{sum(s.lugares_expected for s in scores)} · "
        f"Cosas {sum(s.cosas_found for s in scores)}/{sum(s.cosas_expected for s in scores)} · "
        f"Extra {sum(s.extra for s in scores)} · Coste {sum(s.cost_usd for s in scores):.4f} USD"
    )
    return "\n".join(lines)


class EvalRunner:
    """Descarga y transcribe cada caso una vez (caché en disco) y solo repite la extracción."""

    def __init__(self, fetch, transcribe, cache_dir: Path) -> None:
        self._fetch = fetch
        self._transcribe = transcribe
        self._cache = cache_dir

    def _prepare(self, case: EvalCase) -> JobContext:
        classified = classify_url(case.url)
        if classified is None:
            raise ValueError(f"URL no soportada en el caso {case.id}: {case.url}")
        now = utcnow()
        job = Job(
            bookmark_id=f"eval-{case.id}", url=case.url, platform=classified[0], hint=classified[1],
            status=JobStatus.PENDING, attempts=0, next_attempt_at=None, last_error=None, outcome=None,
            created_at=now, updated_at=now,
        )
        ctx = JobContext(job=job, workdir=self._cache / case.id)
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        fetch_file, transcript_file = ctx.workdir / "fetch.json", ctx.workdir / "transcript.json"
        if fetch_file.exists():
            ctx.results["fetch"] = FetchResult.model_validate_json(fetch_file.read_text(encoding="utf-8"))
        else:
            ctx.results["fetch"] = self._fetch.run(ctx)
            fetch_file.write_text(ctx.results["fetch"].model_dump_json(), encoding="utf-8")
        if transcript_file.exists():
            ctx.results["transcribe"] = Transcript.model_validate_json(transcript_file.read_text(encoding="utf-8"))
        else:
            ctx.results["transcribe"] = self._transcribe.run(ctx)
            transcript_file.write_text(ctx.results["transcribe"].model_dump_json(), encoding="utf-8")
        return ctx

    def run(self, cases: list[EvalCase], extract, thresholds: Thresholds, keyframes: bool) -> list[CaseScore]:
        scores = []
        for case in cases:
            try:
                ctx = self._prepare(case)
                if not keyframes:
                    ctx.results["fetch"] = ctx.result("fetch", FetchResult).model_copy(update={"keyframes": []})
                scores.append(score_case(case, extract.run(ctx), thresholds))
            except (TohokuError, ValueError) as exc:
                scores.append(CaseScore(id=case.id, japan_ok=False, error=str(exc)))
        return scores
