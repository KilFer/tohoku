class TohokuError(Exception):
    """Base of the service's errors."""


class TransientError(TohokuError):
    """Transient failure (timeout, 5xx, 429): the stage is retried with increasing wait."""


class PermanentError(TohokuError):
    """The source cannot be processed (deleted, private, too long): jr:error."""


class ApiError(PermanentError):
    """Unexpected 4xx response from an external service."""

    def __init__(self, service: str, status: int, body: str) -> None:
        super().__init__(f"{service}: HTTP {status}: {body[:300]}")
        self.service = service
        self.status = status


class ConfigError(TohokuError):
    """Invalid configuration: processing stops and a notification is sent. Does not consume retries."""


class QuotaExceeded(TohokuError):
    """Daily limit reached: the job waits until the next day without consuming retries."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key
