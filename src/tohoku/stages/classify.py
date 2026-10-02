import logging

from tohoku.classify.base import Candidate, Classifier, ClassifierError, Verdict
from tohoku.context import JobContext
from tohoku.destinations import DestinationsConfig
from tohoku.errors import ConfigError, TransientError
from tohoku.models import Classification, FetchResult, Transcript
from tohoku.quota import DailyQuota
from tohoku.stages.extract import build_user_text

log = logging.getLogger(__name__)

MAX_IMAGES = 2


class ClassifyStage:
    """Decide which destination the link goes to among its list's candidates."""

    name = "classify"
    # Default for callers that do not look at `needs_files_for`; the pipeline uses `needs_files_for`.
    needs_files = True
    result_model = Classification

    def __init__(
        self,
        config: DestinationsConfig,
        classifier: Classifier | None,
        budget: DailyQuota,
        vision_classifier: Classifier | None = None,
    ) -> None:
        """`classifier` decides from text; `vision_classifier` (multimodal model) only when images are sent.

        Without `vision_classifier` images are never sent (the text model might not support them).
        """
        self._config = config
        self._classifier = classifier
        self._vision_classifier = vision_classifier
        self._budget = budget

    def _names(self, ctx: JobContext) -> list[str]:
        """Current candidates: those no longer in destinos.yaml do not count; if none remain, the default destination."""
        return [n for n in ctx.job.candidates or [] if n in self._config.destinos] or [self._config.destino_por_defecto]

    def _sends_images(self, fetch: FetchResult, transcript: Transcript) -> bool:
        blank = not (fetch.meta.description or "").strip() and not transcript.text.strip()
        return blank and self._vision_classifier is not None

    def needs_files_for(self, ctx: JobContext) -> bool:
        """Only needs the files if it will call the classifier with images (everything else uses stored text)."""
        if ctx.job.destination or len(self._names(ctx)) == 1:
            return False
        fetch = ctx.results.get("fetch")
        transcript = ctx.results.get("transcribe")
        if not isinstance(fetch, FetchResult) or not isinstance(transcript, Transcript):
            return True  # without previous results it cannot be known: the safe choice is to have the files
        return self._sends_images(fetch, transcript)

    def run(self, ctx: JobContext) -> Classification:
        if ctx.job.destination:
            return Classification(destino=ctx.job.destination, omitido=True)
        names = self._names(ctx)
        if len(names) == 1:
            return Classification(destino=names[0], omitido=True)
        if self._classifier is None:
            raise ConfigError("hay varios candidatos y no hay clasificador configurado")

        fetch = ctx.result("fetch", FetchResult)
        transcript = ctx.result("transcribe", Transcript)
        text = build_user_text(fetch, transcript)
        images = []
        classifier = self._classifier
        if self._sends_images(fetch, transcript):
            images = [ctx.workdir / rel for rel in (fetch.images + fetch.keyframes)[:MAX_IMAGES]]
            classifier = self._vision_classifier
        candidates = [Candidate(nombre=n, descripcion=self._config.destinos[n].descripcion) for n in names]

        cost = 0.0
        feedback: str | None = None
        problem = ""
        verdict: Verdict | None = None
        for _ in range(2):
            self._budget.check()
            try:
                verdict = classifier.classify(text, images, candidates, feedback)
            except ClassifierError as exc:
                self._budget.add(exc.cost_usd)
                cost += exc.cost_usd
                problem = f"{exc} (respuesta: {exc.raw[:200]})"
            else:
                self._budget.add(verdict.cost_usd)
                cost += verdict.cost_usd
                if verdict.destino is None or verdict.destino in names:
                    break
                problem = f"destino '{verdict.destino}' no está entre los candidatos"
                verdict = None
            feedback = f"La respuesta anterior no era válida: {problem}. Candidatos válidos: {', '.join(names)}."
        if verdict is None:
            raise TransientError(f"clasificador: respuesta no válida: {problem}")

        destino = verdict.destino
        if destino is not None and verdict.confianza < self._config.clasificador.confianza_minima:
            destino = None
        dudosa = (
            verdict.alternativa in names
            and verdict.alternativa != verdict.destino
            and verdict.confianza - verdict.confianza_alternativa < self._config.clasificador.margen_revision
        )
        return Classification(
            destino=destino, confianza=verdict.confianza, alternativa=verdict.alternativa,
            confianza_alternativa=verdict.confianza_alternativa, dudosa=dudosa, cost_usd=cost,
        )
