class TohokuError(Exception):
    """Base de los errores del servicio."""


class TransientError(TohokuError):
    """Fallo pasajero (timeout, 5xx, 429): se reintenta la etapa con espera creciente."""


class PermanentError(TohokuError):
    """La fuente no se puede procesar (borrada, privada, demasiado larga): jr:error."""


class ApiError(PermanentError):
    """Respuesta 4xx inesperada de un servicio externo."""

    def __init__(self, service: str, status: int, body: str) -> None:
        super().__init__(f"{service}: HTTP {status}: {body[:300]}")
        self.service = service
        self.status = status


class ConfigError(TohokuError):
    """Configuración inválida: se detiene el procesamiento y se avisa. No consume reintentos."""


class QuotaExceeded(TohokuError):
    """Límite diario alcanzado: el job espera al día siguiente sin consumir reintentos."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key
