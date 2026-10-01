import json
import logging
from collections.abc import Callable

from pydantic import ValidationError

from tohoku.clients.openrouter import OpenRouterClient
from tohoku.clients.trilium import TNote, TriliumClient
from tohoku.config import Settings
from tohoku.context import JobContext
from tohoku.errors import ApiError
from tohoku.geo import near_notes
from tohoku.models import (
    Extraction,
    ExtractResult,
    FetchResult,
    GeocodeResult,
    ItemKind,
    MergeOutput,
    PlannedItem,
    PublishedNote,
    PublishResult,
    ResolveResult,
    SourceMeta,
    Transcript,
)
from tohoku.notes import (
    DATA_ATTACHMENT_TITLE,
    CosaData,
    LugarData,
    NoteData,
    OtroData,
    add_source,
    compose_content,
    dump_data,
    item_identity,
    labels_for,
    load_data,
    name_key,
    note_title,
    render_generated,
    source_entry,
)
from tohoku.prompts import load_prompt
from tohoku.publishing import create_failure_note, sync_labels, sync_review, upsert_labels
from tohoku.quota import DailyQuota
from tohoku.rules import decide_outcome, destination_decision
from tohoku.state import StateStore
from tohoku.text import normalize_name, strip_fences
from tohoku.trilium_layout import Layout

__all__ = ["PublishStage", "sync_labels", "upsert_labels"]

log = logging.getLogger(__name__)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _synthetic_title(meta: SourceMeta) -> str:
    if meta.title and meta.title.strip():
        return meta.title
    first_line = next((line.strip() for line in (meta.description or "").splitlines() if line.strip()), "")
    return first_line[:80].strip() or "Sin título"


