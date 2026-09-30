from tohoku.flows.base import Flow
from tohoku.flows.viaje.flow import ViajeFlow

FLOWS: dict[str, Flow] = {"viaje": ViajeFlow()}
