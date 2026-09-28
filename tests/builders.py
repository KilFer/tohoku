from datetime import UTC, datetime
from pathlib import Path

from japan_reader.context import JobContext
from japan_reader.models import ContentType, Cosa, Extraction, FetchResult, GeoMatch, Lugar, Otro, SourceMeta
from japan_reader.sources import ContentHint, Platform
from japan_reader.state import Job, JobStatus


def make_job(bookmark_id="b1", url="https://www.youtube.com/shorts/abc", platform=Platform.YOUTUBE, hint=ContentHint.VIDEO) -> Job:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    return Job(
        bookmark_id=bookmark_id, url=url, platform=platform, hint=hint, status=JobStatus.PENDING, attempts=0,
        next_attempt_at=None, last_error=None, outcome=None, created_at=now, updated_at=now,
    )


def make_ctx(tmp_path: Path, job: Job | None = None, **results) -> JobContext:
    job = job or make_job()
    workdir = tmp_path / "jobs" / job.bookmark_id
    workdir.mkdir(parents=True, exist_ok=True)
    return JobContext(job=job, workdir=workdir, results=dict(results))


def make_meta(**overrides) -> SourceMeta:
    base = {
        "url": "https://www.youtube.com/shorts/abc", "platform": Platform.YOUTUBE, "content_type": ContentType.VIDEO,
        "title": "Ramen en Tokio", "author": "viajero", "published": "2026-08-01",
    }
    return SourceMeta(**(base | overrides))


def make_fetch(**overrides) -> FetchResult:
    return FetchResult(**({"meta": make_meta()} | overrides))


def make_lugar(nombre="Ichiran Shibuya", **overrides) -> Lugar:
    base = {
        "nombre": nombre, "nombre_local": None, "consulta_busqueda": f"{nombre} Tokyo", "ciudad": "Tokio",
        "region": "Kanto", "categoria": "comida", "que_es": f"Ramen en {nombre}", "que_hacer": "Pedir tonkotsu",
        "consejos": ["Ir pronto"], "precio_aprox": "¥1000", "confianza": 0.9,
    }
    return Lugar(**(base | overrides))


def make_cosa(nombre="CoCo Ichibanya", **overrides) -> Cosa:
    base = {
        "nombre": nombre, "categoria": "cadenas", "que_es": "Curry japonés", "consejos": ["Elige el picante"],
        "donde": ["Por todo Japón"], "donde_lugares": [], "confianza": 0.9,
    }
    return Cosa(**(base | overrides))


def make_extraction(confianza_japon=0.95, lugares=(), cosas=(), otros=()) -> Extraction:
    return Extraction(
        relacionado_japon=confianza_japon >= 0.5, confianza_japon=confianza_japon, idioma="es",
        resumen_fuente="Un vídeo sobre Tokio", lugares=list(lugares), cosas=list(cosas),
        otros=[o if isinstance(o, Otro) else Otro(**o) for o in otros],
    )


def make_geo(
    place_id="P1", name="Ichiran Shibuya", address="Jinnan, Shibuya, Tokio 150-0041, Japón", lat=35.66, lng=139.70,
    country_code=None, area="",
) -> GeoMatch:
    return GeoMatch(
        place_id=place_id, name=name, address=address, lat=lat, lng=lng,
        maps_url=f"https://maps.google.com/?cid={place_id}", country_code=country_code, area=area,
    )
