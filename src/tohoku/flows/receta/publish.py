import logging
from collections.abc import Callable

from tohoku.clients.trilium import TNote, TriliumClient, image_src
from tohoku.config import Settings
from tohoku.context import JobContext
from tohoku.flows.receta.extract import RecetaExtractResult
from tohoku.flows.receta.layout import RecetaLayout
from tohoku.flows.receta.models import CoverResult, RecetaData, RecetaExtraction, dump_data, load_data
from tohoku.flows.receta.params import RecetaParams
from tohoku.flows.receta.render import render_receta
from tohoku.models import FetchResult, ItemKind, PlannedItem, PublishedNote, PublishResult, ResolveResult, Transcript
from tohoku.notes import DATA_ATTACHMENT_TITLE, compose_content, name_key, source_entry
from tohoku.publishing import create_failure_note, sync_labels, sync_review
from tohoku.rules import decide_outcome, destination_decision
from tohoku.state import StateStore

log = logging.getLogger(__name__)

COVER_TITLE = "portada.jpg"
RECETA_ICON = "bx bx-bowl-rice"


class RecetaPublishStage:
    """Crea o actualiza la nota de la receta en Trilium y manda lo dudoso a la Bandeja."""

    name = "publish"
    result_model = PublishResult

    def __init__(
        self,
        trilium: TriliumClient,
        layout: Callable[[], RecetaLayout],
        settings: Settings,
        state: StateStore,
        params: RecetaParams | None = None,
    ) -> None:
        self._t = trilium
        self._layout = layout
        self._settings = settings
        self._state = state
        self._params = params or RecetaParams()

    def run(self, ctx: JobContext) -> PublishResult:
        layout = self._layout()
        extraction = ctx.result("extract", RecetaExtractResult).extraction
        plan = ctx.result("resolve", ResolveResult)
        done = self._state.published(ctx.job.bookmark_id)
        notes: list[PublishedNote] = []
        for item in plan.items:
            note = done.get(item.key)
            if note is None:
                note = self._publish_item(item, ctx, layout)
                self._state.record_publish(ctx.job.bookmark_id, note)
            notes.append(note)
        decision = destination_decision(extraction, self._settings.thresholds) if extraction else "yes"
        outcome = decide_outcome(decision, notes)
        log.info("bookmark=%s publish receta notas=%d resultado=%s", ctx.job.bookmark_id, len(notes), outcome)
        return PublishResult(notes=notes, outcome=outcome)

    def _publish_item(self, item: PlannedItem, ctx: JobContext, layout: RecetaLayout) -> PublishedNote:
        if item.kind == ItemKind.FALLO:
            fetch = ctx.result("fetch", FetchResult)
            error = ctx.result("extract", RecetaExtractResult).error or ""
            note_id = create_failure_note(
                self._t, layout.root, layout.revision, ctx.job.bookmark_id, fetch.meta, ctx.result("transcribe", Transcript).text, error
            )
        else:
            note_id = self._create_or_update(ctx, layout)
        sync_review(self._t, self._state, note_id, item.review_reasons, ctx.job.bookmark_id, item.key, layout.revision)
        return PublishedNote(key=item.key, note_id=note_id, action=item.action, review_reasons=item.review_reasons)

    def _build_data(self, ctx: JobContext) -> RecetaData:
        fetch = ctx.result("fetch", FetchResult)
        extraction = ctx.result("extract", RecetaExtractResult).extraction
        if extraction is None:
            raise ValueError("no hay extracción para construir la nota")
        return RecetaData(
            titulo=extraction.titulo, resumen=extraction.resumen, raciones=extraction.raciones, tiempo_min=extraction.tiempo_min,
            dificultad=extraction.dificultad, tipo_plato=extraction.tipo_plato, cocina=extraction.cocina,
            ingredientes=extraction.ingredientes, pasos=extraction.pasos, consejos=extraction.consejos,
            fuentes=[source_entry(ctx.job.bookmark_id, fetch.meta, extraction.resumen)],
        )

    def labels_for(self, data: RecetaData) -> dict[str, str]:
        """Atributos que gestiona el servicio. Nunca los de `atributos_usuario` (probada, valoracion…)."""
        labels = {"jrTipo": "receta", "jrNombreNorm": name_key(data.titulo), "fuentes": str(len(data.fuentes)), "iconClass": RECETA_ICON}
        for name in RecetaExtraction.model_fields:
            if name in self._params.atributos and name not in self._params.atributos_usuario and hasattr(data, name):
                value = getattr(data, name)
                if value is not None:
                    labels[name] = str(value)
        return labels

    def _create_or_update(self, ctx: JobContext, layout: RecetaLayout) -> str:
        """Crea (o retoma tras un fallo a medias, o reprocesa) la nota. Idempotente vía `#jrItem`."""
        data = self._build_data(ctx)
        item_id = f"{ctx.job.bookmark_id}:receta:{name_key(data.titulo)}"
        found = self._t.search(f'#jrItem="{item_id}"', ancestor=layout.root)
        if found:
            note, existing_content = found[0], self._t.get_content(found[0].note_id)
        else:
            created = self._t.create_note(layout.recetario, data.titulo, "text", "")
            self._t.add_label(created.note_id, "jrItem", item_id)
            note, existing_content = self._t.get_note(created.note_id), None
        attachments = self._t.list_attachments(note.note_id)
        old_labels = self._old_labels(note, attachments)
        data.portada_adjunto = self._upload_cover(note.note_id, attachments, self._cover_bytes(ctx))
        src = image_src(data.portada_adjunto, COVER_TITLE) if data.portada_adjunto else None
        self._t.set_content(note.note_id, compose_content(render_receta(data, src), existing_content))
        sync_labels(self._t, note, self.labels_for(data), old_labels)
        if layout.plantilla_receta not in note.relations("template"):
            self._t.add_relation(note.note_id, "template", layout.plantilla_receta)
        attachment = next((a for a in attachments if a.title == DATA_ATTACHMENT_TITLE), None)
        if attachment is None:
            self._t.create_attachment(note.note_id, DATA_ATTACHMENT_TITLE, "application/json", dump_data(data))
        else:
            self._t.set_attachment_content(attachment.attachment_id, dump_data(data))
        return note.note_id

    def _old_labels(self, note: TNote, attachments: list) -> dict[str, str]:
        attachment = next((a for a in attachments if a.title == DATA_ATTACHMENT_TITLE), None)
        if attachment is None:
            return {}
        return self.labels_for(load_data(self._t.get_attachment_content(attachment.attachment_id)))

    @staticmethod
    def _cover_bytes(ctx: JobContext) -> bytes | None:
        path = ctx.results.get("cover")
        if not isinstance(path, CoverResult) or not path.path or not (ctx.workdir / path.path).is_file():
            return None
        return (ctx.workdir / path.path).read_bytes()

    def _upload_cover(self, note_id: str, attachments: list, image: bytes | None) -> str | None:
        """Sube `portada.jpg`; si ya hay un adjunto con ese título se reutiliza y se vuelve a subir su binario
        (un fallo entre el POST y la subida deja un adjunto vacío). Sin portada nueva se conserva la anterior."""
        existing = next((a for a in attachments if a.title == COVER_TITLE), None)
        if image is None:
            return existing.attachment_id if existing else None
        if existing is None:
            return self._t.create_image_attachment(note_id, COVER_TITLE, image)
        self._t.set_attachment_data(existing.attachment_id, image)
        return existing.attachment_id
