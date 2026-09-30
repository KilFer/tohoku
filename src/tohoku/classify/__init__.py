from collections.abc import Callable

from tohoku.classify.base import Classifier
from tohoku.classify.llm import JsonSchemaClassifier, LabelClassifier
from tohoku.clients.openrouter import OpenRouterClient

# Los adaptadores de modelos con formato propio (p. ej. JEV) se registran aquí.
CLASSIFIERS: dict[str, Callable[[OpenRouterClient, str], Classifier]] = {
    "json_schema": JsonSchemaClassifier,
    "etiqueta": LabelClassifier,
}
