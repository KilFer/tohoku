import json
import logging
from collections.abc import Callable

from pydantic import ValidationError

from japan_reader.clients.openrouter import OpenRouterClient
from japan_reader.clients.trilium import TNote, TriliumClient
from japan_reader.config import Settings
from japan_reader.context import JobContext
from japan_reader.models import (
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
    Transcript,
)
from japan_reader.notes import (
    DATA_ATTACHMENT_TITLE,
    CosaData,
    LugarData,
    NoteData,
    OtroData,
    add_source,
    compose_content,
    dump_data,
    labels_for,
    load_data,
    note_title,
    render_failure,
    render_generated,
    source_entry,
)
from japan_reader.prompts import load_prompt
from japan_reader.quota import DailyQuota
from japan_reader.rules import decide_outcome, japan_decision
from japan_reader.state import StateStore
from japan_reader.text import normalize_name, strip_fences
from japan_reader.trilium_layout import Layout

log = logging.getLogger(__name__)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def upsert_labels(trilium: TriliumClient, note: TNote, labels: dict[str, str]) -> None:
    for name, value in labels.items():
        current = note.attr("label", name)
        if current is None:
            trilium.add_label(note.note_id, name, value)
        elif current.value != value:
            trilium.update_attribute(current.attribute_id, value)


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
        decision = japan_decision(extraction, self._settings.thresholds) if extraction else "yes"
        outcome = decide_outcome(decision, notes)
        log.info("bookmark=%s publish notas=%d resultado=%s", ctx.job.bookmark_id, len(notes), outcome)
        return PublishResult(notes=notes, outcome=outcome)

    def _publish_item(self, item: PlannedItem, ctx: JobContext, layout: Layout) -> PublishedNote:
        if item.kind == ItemKind.FALLO:
            note_id = self._create_failure(ctx, layout)
        else:
            data = self._build_data(item, ctx)
            if item.action == "merge" and item.existing_note_id:
                note_id = self._merge(item.existing_note_id, data)
            else:
                note_id = self._create(data, layout)
        if item.review_reasons:
            self._send_to_review(note_id, item.review_reasons, layout)
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
                titulo=fetch.meta.title or "Sin título", contenido=extraction.resumen_fuente,
                fuentes=[entry(extraction.resumen_fuente)],
            )
        otro = extraction.otros[item.index]
        return OtroData(titulo=otro.titulo, contenido=otro.contenido, fuentes=[entry(otro.contenido[:200])])

    def _create(self, data: NoteData, layout: Layout) -> str:
        if isinstance(data, LugarData):
            parent, template = layout.mapa, layout.plantilla_lugar
        elif isinstance(data, CosaData):
            parent, template = layout.categorias[data.categoria], layout.plantilla_cosa
        else:
            parent, template = layout.cultura, None
        note = self._t.create_note(parent, note_title(data), "text", compose_content(render_generated(data), None))
        for name, value in labels_for(data).items():
            self._t.add_label(note.note_id, name, value)
        if template:
            self._t.add_relation(note.note_id, "template", template)
        self._t.create_attachment(note.note_id, DATA_ATTACHMENT_TITLE, "application/json", dump_data(data))
        return note.note_id

    def _merge(self, note_id: str, new: NoteData) -> str:
        note = self._t.get_note(note_id)
        attachment = next((a for a in self._t.list_attachments(note_id) if a.title == DATA_ATTACHMENT_TITLE), None)
        if attachment is None:
            log.warning("nota %s sin %s; se regenera con la fuente nueva", note_id, DATA_ATTACHMENT_TITLE)
            data = new
        else:
            data = load_data(self._t.get_attachment_content(attachment.attachment_id))
            if add_source(data, new.fuentes[0]):
                self._merge_text(data, new)
            if isinstance(data, LugarData) and isinstance(new, LugarData) and data.place is None:
                data.place = new.place
            if isinstance(data, CosaData) and isinstance(new, CosaData):
                data.donde = _unique(data.donde + new.donde)
        self._t.set_content(note_id, compose_content(render_generated(data), self._t.get_content(note_id)))
        upsert_labels(self._t, note, labels_for(data))
        if attachment is None:
            self._t.create_attachment(note_id, DATA_ATTACHMENT_TITLE, "application/json", dump_data(data))
        else:
            self._t.set_attachment_content(attachment.attachment_id, dump_data(data))
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
        meta = fetch.meta
        note = self._t.create_note(
            layout.revision, f"Extracción fallida: {meta.title or meta.url}", "text",
            render_failure(meta, transcript.text, extract.error or ""),
        )
        self._t.add_label(note.note_id, "jrTipo", "fallo")
        return note.note_id

    def _send_to_review(self, note_id: str, reasons: list[str], layout: Layout) -> None:
        note = self._t.get_note(note_id)
        if layout.revision not in note.parent_note_ids:
            self._t.clone(note_id, layout.revision)
        previous = (note.label("revisar") or "").split(",")
        upsert_labels(self._t, note, {"revisar": ",".join(_unique([r for r in previous + reasons if r]))})

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
