from collections.abc import Callable

from tohoku.classify.base import Classifier
from tohoku.classify.llm import JsonSchemaClassifier, LabelClassifier
from tohoku.clients.openrouter import OpenRouterClient

# Adapters for models with their own format (e.g. JEV) are registered here.
CLASSIFIERS: dict[str, Callable[[OpenRouterClient, str], Classifier]] = {
    "json_schema": JsonSchemaClassifier,
    "etiqueta": LabelClassifier,
}