class PublishStage:
    """Etapa 7: crea o fusiona notas en Trilium y manda lo dudoso a la bandeja de revisión."""

    name = "publish"
    result_model = PublishResult

    def __init__(
        self,
        trilium: TriliumClient,
        layout: Callable[[], Layout],
        llm: OpenRouterClient,
        settings: Settings,
        budget: DailyQuota,
        state: StateStore,
    ) -> None:
        self._t = trilium
        self._layout = layout
        self._llm = llm
        self._settings = settings
        self._budget = budget
        self._state = state

    def run(self, ctx: JobContext) -> PublishResult:
        layout = self._layout()
        extraction = ctx.result("extract", ExtractResult).extraction
        plan = ctx.result("resolve", ResolveResult)
        done = self._state.published(ctx.job.bookmark_id)
        by_key: dict[str, PublishedNote] = {}
        for item in plan.items:
            if item.action == "alias":
                continue
            note = done.get(item.key)
            if note is None:
                note = self._publish_item(item, ctx, layout)
                self._state.record_publish(ctx.job.bookmark_id, note)
            by_key[item.key] = note
        if extraction is not None:
            self._link_donde(extraction, plan, by_key)
        notes = [by_key[item.key] for item in plan.items if item.action != "alias"]
        decision = destination_decision(extraction, self._settings.thresholds) if extraction else "yes"
        outcome = decide_outcome(decision, notes)
        log.info("bookmark=%s publish notas=%d resultado=%s", ctx.job.bookmark_id, len(notes), outcome)
        return PublishResult(notes=notes, outcome=outcome)

    def _publish_item(self, item: PlannedItem, ctx: JobContext, layout: Layout) -> PublishedNote:
        if item.kind == ItemKind.FALLO:
            note_id = self._create_failure(ctx, layout)
        else:
            data = self._build_data(item, ctx)
            if item.action == "merge" and item.existing_note_id:
                try:
                    note_id = self._merge(item.existing_note_id, data)
                except ApiError as exc:
                    if exc.status != 404:
                        raise
                    log.warning("nota %s de fusión no existe (borrada); se crea una nueva", item.existing_note_id)
                    note_id = self._create(data, layout, ctx.job.bookmark_id)
            else:
                note_id = self._create(data, layout, ctx.job.bookmark_id)
        self._sync_review(note_id, item, ctx.job.bookmark_id, layout)
        return PublishedNote(key=item.key, note_id=note_id, action=item.action, review_reasons=item.review_reasons)

    def _build_data(self, item: PlannedItem, ctx: JobContext) -> NoteData:
        fetch = ctx.result("fetch", FetchResult)
        extraction = ctx.result("extract", ExtractResult).extraction
        if extraction is None:
            raise ValueError("no hay extracción para construir la nota")

        def entry(aporte: str):
            return source_entry(ctx.job.bookmark_id, fetch.meta, aporte)

        if item.kind == ItemKind.LUGAR:
            lugar = extraction.lugares[item.index]
            geo = ctx.result("geocode", GeocodeResult)
            match = next((o.match for o in geo.outcomes if o.lugar_index == item.index), None)
            return LugarData(
                nombre=lugar.nombre, nombre_local=lugar.nombre_local, ciudad=lugar.ciudad, region=lugar.region,
                categoria=lugar.categoria, resumen=lugar.que_es, que_hacer=lugar.que_hacer, consejos=lugar.consejos,
                precio_aprox=lugar.precio_aprox, place=match, fuentes=[entry(lugar.que_es)],
            )
        if item.kind == ItemKind.COSA:
            cosa = extraction.cosas[item.index]
            return CosaData(
                nombre=cosa.nombre, categoria=cosa.categoria, resumen=cosa.que_es, consejos=cosa.consejos,
                donde=cosa.donde, fuentes=[entry(cosa.que_es)],
            )
        if item.index == -1:
            return OtroData(
                titulo=_synthetic_title(fetch.meta), contenido=extraction.resumen_fuente,
                fuentes=[entry(extraction.resumen_fuente)],
            )
        otro = extraction.otros[item.index]
        return OtroData(titulo=otro.titulo, contenido=otro.contenido, fuentes=[entry(otro.contenido[:200])])

    def _natural_match(self, data: NoteData, layout: Layout) -> list[TNote]:
        """Notas existentes con la misma clave natural (ficha de Google; si no la hay, el nombre normalizado)."""
        if isinstance(data, LugarData) and data.place:
            return self._t.search(f'#googlePlaceId="{data.place.place_id}"', ancestor=layout.root) or near_notes(
                self._t.search(f'#jrTipo=lugar #jrNombreNorm="{name_key(data.nombre)}"', ancestor=layout.root), data.place
            )
        if isinstance(data, LugarData):
            return self._t.search(f'#jrTipo=lugar #jrNombreNorm="{name_key(data.nombre)}"', ancestor=layout.root)
        if isinstance(data, CosaData):
            return self._t.search(f'#jrTipo=cosa #jrNombreNorm="{name_key(data.nombre)}"', ancestor=layout.comprar)
        return []

    def _create(self, data: NoteData, layout: Layout, bookmark_id: str) -> str:
        """Crea (o retoma, tras un fallo a medias) la nota de `data`. Idempotente vía `#jrItem` y la clave natural."""
        if isinstance(data, LugarData):
            parent, template = layout.mapa, layout.plantilla_lugar
        elif isinstance(data, CosaData):
            parent, template = layout.categorias[data.categoria], layout.plantilla_cosa
        else:
            parent, template = layout.cultura, None
        item_id = f"{bookmark_id}:{item_identity(data)}"
        found = self._t.search(f'#jrItem="{item_id}"', ancestor=layout.root)
        if found and self._has_data(found[0].note_id):
            # La nota ya estaba completa (de una ejecución anterior): se trata como una
            # fusión para no perder "Mis notas" ni duplicar la fuente ni volver a crearla.
            return self._merge(found[0].note_id, data)
        natural = [n for n in self._natural_match(data, layout) if not found or n.note_id != found[0].note_id]
        if natural:
            # Otra fuente ya creó la nota después de que `resolve` hiciera el plan: se fusiona.
            return self._merge(natural[0].note_id, data)
        if found:
            # Retomamos una creación cortada a medias: no hay adjunto todavía, pero puede
            # haber contenido ya escrito (y hasta ediciones del usuario bajo "Mis notas").
            note = found[0]
            existing_content = self._t.get_content(note.note_id)
        else:
            created = self._t.create_note(parent, note_title(data), "text", "")
            self._t.add_label(created.note_id, "jrItem", item_id)
            note = self._t.get_note(created.note_id)
            existing_content = None
        self._t.set_content(note.note_id, compose_content(render_generated(data), existing_content))
        upsert_labels(self._t, note, labels_for(data))
        if template and template not in note.relations("template"):
            self._t.add_relation(note.note_id, "template", template)
        self._t.create_attachment(note.note_id, DATA_ATTACHMENT_TITLE, "application/json", dump_data(data))
        return note.note_id

    def _has_data(self, note_id: str) -> bool:
        return any(a.title == DATA_ATTACHMENT_TITLE for a in self._t.list_attachments(note_id))

    def _merge(self, note_id: str, new: NoteData) -> str:
        note = self._t.get_note(note_id)
        attachment = next((a for a in self._t.list_attachments(note_id) if a.title == DATA_ATTACHMENT_TITLE), None)
        old_labels: dict[str, str] = {}
        if attachment is None:
            log.warning("nota %s sin %s; se regenera con la fuente nueva", note_id, DATA_ATTACHMENT_TITLE)
            data = new
        else:
            data = load_data(self._t.get_attachment_content(attachment.attachment_id))
            old_labels = labels_for(data)
            if add_source(data, new.fuentes[0]):
                self._merge_text(data, new)
            elif type(data) is type(new) and all(f.bookmark_id == new.fuentes[0].bookmark_id for f in data.fuentes):
                # Reprocesado de una nota que solo tiene esta fuente: se regenera con la extracción
                # nueva (sin LLM). Si la nueva no tiene ficha de Google, se conserva la anterior.
                previous = data
                data = new.model_copy(deep=True)
                if isinstance(data, LugarData) and isinstance(previous, LugarData) and data.place is None:
                    data.place = previous.place
            if isinstance(data, LugarData) and isinstance(new, LugarData) and data.place is None:
                data.place = new.place
            if isinstance(data, CosaData) and isinstance(new, CosaData):
                data.donde = _unique(data.donde + new.donde)
        # El adjunto se escribe primero: si el reintento se corta después, ya se ve la fuente
        # como incorporada y no se vuelve a llamar al LLM de pago.
        if attachment is None:
            self._t.create_attachment(note_id, DATA_ATTACHMENT_TITLE, "application/json", dump_data(data))
        else:
            self._t.set_attachment_content(attachment.attachment_id, dump_data(data))
        self._t.set_content(note_id, compose_content(render_generated(data), self._t.get_content(note_id)))
        sync_labels(self._t, note, labels_for(data), old_labels)
        return note_id

    def _merge_text(self, data: NoteData, new: NoteData) -> None:
        if isinstance(data, OtroData) or isinstance(new, OtroData):
            return
        current = {"resumen": data.resumen, "que_hacer": getattr(data, "que_hacer", ""), "consejos": data.consejos}
        incoming = {"resumen": new.resumen, "que_hacer": getattr(new, "que_hacer", ""), "consejos": new.consejos}
        messages = [
            {"role": "system", "content": load_prompt("merge")},
            {"role": "user", "content": json.dumps({"actual": current, "nuevo": incoming}, ensure_ascii=False)},
        ]
        self._budget.check()
        result = self._llm.chat_json(self._settings.text_model, messages, MergeOutput.model_json_schema(), "merge")
        self._budget.add(result.cost_usd)
        try:
            merged = MergeOutput.model_validate_json(strip_fences(result.content))
        except ValidationError:
            log.warning("fusión con LLM inválida; se conservan los textos y se unen los consejos")
            merged = MergeOutput(resumen=data.resumen, que_hacer=current["que_hacer"], consejos=_unique(data.consejos + new.consejos))
        data.resumen = merged.resumen
        data.consejos = merged.consejos
        if isinstance(data, LugarData):
            data.que_hacer = merged.que_hacer

    def _create_failure(self, ctx: JobContext, layout: Layout) -> str:
        fetch = ctx.result("fetch", FetchResult)
        transcript = ctx.result("transcribe", Transcript)
        extract = ctx.result("extract", ExtractResult)
        return create_failure_note(
            self._t, layout.root, layout.revision, ctx.job.bookmark_id, fetch.meta, transcript.text, extract.error or ""
        )

    def _sync_review(self, note_id: str, item: PlannedItem, bookmark_id: str, layout: Layout) -> None:
        sync_review(self._t, self._state, note_id, item.review_reasons, bookmark_id, item.key, layout.revision)

    def _link_donde(self, extraction: Extraction, plan: ResolveResult, by_key: dict[str, PublishedNote]) -> None:
        lugar_notes: dict[str, str] = {}
        for item in plan.items:
            if item.kind != ItemKind.LUGAR:
                continue
            key = item.alias_of if item.action == "alias" else item.key
            if key in by_key:
                lugar_notes[normalize_name(extraction.lugares[item.index].nombre)] = by_key[key].note_id
        for item in plan.items:
            if item.kind != ItemKind.COSA or item.action == "alias" or item.key not in by_key:
                continue
            cosa = extraction.cosas[item.index]
            if not cosa.donde_lugares:
                continue
            note = self._t.get_note(by_key[item.key].note_id)
            linked = set(note.relations("dondeComprar"))
            for name in cosa.donde_lugares:
                target = lugar_notes.get(normalize_name(name))
                if target and target not in linked:
                    self._t.add_relation(note.note_id, "dondeComprar", target)
                    linked.add(target)
